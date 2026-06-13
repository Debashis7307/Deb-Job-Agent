# 🤖 Job Application AI Agent

> An autonomous AI agent that applies to 20–30 jobs daily on your behalf across LinkedIn, Naukri, Internshala, RemoteOK, and Wellfound — and sends personalized cold emails to HRs.

## 🚀 Quick Start

### 1. Run Setup Wizard
```powershell
.\venv\Scripts\python setup.py
```

### 2. Fill in Your Profile
Edit `data/user_profile.json` with your name, skills, projects, and portfolio URL.
Put your resume at `data/resume.pdf`.

### 3. Test (Dry Run — No Real Sending)
```powershell
.\venv\Scripts\python main.py --dry-run
```

### 4. Test Email Configuration
```powershell
.\venv\Scripts\python main.py --test-email
```

### 5. Run Once (Live)
```powershell
.\venv\Scripts\python main.py --run-now
```

### 6. Start Daily Scheduler (runs every day at 9 AM)
```powershell
.\venv\Scripts\python main.py
```

---

## 📁 Project Structure

```
Job Agent/
├── main.py                  # 🔑 Entry point + APScheduler
├── config.py                # Config loader
├── setup.py                 # Setup wizard
├── requirements.txt
├── .env                     # Your secrets (never commit!)
│
├── agent/
│   ├── graph.py             # LangGraph workflow
│   ├── state.py             # AgentState TypedDict
│   └── nodes/
│       ├── scrape_node.py   # Scrapes all portals
│       ├── filter_node.py   # Dedup + Gemini scoring
│       ├── apply_node.py    # Auto-apply
│       ├── email_node.py    # Cold email generation + sending
│       ├── memory_node.py   # mem0 + SQLite tracking
│       └── report_node.py   # Daily summary email
│
├── scrapers/
│   ├── remoteok_scraper.py  # Free JSON API ✅
│   ├── internshala_scraper.py # BeautifulSoup ✅
│   ├── wellfound_scraper.py # Playwright ✅
│   ├── linkedin_scraper.py  # Playwright + stealth ✅
│   └── naukri_scraper.py    # Playwright + stealth ✅
│
├── tools/
│   ├── email_finder.py      # Finds HR emails for free
│   ├── email_sender.py      # Gmail SMTP sender
│   └── resume_parser.py     # Extracts resume info
│
├── database/
│   └── tracker.db           # SQLite (auto-created)
│
└── data/
    ├── resume.pdf           # YOUR RESUME (add this!)
    └── user_profile.json    # Your details
```

---

## 🔑 Required API Keys

| Key | Where | Cost |
|-----|-------|------|
| Gemini Flash API | [aistudio.google.com](https://aistudio.google.com) | **FREE** (1500 req/day) |
| Gmail App Password | Gmail → Security → 2FA → App Passwords | **FREE** |
| mem0 API (optional) | [mem0.ai](https://mem0.ai) | **FREE** (1000 calls/month) |

---

## ⚙️ Configuration

Edit `.env` (created by setup.py):

```env
GEMINI_API_KEY=your_key
GMAIL_ADDRESS=yourname.jobs@gmail.com
GMAIL_APP_PASSWORD=xxxx_xxxx_xxxx_xxxx
DRY_RUN=True              # Set False for real applying
MAX_APPLY_PER_DAY=30
SCHEDULE_HOUR=9           # Run at 9 AM daily
```

---

## 🛡️ Anti-429 (Rate Limit Protection)

- Uses **Gemini Flash** (not Pro) — 15 RPM free
- All job scoring done in **1 batched Gemini call**
- Emails generated in **batches of 5** per call
- **Exponential backoff** on 429 errors
- Max ~10-15 Gemini calls per day (well under 1500 limit)

---

## 📊 Tracking

All applications stored in `database/tracker.db`:
- Never applies to the same job twice
- Tracks status: applied / email_sent / failed
- Daily stats + all-time totals
- Daily summary email sent to you each morning

---

## ⚠️ Important Notes

1. **LinkedIn**: Uses Playwright stealth mode (personal use only)
2. **Email limit**: Gmail free = 500/day; agent sends max 25/day
3. **Start with DRY_RUN=True** to test before going live
4. **Resume**: Must be a PDF at `data/resume.pdf`
