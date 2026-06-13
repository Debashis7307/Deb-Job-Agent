"""
dashboard/app.py — Flask web dashboard for the Job Application AI Agent
Beautiful dark-themed UI showing all application data + trigger button

Run: .\\venv\\Scripts\\python dashboard/app.py
Then open: http://localhost:5000
"""
import sys
import os
import json
import threading
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from flask import Flask, render_template, jsonify, request, Response
from flask_cors import CORS

# Add parent dir to path so we can import config & db
sys.path.insert(0, str(Path(__file__).parent.parent))

app = Flask(__name__, template_folder="templates", static_folder="static")
CORS(app)

# Agent running state
agent_running = False
agent_log_buffer = []
MAX_LOG_LINES = 200


def is_agent_running_from_log() -> bool:
    """Helper to detect if agent CLI is running by scanning today's log file."""
    try:
        from pathlib import Path
        today = datetime.now().strftime("%Y-%m-%d")
        log_path = Path("logs") / f"agent_{today}.log"
        if not log_path.exists():
            return False
            
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
            
        for line in reversed(lines):
            if "JOB AGENT STARTING" in line:
                return True
            if "AGENT RUN COMPLETE" in line or "AGENT CRASHED" in line:
                return False
    except Exception:
        pass
    return False


def get_db():
    """Get database manager instance."""
    from database.db_manager import DatabaseManager
    import config as cfg
    return DatabaseManager(cfg.DB_PATH)


