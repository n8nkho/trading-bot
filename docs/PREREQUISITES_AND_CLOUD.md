# Fortress – Prerequisites, Alpaca, Ollama & Cloud Setup

This guide covers **what you need before installing** and **optional 24/7 cloud setup** (e.g. Oracle Cloud). For the short “easy install” steps, see [CUSTOMER_INSTALL.md](CUSTOMER_INSTALL.md).

---

## What you need (overview)

| Item | Required? | Used for |
|------|-----------|----------|
| **Alpaca (paper) account** | Yes | Paper trading; you paste API key + secret in the browser wizard. |
| **Python 3.10+** | Yes | Running the bot and dashboard. |
| **Ollama** | Optional | Local AI analysis (screening, sentiment). Bot runs without it but with reduced AI features. |
| **Cloud server (e.g. Oracle)** | Optional | Running 24/7 instead of on your own computer. |

---

## 1. Alpaca setup (required)

**Fortress currently supports Alpaca only.** Other brokers (e.g. Interactive Brokers, TD Ameritrade) are not supported. See [BROKERS_AND_ALPACA.md](BROKERS_AND_ALPACA.md) for details.

1. Go to [Alpaca](https://alpaca.markets/) and sign up (free).
2. Open the **Paper Trading** dashboard: [app.alpaca.markets/paper/dashboard/overview](https://app.alpaca.markets/paper/dashboard/overview).
3. In **API Keys**, create or copy your **API Key ID** and **Secret Key**.  
   Use **paper** keys only (not live) so no real money is at risk.
4. When you run Fortress and open the setup page in your browser (Step 3 of [CUSTOMER_INSTALL.md](CUSTOMER_INSTALL.md)), you will **paste these two values** there. They are saved only on your machine; we never see them.

**Important:** Fortress is designed for **paper trading**. Keep your Alpaca base URL as the paper URL (`https://paper-api.alpaca.markets`). The setup wizard and default config use paper.

---

## 2. Ollama setup (optional but recommended)

Ollama runs a **local AI model** on your machine. The bot uses it for screening and analysis. If Ollama is not installed or not running, the bot still works but skips some AI steps.

### Install Ollama

- **Mac / Linux:**  
  In a terminal, run:
  ```bash
  curl -fsSL https://ollama.com/install.sh | sh
  ```
  Or download the installer from [ollama.com](https://ollama.com).
- **Windows:**  
  Download the installer from [ollama.com](https://ollama.com) and run it.

### Pull the model and start Ollama

- **Linux (with systemd):**
  ```bash
  sudo systemctl start ollama    # start now
  sudo systemctl enable ollama   # start on boot
  ollama pull llama3.2:1b        # small, fast model used by Fortress
  ```
- **Mac / Windows:**  
  Start the **Ollama** app from your applications. Then open a terminal (or Command Prompt) and run:
  ```bash
  ollama pull llama3.2:1b
  ```

Optional (for deeper analysis, needs more RAM):
```bash
ollama pull llama3.1:8b
```

### Check that Ollama is running

- Open **http://localhost:11434** in your browser. You should see “Ollama is running” or similar.
- The Fortress dashboard **System Health** section also shows **Ollama: Running** or **Stopped**.

---

## 3. Oracle Cloud (or any VPS) – run Fortress 24/7

If you want the bot to run **all the time** (e.g. overnight and when your PC is off), use a cloud server. You can use **Oracle Cloud Free Tier**, **DigitalOcean**, **Linode**, or any VPS that gives you Ubuntu (or similar) and SSH access.

### 3a. Oracle Cloud Free Tier (example)

1. **Create an Oracle Cloud account** (free tier): [cloud.oracle.com](https://cloud.oracle.com).
2. **Create a compute instance:**
   - Choose **Ubuntu 22** (or 24) as the image.
   - Shape: **Ampere (ARM)** or **x86**, 1 OCPU, 1 GB RAM is enough to start; 2 GB RAM is better if you run Ollama.
   - Add your SSH public key so you can log in.
3. **Connect by SSH:**  
   From your computer:
   ```bash
   ssh ubuntu@<your-instance-public-ip>
   ```
4. **On the server, install dependencies:**
   ```bash
   sudo apt update
   sudo apt install -y python3 python3-pip python3-venv
   # Optional: Ollama for AI
   curl -fsSL https://ollama.com/install.sh | sh
   sudo systemctl enable ollama
   sudo systemctl start ollama
   ollama pull llama3.2:1b
   ```
5. **Copy Fortress onto the server:**
   - From your computer (in the folder where you have Fortress):
     ```bash
     scp -r /path/to/Fortress ubuntu@<your-instance-ip>:~/
     ```
   - Or use **git** if you have a repo: `git clone <repo-url> Fortress && cd Fortress`
6. **On the server, run setup and start the dashboard:**
   ```bash
   cd ~/Fortress
   chmod +x setup.sh start_dashboard.sh
   ./setup.sh
   ./start_dashboard.sh
   ```
   To keep it running after you close SSH, use **tmux** or **screen**, or run the dashboard as a service (see below).
7. **Open the setup wizard in your browser:**  
   - If the server is on the internet: **http://&lt;your-instance-public-ip&gt;:8083**  
     (You may need to open port **8083** in the Oracle Cloud **Virtual Cloud Network** → Security List → Ingress Rules.)
   - Or use an **SSH tunnel** from your computer so you don’t expose the port:
     ```bash
     ssh -L 8083:localhost:8083 ubuntu@<your-instance-ip>
     ```
     Then on your PC open **http://localhost:8083** and complete Alpaca + setup as in [CUSTOMER_INSTALL.md](CUSTOMER_INSTALL.md).

### 3b. Run the dashboard in the background (Linux)

So the dashboard and bot keep running after you log out:

```bash
# Using nohup (simple)
cd ~/Fortress
source venv/bin/activate
nohup python3 dashboard/command_center.py > logs/dashboard.log 2>&1 &

# Or use tmux
tmux new -s fortress
cd ~/Fortress && ./start_dashboard.sh
# Detach: Ctrl+B then D. Reattach later: tmux attach -t fortress
```

### 3c. Other clouds (DigitalOcean, etc.)

Same idea: create an **Ubuntu** droplet/VM, SSH in, install Python (and optionally Ollama), copy or clone Fortress, run `./setup.sh` and then start the dashboard. Use the VM’s IP and port **8083** (and open that port in the firewall if you want to reach it from the internet), or use an SSH tunnel to **localhost:8083** for extra safety.

---

## 4. Quick reference

- **Alpaca keys:** Get from [Alpaca Paper Dashboard](https://app.alpaca.markets/paper/dashboard/overview) → paste in Fortress browser setup (Step 3 of install).
- **Ollama:** Install from [ollama.com](https://ollama.com), then `ollama pull llama3.2:1b` (and optionally `llama3.1:8b`). Bot works without it but with fewer AI features.
- **Oracle Cloud:** Create Ubuntu VM → SSH in → install Python (and optionally Ollama) → copy Fortress → run `./setup.sh` and `./start_dashboard.sh` → open http://&lt;VM-IP&gt;:8083 or use SSH tunnel to localhost:8083.

For the shortest path (no cloud, no Ollama), follow [CUSTOMER_INSTALL.md](CUSTOMER_INSTALL.md) and paste your Alpaca keys in the browser; you’re done.
