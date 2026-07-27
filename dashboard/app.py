"""
dashboard/app.py — Flask web dashboard for the Job Application AI Agent
Beautiful dark-themed UI showing all application data + trigger button

Cloud-hosted version:
- Password-protected manual trigger (DASHBOARD_PASSWORD env var)
- Manual trigger fires GitHub Actions workflow (via GitHub API)
- /health endpoint for UptimeRobot keep-alive
- Reads tracker.db from repo (committed by GitHub Actions after each run)

Run locally:   .\\venv\\Scripts\\python dashboard/app.py
Cloud URL:     https://job-agent.onrender.com
"""
import sys
import os
import json
import hashlib
import threading
import requests
from datetime import datetime, timedelta
from pathlib import Path
from flask import Flask, render_template, jsonify, request, Response, session
from flask_cors import CORS

# Add parent dir to path so we can import config & db
sys.path.insert(0, str(Path(__file__).parent.parent))

app = Flask(__name__, template_folder="templates", static_folder="static")
CORS(app)

# Session secret key from env
app.secret_key = os.environ.get("DASHBOARD_SECRET_KEY", "job-agent-dashboard-secret-2024")

# Agent running state (in-process, for local runs)
agent_running = False
agent_log_buffer = []
MAX_LOG_LINES = 200

# ─── Cloud Detection ────────────────────────────────────────────────────────
IS_CLOUD = os.environ.get("CLOUD_RUN", "").lower() == "true" or \
           os.environ.get("RENDER", "").lower() == "true" or \
           os.environ.get("GH_PAT", "") != ""


# ─── GitHub Actions Integration ─────────────────────────────────────────────

def get_github_config():
    """Get GitHub config from environment variables."""
    return {
        "token": os.environ.get("GH_PAT", ""),
        "owner": os.environ.get("GITHUB_REPO_OWNER", "Debashis7307"),
        "repo": os.environ.get("GITHUB_REPO_NAME", "Deb-Job-Agent"),
        "workflow_id": os.environ.get("GITHUB_WORKFLOW_ID", "job_agent.yml"),
    }


def trigger_github_actions(dry_run: bool = False) -> dict:
    """
    Trigger the GitHub Actions workflow via API.
    Returns {"success": bool, "message": str, "run_url": str}
    """
    cfg = get_github_config()

    if not cfg["token"]:
        return {
            "success": False,
            "message": "GitHub PAT not configured. Running locally instead.",
            "run_url": ""
        }

    url = f"https://api.github.com/repos/{cfg['owner']}/{cfg['repo']}/actions/workflows/{cfg['workflow_id']}/dispatches"

    headers = {
        "Authorization": f"Bearer {cfg['token']}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    payload = {
        "ref": "main",
        "inputs": {
            "dry_run": "true" if dry_run else "false",
            "triggered_by": "dashboard-manual",
        }
    }

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=15)
        if resp.status_code == 204:
            run_url = f"https://github.com/{cfg['owner']}/{cfg['repo']}/actions"
            return {
                "success": True,
                "message": "✅ Agent triggered on GitHub Actions! Check the Actions tab for live progress.",
                "run_url": run_url,
            }
        else:
            return {
                "success": False,
                "message": f"GitHub API error: {resp.status_code} — {resp.text[:200]}",
                "run_url": ""
            }
    except Exception as e:
        return {
            "success": False,
            "message": f"Failed to trigger GitHub Actions: {str(e)}",
            "run_url": ""
        }


