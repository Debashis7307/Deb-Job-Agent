/* ============================================
   Job Agent Dashboard — JavaScript
   Real-time updates, chart, agent control
   ============================================ */

let currentPage = 1;
let chartInstance = null;
let sseSource = null;

// ─── Initialize ──────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
  updateClock();
  setInterval(updateClock, 1000);
  setInterval(updateCountdown, 1000);

  loadStats();
  loadApplications(1);
  loadDailyChart();
  loadPortals();
  startSSELogs();

  // Auto-refresh stats every 30 seconds
  setInterval(loadStats, 30000);
  setInterval(loadPortals, 60000);
});

// ─── Clock ────────────────────────────────────────────────────
function updateClock() {
  const now = new Date();
  const timeStr = now.toLocaleTimeString("en-IN", {
    hour: "2-digit", minute: "2-digit", second: "2-digit",
    hour12: false, timeZone: "Asia/Kolkata"
  });
  document.getElementById("navClock").textContent = timeStr;
}

// ─── Countdown to 10 PM ───────────────────────────────────────
function updateCountdown() {
  const now = new Date();
  const istOffset = 5.5 * 60 * 60 * 1000;
  const ist = new Date(now.getTime() + istOffset - now.getTimezoneOffset() * 60000);
  
  let next = new Date(ist);
  next.setHours(22, 0, 0, 0);
  if (ist.getHours() >= 22) {
    next.setDate(next.getDate() + 1);
  }
  
  const diff = next - ist;
  const h = Math.floor(diff / 3600000).toString().padStart(2, "0");
  const m = Math.floor((diff % 3600000) / 60000).toString().padStart(2, "0");
  const s = Math.floor((diff % 60000) / 1000).toString().padStart(2, "0");
  
  document.getElementById("countdown").textContent = `${h}:${m}:${s}`;
}

// ─── Stats ────────────────────────────────────────────────────
async function loadStats() {
  try {
    const res = await fetch("/api/stats");
    const data = await res.json();

    animateNumber("totalApplied", data.all_time?.total_applied || 0);
    animateNumber("totalEmailed", data.all_time?.total_emailed || 0);
    animateNumber("totalCompanies", data.all_time?.unique_companies || 0);
    animateNumber("totalScraped", data.today?.total_scraped || 0);
    animateNumber("totalManualDone", data.manual_done || 0);

    document.getElementById("todayApplied").textContent =
      `Today: ${data.today?.total_applied || 0}`;
    document.getElementById("todayEmailed").textContent =
      `Today: ${data.today?.total_emailed || 0}`;
    document.getElementById("newToday").textContent =
      `New today: ${data.today?.total_new || 0}`;

    if (data.next_run) {
      document.getElementById("nextRunTime").textContent = "22:00 IST";
    }

    updateAgentStatus(data.agent_running);
    updateGHRunStatus(data);

  } catch (err) {
    console.warn("Stats load failed:", err);
  }
}

function animateNumber(id, target) {
  const el = document.getElementById(id);
  if (!el) return;
  const current = parseInt(el.textContent.replace(/,/g, "")) || 0;
  const diff = target - current;
  if (diff === 0) return;
  
  const steps = 20;
  let step = 0;
  const timer = setInterval(() => {
    step++;
    el.textContent = Math.round(current + (diff * step / steps)).toLocaleString();
    if (step >= steps) clearInterval(timer);
  }, 30);
}

// ─── Agent Status ─────────────────────────────────────────────
function updateAgentStatus(running) {
  const dot = document.getElementById("statusDot");
  const text = document.getElementById("statusText");
  const btn = document.getElementById("btnRunAgent");
  const btnLarge = document.getElementById("btnRunLarge");
  const pill = document.getElementById("agentStatusPill");

  if (running) {
    dot.classList.add("running");
    text.textContent = "Running...";
    if (btn) { btn.disabled = true; btn.textContent = "Running..."; }
    if (btnLarge) { btnLarge.disabled = true; btnLarge.innerHTML = `<span class="spin">⟳</span> Agent Running...`; }
    pill.style.borderColor = "rgba(16,185,129,0.3)";
  } else {
    dot.classList.remove("running");
    text.textContent = "Idle";
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M12 1C8.676 1 6 3.676 6 7v1H4v14h16V8h-2V7c0-3.324-2.676-6-6-6zm0 2c2.276 0 4 1.724 4 4v1H8V7c0-2.276 1.724-4 4-4zm0 9a2 2 0 1 1 0 4 2 2 0 0 1 0-4z"/></svg> Run Agent Now`;
    }
    if (btnLarge) {
      btnLarge.disabled = false;
      btnLarge.innerHTML = `<svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor"><path d="M12 1C8.676 1 6 3.676 6 7v1H4v14h16V8h-2V7c0-3.324-2.676-6-6-6zm0 2c2.276 0 4 1.724 4 4v1H8V7c0-2.276 1.724-4 4-4zm0 9a2 2 0 1 1 0 4 2 2 0 0 1 0-4z"/></svg> Run Agent Now`;
    }
    pill.style.borderColor = "";
  }

  // Update GitHub Actions status badge
  updateGHRunStatus(data);
}

