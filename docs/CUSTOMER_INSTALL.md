# Fortress – Easy Install (No Terminal Needed After Step 2)

**For non-technical users.** You do three things: download, run one command, then finish everything in your browser.

---

## Before you start

- **Alpaca (required):** Fortress works with **Alpaca** only. Sign up for a free [Alpaca](https://alpaca.markets/) **paper trading** account. In the [Paper Dashboard](https://app.alpaca.markets/paper/dashboard/overview) get your **API Key** and **Secret** — you’ll paste them in the browser in Step 3. No real money is used.
- **Python:** Your computer needs Python 3.10 or newer. Mac/Linux often have it; Windows: install from [python.org](https://www.python.org/downloads/) if needed.
- **Ollama (optional):** For full AI analysis, install [Ollama](https://ollama.com) and run `ollama pull llama3.2:1b`. The bot works without it; see [PREREQUISITES_AND_CLOUD.md](PREREQUISITES_AND_CLOUD.md) for details.
- **Cloud (optional):** To run 24/7 on a server (e.g. Oracle Cloud), see [PREREQUISITES_AND_CLOUD.md](PREREQUISITES_AND_CLOUD.md#3-oracle-cloud-or-any-vps--run-fortress-247).

---

## What you need (summary)

- A **computer** (Windows, Mac, or Linux) with internet.
- Your **Alpaca paper** API key and secret (see above).
- About **5 minutes**.

---

## Step 1: Download Fortress

- You received a **ZIP file** or a **link to download** the Fortress folder.
- **Unzip** it (or download and extract) to a folder, e.g. `Fortress` on your Desktop or in Documents.
- Remember where that folder is (e.g. `Desktop/Fortress`).

---

## Step 2: Run the installer (one time)

**On Mac or Linux:**

1. Open **Terminal** (search for “Terminal” in your apps).
2. Type this (replace with your actual folder path if different):
   ```bash
   cd ~/Desktop/Fortress
   ```
   Press **Enter**.
3. Type:
   ```bash
   chmod +x setup.sh start_dashboard.sh
   ./setup.sh
   ```
   Press **Enter**. Wait until you see **“Setup complete”**.
4. Then type:
   ```bash
   ./start_dashboard.sh
   ```
   Press **Enter**. **Leave this window open.** You should see a line like: **“Open in your browser: http://localhost:8083”**.

**On Windows:**

1. Open **Command Prompt** or **PowerShell**.
2. Go to your Fortress folder, e.g.:
   ```bat
   cd %USERPROFILE%\Desktop\Fortress
   ```
3. Run:
   ```bat
   python setup.py
   ```
   Wait until you see **"Setup complete"**.
4. Start the dashboard:
   ```bat
   python dashboard\command_center.py
   ```
   **Leave this window open.** In your browser open: **http://localhost:8083**

---

## Step 3: Finish in your browser (no terminal from here)

1. Open your **web browser** (Chrome, Edge, Safari, etc.).
2. In the address bar type: **http://localhost:8083** and press **Enter**.
3. You should see the **Fortress setup page**.
4. **Enter your Alpaca keys:**
   - **API Key** and **Secret** (paste from your Alpaca paper dashboard).
   - Leave **Paper trading** checked.
5. Click **“Save and test connection”**.
6. When you see **“Connection successful”**, setup is done. You can use the **Dashboard** from then on.

**Next time:** Run `./start_dashboard.sh` (Mac/Linux) or the Windows start command, then open **http://localhost:8083** in your browser. No need to enter keys again.

---

## Troubleshooting

- **“python3 not found”** – You need to install Python 3.10 or newer. On Mac: install from [python.org](https://www.python.org/downloads/). Your seller can provide a short guide.
- **“Open in your browser” doesn’t load** – Make sure you ran `./start_dashboard.sh` and left that window open. Try http://127.0.0.1:8083 if localhost doesn’t work.
- **Connection test fails** – Double-check you’re using **paper** Alpaca keys (not live) and that you copied the key and secret with no extra spaces.

---

## Optional: Ollama and running in the cloud

- **Ollama:** For AI-powered screening and analysis, install [Ollama](https://ollama.com) and pull the model (`ollama pull llama3.2:1b`). Full steps: [PREREQUISITES_AND_CLOUD.md – Ollama](PREREQUISITES_AND_CLOUD.md#2-ollama-setup-optional-but-recommended).
- **Oracle Cloud or any VPS:** To run Fortress 24/7 on a server (Ubuntu VM, Oracle Cloud free tier, etc.), see [PREREQUISITES_AND_CLOUD.md – Oracle Cloud](PREREQUISITES_AND_CLOUD.md#3-oracle-cloud-or-any-vps--run-fortress-247).

---

## Support

- Your keys are stored **only on your computer** in the Fortress folder. We never see them.
- For more help, see the rest of the docs in the `docs/` folder or contact your seller.
