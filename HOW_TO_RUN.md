# 🚀 How to Run the Job Application AI Agent & Dashboard

Follow these simple instructions to run the web dashboard and start the AI agent daily job workflow on your Windows PC.

---

## 💻 1. Quick Startup Commands (Recommended)

To run the full system (both the **Web Dashboard** and the **Daily Scheduler**), follow these steps:

1. Open **PowerShell** or **Command Prompt** as Administrator.
2. Navigate to your project folder:
   ```powershell
   cd "d:\P_Files\Job Agent"
   ```
3. Run the main script using the virtual environment:
   ```powershell
   .\venv\Scripts\python -X utf8 main.py
   ```
   *This starts the Flask Web Dashboard at **http://localhost:5001** and activates the background scheduler.*

---

## 🌐 2. Accessing the Web Dashboard

- Open your web browser and go to: **[http://localhost:5001](http://localhost:5001)**
- On this dashboard, you can:
  - View all-time statistics and today's status.
  - Review all scraped jobs and detailed logs.
  - See active applications, pending cold outreach, and manual checks.
  - Click the **"Run Now"** trigger button to immediately launch the daily workflow manually.

---

## ⚡ 3. Running the Agent via CLI

If you want to run the agent directly from the terminal without starting the full dashboard + scheduler:

### A. Run Immediately in Test Mode (Dry Run)
*Highly recommended to check scraping and email generation without actually applying or sending emails.*
```powershell
.\venv\Scripts\python -X utf8 main.py --dry-run
```

### B. Run Immediately in Live Mode (Real Apply & Email)
*This will immediately scrape, apply to 20-30 jobs, and send personalized cold emails.*
```powershell
.\venv\Scripts\python -X utf8 main.py --run-now
```

### C. Test Email Configuration
*Sends two quick test emails to verify your Gmail App Password and personal address credentials are working.*
```powershell
.\venv\Scripts\python -X utf8 main.py --test-email
```

---

## 📬 4. What Happens Automatically Every Day?

1. **Daily Scheduler Run**: The agent is scheduled to start automatically **every day at 10:00 PM IST** (as long as `main.py` is running).
2. **Relevance Filter**: Scrapes tech-only roles from Internshala, remoteok, Wellfound, LinkedIn, and Naukri. Non-tech titles (e.g. video editors, graphic design, electronics, organic store assistants) are automatically ignored.
3. **Genuine HR/Founder Verification**: Verifies email domains in real-time to avoid bounces, searches DuckDuckGo for direct personal founder/HR emails, and writes customized personal emails starting with *"Hey"* (4-10 lines based on the job context).
4. **mem0 Protection**: Caches operations locally so it never uses more than 1 add and 1 retrieval request per day, completely shielding your free Hobby plan.
5. **Daily Summary Text Email**: Once completed, a simple decorated text report is automatically sent to **debashisalak@gmail.com** summarizing the run date's stats, active applications, and highlighting any **replies from HR/companies** received in your careers inbox over the last 3 days!