// ─── Trigger Agent (Password Protected) ──────────────────────
function triggerAgent() {
  // Reset modal state
  const pwInput = document.getElementById("agentPassword");
  const errEl = document.getElementById("authError");
  if (pwInput) pwInput.value = "";
  if (errEl) { errEl.style.display = "none"; errEl.textContent = ""; }

  document.getElementById("runModal").classList.add("show");

  // Auto-focus password field
  setTimeout(() => {
    if (pwInput) pwInput.focus();
  }, 100);
}

function closeModal() {
  document.getElementById("runModal").classList.remove("show");
}

function togglePasswordVisibility() {
  const pwInput = document.getElementById("agentPassword");
  const eyeIcon = document.getElementById("eyeIcon");
  if (!pwInput) return;

  if (pwInput.type === "password") {
    pwInput.type = "text";
    eyeIcon.innerHTML = `<path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/>` ;
  } else {
    pwInput.type = "password";
    eyeIcon.innerHTML = `<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/>`;
  }
}

async function confirmRun() {
  const pwInput = document.getElementById("agentPassword");
  const errEl = document.getElementById("authError");
  const confirmBtn = document.getElementById("btnConfirmRun");
  const password = pwInput ? pwInput.value.trim() : "";
  const dryRun = document.getElementById("dryRunToggle").checked;

  if (!password) {
    if (errEl) { errEl.textContent = "Please enter your secret key."; errEl.style.display = "block"; }
    return;
  }

  // Disable button during request
  if (confirmBtn) { confirmBtn.disabled = true; confirmBtn.textContent = "Verifying..."; }

  try {
    const res = await fetch("/api/run_agent", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password, dry_run: dryRun }),
    });
    const data = await res.json();

    if (res.status === 403) {
      // Wrong password — show rejection
      if (errEl) {
        errEl.textContent = data.message || "You are not Debashis, so I can't work for you! 🚫";
        errEl.style.display = "block";
        errEl.style.color = "#ff6b6b";
      }
      if (confirmBtn) { confirmBtn.disabled = false; confirmBtn.textContent = "🚀 Start Agent"; }
      return;
    }

    if (data.status === "started") {
      closeModal();
      addLog(`[${getTime()}] ✅ Agent triggered! Mode: ${data.mode || 'cloud'}`, "success");

      if (data.mode === "github_actions" && data.run_url) {
        addLog(`[${getTime()}] 🔗 GitHub Actions: ${data.run_url}`, "info");
        showGHRunBanner(data.run_url);
      }

      updateAgentStatus(true);
      animateWorkflowSteps();
    } else {
      if (errEl) { errEl.textContent = data.message; errEl.style.display = "block"; }
      if (confirmBtn) { confirmBtn.disabled = false; confirmBtn.textContent = "🚀 Start Agent"; }
    }
  } catch (err) {
    if (errEl) { errEl.textContent = `Network error: ${err}`; errEl.style.display = "block"; }
    if (confirmBtn) { confirmBtn.disabled = false; confirmBtn.textContent = "🚀 Start Agent"; }
  }
}

// ─── GitHub Actions Status Banner ────────────────────────────
function showGHRunBanner(url) {
  const banner = document.getElementById("ghRunStatus");
  const link = document.getElementById("ghRunLink");
  if (banner) { banner.style.display = "flex"; }
  if (link) { link.href = url; }
}