# ─── API Routes ──────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/stats")
def api_stats():
    """Overall stats for the dashboard header."""
    try:
        db = get_db()
        all_time = db.get_all_time_stats()
        today = datetime.now().strftime("%Y-%m-%d")
        today_stats = db.get_daily_stats(today)

        # Count manual applications done (where notes contains 'Manually applied')
        import sqlite3
        import config as cfg
        with sqlite3.connect(cfg.DB_PATH) as conn:
            manual_done = conn.execute(
                "SELECT COUNT(*) FROM applications WHERE notes LIKE '%Manually applied%'"
            ).fetchone()[0]

        # Get next scheduled run time (10 PM today or tomorrow)
        now = datetime.now()
        next_run = now.replace(hour=22, minute=0, second=0, microsecond=0)
        if now.hour >= 22:
            next_run += timedelta(days=1)
        time_until = str(next_run - now).split(".")[0]  # Remove microseconds

        return jsonify({
            "all_time": all_time,
            "today": today_stats,
            "next_run": next_run.strftime("%Y-%m-%d 22:00"),
            "time_until_next_run": time_until,
            "agent_running": agent_running or is_agent_running_from_log(),
            "current_time": now.strftime("%Y-%m-%d %H:%M:%S"),
            "manual_done": manual_done,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/applications")
def api_applications():
    """Get paginated application history."""
    try:
        page = int(request.args.get("page", 1))
        per_page = int(request.args.get("per_page", 50))
        status_filter = request.args.get("status", "all")
        portal_filter = request.args.get("portal", "all")

        import sqlite3
        import config as cfg

        with sqlite3.connect(cfg.DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            
            where_clauses = []
            params = []
            
            if status_filter != "all":
                where_clauses.append("status = ?")
                params.append(status_filter)
            if portal_filter != "all":
                where_clauses.append("portal = ?")
                params.append(portal_filter)
            
            where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
            
            total = conn.execute(
                f"SELECT COUNT(*) FROM applications {where_sql}", params
            ).fetchone()[0]
            
            rows = conn.execute(
                f"""SELECT job_hash, job_title, company, location, portal, status, 
                           applied_date, hr_email, email_sent, relevance_score, job_url, notes
                    FROM applications {where_sql}
                    ORDER BY created_at DESC
                    LIMIT ? OFFSET ?""",
                params + [per_page, (page - 1) * per_page]
            ).fetchall()

        applications = [dict(r) for r in rows]
        return jsonify({
            "applications": applications,
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": (total + per_page - 1) // per_page,
        })
    except Exception as e:
        return jsonify({"error": str(e), "applications": [], "total": 0}), 200


@app.route("/api/applications/<job_hash>/status", methods=["POST"])
def api_update_application_status(job_hash):
    """Update the status of an application (e.g. from manual_required to applied)."""
    try:
        data = request.get_json() or {}
        new_status = data.get("status")
        notes = data.get("notes", "Manually applied via Dashboard button")

        if not new_status:
            return jsonify({"status": "error", "message": "Missing status parameter"}), 400

        import sqlite3
        import config as cfg

        with sqlite3.connect(cfg.DB_PATH) as conn:
            conn.execute("""
                UPDATE applications 
                SET status = ?, applied_date = ?, notes = ?
                WHERE job_hash = ?
            """, (new_status, datetime.now().isoformat(), notes, job_hash))
            
            # Also update/increment daily stats for today
            today = datetime.now().strftime("%Y-%m-%d")
            existing = conn.execute(
                "SELECT * FROM daily_stats WHERE date = ?", (today,)
            ).fetchone()
            
            if existing:
                conn.execute(
                    "UPDATE daily_stats SET total_applied = total_applied + 1 WHERE date = ?",
                    (today,)
                )
            else:
                conn.execute(
                    "INSERT INTO daily_stats (date, total_applied) VALUES (?, 1)",
                    (today,)
                )

        return jsonify({"status": "success", "message": f"Updated status to {new_status}"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/daily_chart")
def api_daily_chart():
    """Get last 14 days of daily stats for the chart."""
    try:
        import sqlite3
        import config as cfg

        with sqlite3.connect(cfg.DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT date, total_applied, total_emailed, total_scraped
                FROM daily_stats
                ORDER BY date DESC
                LIMIT 14
            """).fetchall()

        data = [dict(r) for r in reversed(rows)]
        return jsonify(data)
    except Exception as e:
        return jsonify([])


@app.route("/api/run_agent", methods=["POST"])
def api_run_agent():
    """Trigger the agent to run now."""
    global agent_running, agent_log_buffer

    if agent_running:
        return jsonify({"status": "error", "message": "Agent is already running!"}), 400

    agent_log_buffer = []
    agent_running = True

    def run_in_background():
        global agent_running, agent_log_buffer
        try:
            agent_log_buffer.append(f"[{datetime.now().strftime('%H:%M:%S')}] Agent started by dashboard trigger")
            
            import config as cfg
            from agent.graph import build_job_agent_graph, get_initial_state

            agent = build_job_agent_graph()
            initial_state = get_initial_state(dry_run=cfg.DRY_RUN)

            agent_log_buffer.append(f"[{datetime.now().strftime('%H:%M:%S')}] Graph compiled. Starting workflow...")
            final_state = agent.invoke(initial_state)

            agent_log_buffer.append(f"[{datetime.now().strftime('%H:%M:%S')}] DONE! Applied: {final_state.get('total_applied', 0)} | Emailed: {final_state.get('total_emailed', 0)}")
        except Exception as e:
            agent_log_buffer.append(f"[{datetime.now().strftime('%H:%M:%S')}] ERROR: {str(e)}")
        finally:
            agent_running = False

    thread = threading.Thread(target=run_in_background, daemon=True)
    thread.start()

    return jsonify({"status": "started", "message": "Agent workflow started!"})


@app.route("/api/agent_status")
def api_agent_status():
    """Get current agent running status and recent logs."""
    running = agent_running or is_agent_running_from_log()
    logs = []
    try:
        from pathlib import Path
        today = datetime.now().strftime("%Y-%m-%d")
        log_path = Path("logs") / f"agent_{today}.log"
        if log_path.exists():
            with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
                logs = [line.strip() for line in lines[-50:]]
    except Exception:
        pass
        
    if not logs:
        logs = agent_log_buffer[-50:]

    return jsonify({
        "running": running,
        "logs": logs,
    })


@app.route("/api/logs/stream")
def api_logs_stream():
    """Server-Sent Events stream for live log updates."""
    def generate():
        import time
        from pathlib import Path
        
        # Get today's log path
        today = datetime.now().strftime("%Y-%m-%d")
        log_path = Path("logs") / f"agent_{today}.log"
        
        # Keep track of file handle and position
        f = None
        last_pos = 0
        
        # Yield initial system message
        yield f"data: {json.dumps({'line': '[SYSTEM] Connected to live agent log stream.'})}\n\n"
        
        try:
            while True:
                # Check for day rollover
                current_today = datetime.now().strftime("%Y-%m-%d")
                current_log_path = Path("logs") / f"agent_{current_today}.log"
                
                if current_log_path != log_path:
                    # Close old file if open
                    if f:
                        f.close()
                        f = None
                    log_path = current_log_path
                    last_pos = 0
                
                # Check if log file exists
                if not log_path.exists():
                    running = agent_running or is_agent_running_from_log()
                    yield f"data: {json.dumps({'heartbeat': True, 'running': running})}\n\n"
                    time.sleep(1)
                    continue
                
                # Open file if not already open
                if not f:
                    try:
                        f = open(log_path, "r", encoding="utf-8", errors="replace")
                        # Read the last 100 lines on first load to catch up
                        lines = f.readlines()
                        # Yield these lines
                        for line in lines[-100:]:
                            yield f"data: {json.dumps({'line': line.strip()})}\n\n"
                        last_pos = f.tell()
                    except Exception as e:
                        time.sleep(1)
                        continue
                
                # Check if file has new content
                try:
                    curr_size = log_path.stat().st_size
                    if curr_size < last_pos:
                        # File was truncated/rotated
                        f.seek(0)
                        last_pos = 0
                    
                    # Read new lines
                    new_lines = f.readlines()
                    if new_lines:
                        for line in new_lines:
                            yield f"data: {json.dumps({'line': line.strip()})}\n\n"
                        last_pos = f.tell()
                except Exception:
                    if f:
                        f.close()
                        f = None
                    last_pos = 0
                
                running = agent_running or is_agent_running_from_log()
                yield f"data: {json.dumps({'heartbeat': True, 'running': running})}\n\n"
                time.sleep(0.5)
        finally:
            if f:
                f.close()

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/api/portals")
def api_portals():
    """Get breakdown by portal."""
    try:
        import sqlite3
        import config as cfg

        with sqlite3.connect(cfg.DB_PATH) as conn:
            rows = conn.execute("""
                SELECT portal, COUNT(*) as count,
                       SUM(CASE WHEN status='applied' THEN 1 ELSE 0 END) as applied,
                       SUM(CASE WHEN email_sent=1 THEN 1 ELSE 0 END) as emailed
                FROM applications
                GROUP BY portal
            """).fetchall()

        return jsonify([{"portal": r[0], "count": r[1], "applied": r[2], "emailed": r[3]} for r in rows])
    except Exception as e:
        return jsonify([])


if __name__ == "__main__":
    import config as cfg
    print(f"\n{'='*50}")
    print(f"  Job Agent Dashboard")
    print(f"  Opening at: http://localhost:{cfg.DASHBOARD_PORT}")
    print(f"{'='*50}\n")
    app.run(
        host="0.0.0.0",
        port=cfg.DASHBOARD_PORT,
        debug=False,
        threaded=True,
        use_reloader=False,
    )