def get_latest_github_run() -> dict:
    """Get the status of the latest GitHub Actions workflow run."""
    cfg = get_github_config()

    if not cfg["token"]:
        return {}

    url = f"https://api.github.com/repos/{cfg['owner']}/{cfg['repo']}/actions/workflows/{cfg['workflow_id']}/runs?per_page=1"

    headers = {
        "Authorization": f"Bearer {cfg['token']}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    try:
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            runs = data.get("workflow_runs", [])
            if runs:
                run = runs[0]
                return {
                    "status": run.get("status"),           # queued / in_progress / completed
                    "conclusion": run.get("conclusion"),   # success / failure / cancelled
                    "created_at": run.get("created_at"),
                    "run_number": run.get("run_number"),
                    "html_url": run.get("html_url"),
                }
    except Exception:
        pass
    return {}


# ─── Password Authentication ────────────────────────────────────────────────

def verify_password(provided: str) -> bool:
    """
    Verify the dashboard password.
    Compares against DASHBOARD_PASSWORD environment variable.
    Uses constant-time comparison to prevent timing attacks.
    """
    correct = os.environ.get("DASHBOARD_PASSWORD", "")
    if not correct or not provided:
        return False
    # Use hmac-safe comparison
    import hmac
    return hmac.compare_digest(
        hashlib.sha256(provided.encode()).hexdigest(),
        hashlib.sha256(correct.encode()).hexdigest()
    )


# ─── Helpers ────────────────────────────────────────────────────────────────

def is_agent_running_from_log() -> bool:
    """Helper to detect if agent CLI is running by scanning today's log file."""
    try:
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
    try:
        from database.db_manager import DatabaseManager
        import config as cfg
        return DatabaseManager(cfg.DB_PATH)
    except Exception:
        return None


def get_db_path():
    """Get database path, works both locally and on cloud."""
    try:
        import config as cfg
        return cfg.DB_PATH
    except Exception:
        # Fallback for cloud dashboard without full config
        base = Path(__file__).parent.parent
        return str(base / "database" / "tracker.db")


# ─── Routes ─────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/health")
def health():
    """Health check endpoint — used by UptimeRobot to keep dashboard alive."""
    return jsonify({
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
        "service": "Job Agent Dashboard",
    })


@app.route("/api/auth", methods=["POST"])
def api_auth():
    """
    Verify the dashboard password before running the agent.
    Returns 200 + token on success, 403 on failure.
    """
    data = request.get_json() or {}
    password = data.get("password", "")

    if verify_password(password):
        # Create a short-lived session token
        session["authenticated"] = True
        session["auth_time"] = datetime.now().isoformat()
        return jsonify({
            "status": "success",
            "message": "Authentication successful! Starting agent...",
        })
    else:
        return jsonify({
            "status": "error",
            "message": "You are not Debashis, so I can't work for you! 🚫",
        }), 403


@app.route("/api/stats")
def api_stats():
    """Overall stats for the dashboard header."""
    try:
        import sqlite3

        db_path = get_db_path()

        if not Path(db_path).exists():
            # DB not yet synced from GitHub
            return jsonify({
                "all_time": {"total_applied": 0, "total_emailed": 0, "total_scraped": 0},
                "today": {"total_applied": 0, "total_emailed": 0},
                "next_run": "",
                "time_until_next_run": "calculating...",
                "agent_running": False,
                "current_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "manual_done": 0,
                "latest_gh_run": get_latest_github_run(),
            })

        db = get_db()
        all_time = db.get_all_time_stats() if db else {}
        today_str = datetime.now().strftime("%Y-%m-%d")
        today_stats = db.get_daily_stats(today_str) if db else {}

        manual_done = 0
        with sqlite3.connect(db_path) as conn:
            manual_done = conn.execute(
                "SELECT COUNT(*) FROM applications WHERE notes LIKE '%Manually applied%'"
            ).fetchone()[0]

        # Next run at 10 PM IST
        import pytz
        tz = pytz.timezone("Asia/Kolkata")
        now_ist = datetime.now(tz)
        next_run = now_ist.replace(hour=22, minute=0, second=0, microsecond=0)
        if now_ist.hour >= 22:
            next_run += timedelta(days=1)
        time_until = str(next_run - now_ist).split(".")[0]

        # GitHub Actions latest run status
        gh_run = get_latest_github_run()
        is_running = (agent_running or is_agent_running_from_log() or
                      gh_run.get("status") == "in_progress" or
                      gh_run.get("status") == "queued")

        return jsonify({
            "all_time": all_time,
            "today": today_stats,
            "next_run": next_run.strftime("%Y-%m-%d 22:00 IST"),
            "time_until_next_run": time_until,
            "agent_running": is_running,
            "current_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "manual_done": manual_done,
            "latest_gh_run": gh_run,
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
        db_path = get_db_path()

        if not Path(db_path).exists():
            return jsonify({"applications": [], "total": 0, "page": 1,
                            "per_page": per_page, "total_pages": 0})

        with sqlite3.connect(db_path) as conn:
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
        db_path = get_db_path()

        with sqlite3.connect(db_path) as conn:
            conn.execute("""
                UPDATE applications
                SET status = ?, applied_date = ?, notes = ?
                WHERE job_hash = ?
            """, (new_status, datetime.now().isoformat(), notes, job_hash))

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
        db_path = get_db_path()

        if not Path(db_path).exists():
            return jsonify([])

        with sqlite3.connect(db_path) as conn:
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
    """
    Trigger the agent to run now.
    Requires valid password in request body.
    On cloud: triggers GitHub Actions workflow.
    On local: runs agent in background thread.
    """
    global agent_running, agent_log_buffer

    data = request.get_json() or {}
    password = data.get("password", "")

    # ── Password verification ─────────────────────────────
    if not verify_password(password):
        return jsonify({
            "status": "error",
            "message": "You are not Debashis, so I can't work for you! 🚫"
        }), 403

    dry_run = data.get("dry_run", False)

    # ── Cloud mode: trigger GitHub Actions ───────────────
    if IS_CLOUD:
        result = trigger_github_actions(dry_run=dry_run)
        if result["success"]:
            return jsonify({
                "status": "started",
                "message": result["message"],
                "run_url": result["run_url"],
                "mode": "github_actions",
            })
        else:
            return jsonify({
                "status": "error",
                "message": result["message"],
            }), 500

    # ── Local mode: run in background thread ─────────────
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

            agent_log_buffer.append(
                f"[{datetime.now().strftime('%H:%M:%S')}] DONE! "
                f"Applied: {final_state.get('total_applied', 0)} | "
                f"Emailed: {final_state.get('total_emailed', 0)}"
            )
        except Exception as e:
            agent_log_buffer.append(f"[{datetime.now().strftime('%H:%M:%S')}] ERROR: {str(e)}")
        finally:
            agent_running = False

    thread = threading.Thread(target=run_in_background, daemon=True)
    thread.start()

    return jsonify({
        "status": "started",
        "message": "Agent workflow started locally!",
        "mode": "local",
    })


@app.route("/api/agent_status")
def api_agent_status():
    """Get current agent running status and recent logs."""
    gh_run = get_latest_github_run()
    gh_running = gh_run.get("status") in ("in_progress", "queued")

    running = agent_running or is_agent_running_from_log() or gh_running
    logs = []

    try:
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
        "github_run": gh_run,
    })


@app.route("/api/logs/stream")
def api_logs_stream():
    """Server-Sent Events stream for live log updates."""
    def generate():
        import time

        today = datetime.now().strftime("%Y-%m-%d")
        log_path = Path("logs") / f"agent_{today}.log"

        f = None
        last_pos = 0

        yield f"data: {json.dumps({'line': '[SYSTEM] Connected to live agent log stream.'})}\\n\\n"

        try:
            while True:
                current_today = datetime.now().strftime("%Y-%m-%d")
                current_log_path = Path("logs") / f"agent_{current_today}.log"

                if current_log_path != log_path:
                    if f:
                        f.close()
                        f = None
                    log_path = current_log_path
                    last_pos = 0

                if not log_path.exists():
                    gh_run = get_latest_github_run()
                    running = agent_running or is_agent_running_from_log() or \
                              gh_run.get("status") in ("in_progress", "queued")
                    yield f"data: {json.dumps({'heartbeat': True, 'running': running, 'github_run': gh_run})}\\n\\n"
                    time.sleep(2)
                    continue

                if not f:
                    try:
                        f = open(log_path, "r", encoding="utf-8", errors="replace")
                        lines = f.readlines()
                        for line in lines[-100:]:
                            yield f"data: {json.dumps({'line': line.strip()})}\\n\\n"
                        last_pos = f.tell()
                    except Exception:
                        time.sleep(1)
                        continue

                try:
                    curr_size = log_path.stat().st_size
                    if curr_size < last_pos:
                        f.seek(0)
                        last_pos = 0

                    new_lines = f.readlines()
                    if new_lines:
                        for line in new_lines:
                            yield f"data: {json.dumps({'line': line.strip()})}\\n\\n"
                        last_pos = f.tell()
                except Exception:
                    if f:
                        f.close()
                        f = None
                    last_pos = 0

                gh_run = get_latest_github_run()
                running = agent_running or is_agent_running_from_log() or \
                          gh_run.get("status") in ("in_progress", "queued")
                yield f"data: {json.dumps({'heartbeat': True, 'running': running, 'github_run': gh_run})}\\n\\n"
                time.sleep(2)
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
        db_path = get_db_path()

        if not Path(db_path).exists():
            return jsonify([])

        with sqlite3.connect(db_path) as conn:
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
    port = int(os.environ.get("PORT", cfg.DASHBOARD_PORT))
    print(f"\n{'='*50}")
    print(f"  Job Agent Dashboard")
    print(f"  Opening at: http://localhost:{port}")
    print(f"  Cloud mode: {IS_CLOUD}")
    print(f"{'='*50}\n")
    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
        threaded=True,
        use_reloader=False,
    )