function updateGHRunStatus(statsData) {
  const ghRun = statsData?.latest_gh_run;
  const banner = document.getElementById("ghRunStatus");
  const dot = document.getElementById("ghRunDot");
  const text = document.getElementById("ghRunText");
  const link = document.getElementById("ghRunLink");
  if (!banner || !ghRun || !ghRun.status) return;

  banner.style.display = "flex";
  if (link && ghRun.html_url) link.href = ghRun.html_url;

  if (ghRun.status === "in_progress" || ghRun.status === "queued") {
    dot.style.background = "#f59e0b";
    dot.style.animation = "pulse 1s infinite";
    text.textContent = `GitHub Actions: Run #${ghRun.run_number} ${ghRun.status}...`;
  } else if (ghRun.conclusion === "success") {
    dot.style.background = "#10b981";
    dot.style.animation = "none";
    text.textContent = `Last run #${ghRun.run_number}: ✅ Success`;
  } else if (ghRun.conclusion === "failure") {
    dot.style.background = "#ef4444";
    dot.style.animation = "none";
    text.textContent = `Last run #${ghRun.run_number}: ❌ Failed`;
  } else {
    text.textContent = `Last run #${ghRun.run_number}: ${ghRun.status}`;
  }
}

// ─── Workflow Step Animation ──────────────────────────────────
function animateWorkflowSteps() {
  const steps = ["step1", "step2", "step3", "step4", "step5"];
  let i = 0;
  
  // Reset all
  steps.forEach(s => {
    const el = document.getElementById(s);
    if (el) { el.classList.remove("active", "done"); }
  });

  const timer = setInterval(() => {
    if (i > 0) {
      const prev = document.getElementById(steps[i - 1]);
      if (prev) { prev.classList.remove("active"); prev.classList.add("done"); }
    }
    if (i < steps.length) {
      const curr = document.getElementById(steps[i]);
      if (curr) curr.classList.add("active");
      i++;
    } else {
      clearInterval(timer);
    }
  }, 3000); // Each step for 3 seconds
}

// ─── Live Logs via SSE ────────────────────────────────────────
function startSSELogs() {
  if (sseSource) sseSource.close();
  
  sseSource = new EventSource("/api/logs/stream");
  
  sseSource.onmessage = (event) => {
    const data = JSON.parse(event.data);
    if (data.line) {
      addLog(data.line, classifyLog(data.line));
    }
    if (data.heartbeat !== undefined) {
      updateAgentStatus(data.running);
    }
  };

  sseSource.onerror = () => {
    console.warn("SSE disconnected. Will retry.");
  };
}

function classifyLog(line) {
  const l = line.toLowerCase();
  if (l.includes("error") || l.includes("fail") || l.includes("crash")) return "error";
  if (l.includes("warning") || l.includes("warn")) return "warning";
  if (l.includes("done") || l.includes("success") || l.includes("sent") || l.includes("applied")) return "success";
  if (l.includes("[system]")) return "system";
  return "info";
}

function addLog(text, type = "info") {
  const terminal = document.getElementById("logTerminal");
  const div = document.createElement("div");
  div.className = `log-line log-${type}`;
  div.textContent = text;
  terminal.appendChild(div);
  terminal.scrollTop = terminal.scrollHeight;
  
  // Limit to 200 lines
  while (terminal.children.length > 200) {
    terminal.removeChild(terminal.firstChild);
  }
}

function clearLogs() {
  const terminal = document.getElementById("logTerminal");
  terminal.innerHTML = `<div class="log-line log-system">[${getTime()}] Log cleared.</div>`;
}

function getTime() {
  return new Date().toLocaleTimeString("en-IN", {
    hour: "2-digit", minute: "2-digit", second: "2-digit",
    hour12: false, timeZone: "Asia/Kolkata"
  });
}

// ─── Applications Table ───────────────────────────────────────
async function loadApplications(page = 1) {
  currentPage = page;
  const status = document.getElementById("filterStatus").value;
  const portal = document.getElementById("filterPortal").value;

  try {
    const res = await fetch(
      `/api/applications?page=${page}&per_page=20&status=${status}&portal=${portal}`
    );
    const data = await res.json();

    renderApplications(data.applications || []);
    renderPagination(data.total_pages || 1, page);

  } catch (err) {
    document.getElementById("appTableBody").innerHTML =
      `<tr><td colspan="8" class="table-empty">Failed to load data.</td></tr>`;
  }
}

function renderApplications(apps) {
  const tbody = document.getElementById("appTableBody");
  if (!apps.length) {
    tbody.innerHTML = `<tr><td colspan="8" class="table-empty">No applications yet. Run the agent to get started!</td></tr>`;
    return;
  }

  tbody.innerHTML = apps.map(app => {
    const statusBadge = getStatusBadge(app.status, app.job_url, app.job_hash, app.notes || "");
    const portalBadge = `<span class="portal-badge portal-${app.portal}">${app.portal}</span>`;
    const emailIcon = app.email_sent
      ? `<span class="email-check">✓</span>`
      : `<span class="email-x">—</span>`;
    const score = parseFloat(app.relevance_score || 0);
    const scoreBar = `
      <div class="score-bar">
        <div class="score-fill">
          <div class="score-fill-inner" style="width:${score * 10}%"></div>
        </div>
        <span class="score-num">${score.toFixed(1)}</span>
      </div>`;
    const date = app.applied_date
      ? new Date(app.applied_date).toLocaleDateString("en-IN", { day: "2-digit", month: "short" })
      : "—";
    const titleLink = app.job_url
      ? `<a href="${app.job_url}" target="_blank" style="color:var(--accent-blue);text-decoration:none;" 
           title="${app.job_url}">${app.job_title || "Unknown"}</a>`
      : (app.job_title || "Unknown");

    return `
      <tr>
        <td>${titleLink}</td>
        <td style="font-weight:500;color:var(--text-primary)">${app.company || "—"}</td>
        <td>${portalBadge}</td>
        <td style="max-width:120px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${app.location || "—"}</td>
        <td>${statusBadge}</td>
        <td>${date}</td>
        <td>${emailIcon}</td>
        <td>${scoreBar}</td>
      </tr>`;
  }).join("");
}

function getStatusBadge(status, url = "", job_hash = "", notes = "") {
  if (status === "applied" && notes.includes("Manually applied")) {
    return `<span class="badge badge-manual-done">✓ Done</span>`;
  }

  if ((status === "manual_required" || status === "new") && url && job_hash) {
    return `<button onclick="manualApply('${url}', '${job_hash}', this)" class="btn-table-apply-fire">🔥 Apply</button>`;
  }

  const map = {
    "applied":         `<span class="badge badge-applied">✓ Applied</span>`,
    "email_sent":      `<span class="badge badge-email">✉ Emailed</span>`,
    "manual_required": `<span class="badge badge-manual">⚠ Manual</span>`,
    "failed":          `<span class="badge badge-failed">✗ Failed</span>`,
    "new":             `<span class="badge badge-new">○ New</span>`,
  };
  return map[status] || `<span class="badge">${status}</span>`;
}

function renderPagination(totalPages, currentPage) {
  const div = document.getElementById("tablePagination");
  if (totalPages <= 1) { div.innerHTML = ""; return; }

  let html = "";
  if (currentPage > 1) {
    html += `<button class="page-btn" onclick="loadApplications(${currentPage - 1})">← Prev</button>`;
  }
  for (let i = Math.max(1, currentPage - 2); i <= Math.min(totalPages, currentPage + 2); i++) {
    html += `<button class="page-btn ${i === currentPage ? "active" : ""}" onclick="loadApplications(${i})">${i}</button>`;
  }
  if (currentPage < totalPages) {
    html += `<button class="page-btn" onclick="loadApplications(${currentPage + 1})">Next →</button>`;
  }
  div.innerHTML = html;
}

// ─── Activity Chart ───────────────────────────────────────────
async function loadDailyChart() {
  try {
    const res = await fetch("/api/daily_chart");
    const data = await res.json();

    const labels = data.map(d => {
      const date = new Date(d.date);
      return date.toLocaleDateString("en-IN", { day: "2-digit", month: "short" });
    });
    const applied = data.map(d => d.total_applied || 0);
    const emailed = data.map(d => d.total_emailed || 0);

    const ctx = document.getElementById("activityChart").getContext("2d");
    if (chartInstance) chartInstance.destroy();

    chartInstance = new Chart(ctx, {
      type: "bar",
      data: {
        labels,
        datasets: [
          {
            label: "Applied",
            data: applied,
            backgroundColor: "rgba(99,102,241,0.7)",
            borderColor: "rgba(99,102,241,1)",
            borderWidth: 1, borderRadius: 4,
          },
          {
            label: "Emailed",
            data: emailed,
            backgroundColor: "rgba(245,158,11,0.7)",
            borderColor: "rgba(245,158,11,1)",
            borderWidth: 1, borderRadius: 4,
          },
        ],
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: {
          legend: {
            labels: { color: "#8b9ab8", font: { family: "Inter", size: 12 } }
          },
          tooltip: {
            backgroundColor: "#0d1117",
            borderColor: "#1f2937", borderWidth: 1,
            titleColor: "#f0f4ff", bodyColor: "#8b9ab8",
          },
        },
        scales: {
          x: {
            grid: { color: "rgba(31,41,55,0.5)" },
            ticks: { color: "#4b5568", font: { family: "Inter", size: 11 } },
          },
          y: {
            grid: { color: "rgba(31,41,55,0.5)" },
            ticks: { color: "#4b5568", font: { family: "Inter", size: 11 }, precision: 0 },
            beginAtZero: true,
          },
        },
      },
    });
  } catch (err) {
    console.warn("Chart load failed:", err);
  }
}

// ─── Portal Breakdown ─────────────────────────────────────────
async function loadPortals() {
  try {
    const res = await fetch("/api/portals");
    const data = await res.json();

    const portalConfig = {
      linkedin:       { label: "LinkedIn",    logo: "LI", cls: "logo-li" },
      naukri:         { label: "Naukri",      logo: "NK", cls: "logo-nk" },
      internshala:    { label: "Internshala", logo: "IS", cls: "logo-is" },
      remoteok:       { label: "RemoteOK",    logo: "RO", cls: "logo-ro" },
      wellfound:      { label: "Wellfound",   logo: "WF", cls: "logo-wf" },
      weworkremotely: { label: "WWR",         logo: "WR", cls: "logo-wwr" },
    };

    const defaultPortals = Object.keys(portalConfig).map(key => ({
      portal: key, count: 0, applied: 0, emailed: 0
    }));

    // Merge with actual data
    const merged = defaultPortals.map(def => {
      const actual = data.find(d => d.portal === def.portal);
      return actual || def;
    });

    const html = merged.map(p => {
      const cfg = portalConfig[p.portal] || { label: p.portal, logo: "?", cls: "" };
      return `
        <div class="portal-item">
          <div class="portal-logo ${cfg.cls}">${cfg.logo}</div>
          <div class="portal-info">
            <div class="portal-name">${cfg.label}</div>
            <div class="portal-stats">Applied: ${p.applied} · Emailed: ${p.emailed}</div>
          </div>
          <div class="portal-count">${p.count}</div>
        </div>`;
    }).join("");

    document.getElementById("portalList").innerHTML = html || "<div class='loading-spinner'>No data yet</div>";

  } catch (err) {
    document.getElementById("portalList").innerHTML =
      "<div class='loading-spinner'>Error loading portals</div>";
  }
}

// ─── Close modal on outside click ────────────────────────────
document.getElementById("runModal").addEventListener("click", function(e) {
  if (e.target === this) closeModal();
});

// ─── Keyboard shortcut: R to run ─────────────────────────────
document.addEventListener("keydown", (e) => {
  if (e.key === "r" && !e.ctrlKey && !e.metaKey && 
      document.activeElement.tagName !== "INPUT" &&
      document.activeElement.tagName !== "SELECT") {
    triggerAgent();
  }
  if (e.key === "Escape") closeModal();
});

// ─── Manual Apply Button Callback ────────────────────────────
async function manualApply(url, jobHash, buttonEl) {
  // 1. Open job page in a new browser tab
  window.open(url, '_blank');
  
  // 2. Disable button immediately and show loading
  buttonEl.disabled = true;
  buttonEl.textContent = "Updating...";
  
  try {
    const res = await fetch(`/api/applications/${jobHash}/status`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status: "applied", notes: "Manually applied via Dashboard button" })
    });
    const data = await res.json();
    
    if (data.status === "success") {
      // 3. Transform to green static badge
      const parent = buttonEl.parentElement;
      parent.innerHTML = `<span class="badge badge-manual-done">✓ Done</span>`;
      
      // 4. Update the statistics counters on dashboard
      loadStats();
    } else {
      buttonEl.disabled = false;
      buttonEl.textContent = "🔥 Apply";
      console.warn("Failed to update status: " + data.message);
    }
  } catch (err) {
    buttonEl.disabled = false;
    buttonEl.textContent = "🔥 Apply";
    console.warn("Failed to connect to API: " + err);
  }
}
