# TradingView → Fortress webhook setup

**Print to PDF:** open this file in Chrome / Edge / VS Code preview → **Print** → **Save as PDF**.

Fortress does **not** auto-trade from TradingView. Alerts are **logged** to `data/tradingview_signal_queue.jsonl` and shown in **Command Center → TradingView signal queue** for **human review** and optional downstream automation you build.

---

## Step-by-step: set `FORTRESS_TV_WEBHOOK_SECRET` on the server

These steps match a typical **Ubuntu** box with Fortress in **`/home/ubuntu/trading-bot`** and **`fortress-dashboard`** on port **8083**. Change paths/host if yours differ.

### 1) Generate a secret (Mac or server)

On your **Mac** or **server**:

```bash
openssl rand -hex 32
```

Copy the output (example: `a1b2c3d4...` — **64 hex chars**). That value is **`YOUR_SECRET`** below. **Do not share it** publicly.

---

### 2) SSH into the server

```bash
ssh ubuntu@YOUR_PUBLIC_IP
```

(`YOUR_PUBLIC_IP` = the IP you use for the dashboard, e.g. Oracle instance public IP.)

---

### 3) Open the project `.env`

```bash
cd /home/ubuntu/trading-bot
nano .env
```

(If `.env` does not exist, create it: `nano .env`.)

---

### 4) Add the variable (one line, no spaces around `=`)

Add **exactly** (paste your own hex, not this example):

```bash
FORTRESS_TV_WEBHOOK_SECRET=a1b2c3d4e5f6789...
```

- **Do not** wrap the value in quotes unless your secret itself must contain spaces (it shouldn’t).
- Save in nano: **Ctrl+O**, **Enter**, **Ctrl+X**.

---

### 5) Restart the dashboard service

So the process reloads `.env`:

```bash
sudo systemctl restart fortress-dashboard
sudo systemctl status fortress-dashboard
```

You want **`active (running)`**. If the unit loads env via `EnvironmentFile=` pointing at `.env`, this is enough. If your service embeds env elsewhere, update that file the same way and restart.

---

### 6) Test the hook **on the server** (GET ping)

Use the **same** secret string you put in `.env`:

```bash
curl -s "http://127.0.0.1:8083/api/hooks/tradingview?secret=PASTE_YOUR_SECRET_HERE"
```

You should see JSON like: `"ok": true`, `"message": "POST alert payloads here..."`.

**Wrong secret** → `"ok": false`, `"error": "forbidden"`.

---

### 7) Test from the **internet** (optional but recommended)

From your **Mac**:

```bash
curl -s "http://YOUR_PUBLIC_IP:8083/api/hooks/tradingview?secret=PASTE_YOUR_SECRET_HERE"
```

- If this **times out** or **connection refused**, open **TCP port 8083** in your cloud **security list / firewall** (e.g. Oracle VCN ingress rule: source `0.0.0.0/0` or your IP → destination port **8083**).
- If you terminate **HTTPS** on a reverse proxy, use **`https://your-domain/...`** and the path **`/api/hooks/tradingview`** (secret still in query string unless you configure a header at the proxy).

---

### 8) Build the URL for TradingView

TradingView’s servers will **only** call webhook URLs on **port 80** or **port 443**.  
A URL like `http://YOUR_IP:8083/...` is **rejected** by TradingView (see [their webhook doc](https://www.tradingview.com/support/solutions/43000529348-how-to-configure-webhook-alerts/)).

**You need one of:**

| Approach | Webhook URL example |
|----------|---------------------|
| **HTTPS reverse proxy** (recommended) | `https://hooks.yourdomain.com/api/hooks/tradingview?secret=...` → nginx/Caddy forwards to `127.0.0.1:8083` |
| **HTTP on port 80** | `http://YOUR_PUBLIC_IP/api/hooks/tradingview?secret=...` only if Fortress (or a proxy) listens on **80** |

**Minimal nginx (443 → 8083)** — install TLS (e.g. Let’s Encrypt) for your hostname, then:

```nginx
location /api/hooks/tradingview {
    proxy_pass http://127.0.0.1:8083;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

Use **`https://YOUR_DOMAIN/api/hooks/tradingview?secret=PASTE_YOUR_SECRET_HERE`** in TradingView (same secret as `.env`).

For **testing only** (not TradingView), you can still use **`http://127.0.0.1:8083`** with `curl` on the server.

---

## No paid TradingView plan?

**TradingView → external webhook** is a **TradingView product feature**: on **free** accounts you typically **do not** get a **Webhook URL** field in alerts. That is **their** paywall, not Fortress’s. You do **not** need to pay Fortress extra for the hook — but **TradingView** may require **Essential / Plus / Premium** (or trial) for webhooks. Confirm on [TradingView pricing](https://www.tradingview.com/pricing/) and [webhook help](https://www.tradingview.com/support/solutions/43000529348-how-to-configure-webhook-alerts/).

### What you can do **without** paying TradingView

| Approach | Cost | Notes |
|----------|------|--------|
| **Use Fortress only for signals** | $0 to TV | Cron + **screener / orchestrator**, **Morning Brief**, **Command Center** — your main automation path. |
| **Use TradingView free for charts only** | $0 | Research and manual decisions; no automatic POST to Fortress from TV. |
| **Test the Fortress webhook yourself** | $0 | `curl` POST to `/api/hooks/tradingview` (see below) — proves queue + UI without TV. |
| **DIY bridge (email → script)** | $0–? | TV free alerts can often **email** you; you *could* parse email and POST to Fortress — fragile, not documented here; only if you enjoy ops glue. |

**Bottom line:** the **TradingView signal queue** panel in Fortress stays useful when you feed it via **`curl`**, another app, or **later** if you add a paid TV plan or a different signal source. Nothing in Fortress **requires** you to subscribe to TradingView.

---

## Step-by-step: TradingView alert (logged in on tradingview.com)

TradingView changes labels occasionally; if something doesn’t match exactly, use the same ideas in **Supercharts** / **Chart** view.

### Before you start (TradingView account)

1. **2-factor authentication (2FA)** must be **on** for your TradingView account, or webhooks are blocked.  
   - Profile / account settings → security → enable **2FA** (see [TradingView 2FA help](https://www.tradingview.com/support/solutions/43000572460-how-to-configure-2fa/)).
2. **Paid TradingView plan:** **Webhook URL** is **not** available on the **free** tier for most users. If you **don’t** see **Webhook URL**, you **cannot** complete the steps below until you upgrade **or** use a **trial** — see **[No paid TradingView plan?](#no-paid-tradingview-plan)** above.
3. You must use a URL on **port 443 (https)** or **port 80 (http)** — see **§8** above. **`:8083` in the URL will not work** from TradingView.

---

### G1 — Open a chart

1. Go to **https://www.tradingview.com** and sign in.
2. Use the **search** at top: type a symbol (e.g. `AAPL`) and press **Enter** (or pick from list).  
3. You should see the **price chart** for that symbol (candles / line). Stay on this page.

---

### G2 — Open the “Create alert” dialog

Try **one** of these (whatever appears on your screen):

- **Top toolbar:** look for **“Alert”** or a **bell / alarm** icon → click **“Create alert”** or **“+”** next to Alerts.  
- **Right-click** on the chart (on the price area) → **“Add alert…”** (or similar).  
- **Keyboard:** some layouts use **Alt + A** (try if shortcuts are enabled).

A **modal window** (alert editor) should open.

---

### G3 — Set the **condition** (when the alert fires)

In the alert dialog, the **first** area is usually the **trigger condition**. Examples:

- **Price crosses a level:** e.g. “AAPL **crosses above**” → type a price **slightly above** the current price so it can fire when the market moves up (or use a level you care about).  
- **Crossing a moving average:** condition like “**Close** crosses **above** **MA** …”.  
- **Indicator:** e.g. RSI, MACD — pick from the condition dropdowns.

For a **quick test**, pick something that can realistically happen soon (e.g. “price crosses above” a level just above last close on a liquid stock during market hours), or use a **very easy** condition on a demo if you use paper mode.

**Options:**

- **Once per bar close** vs **once** — use what you need; for testing, “every time” can spam—prefer **once** or bar close for sanity.

---

### G4 — Set the **message** (body Fortress receives)

Find the **“Message”** box (same dialog, sometimes below the condition, or under **“Message”** / **“Notification message”**).

**JSON example** (numbers must **not** be in quotes — use `{{close}}` without quotes around it):

```text
{"ticker":"{{ticker}}","close":{{close}},"time":"{{timenow}}"}
```

**Plain text example:**

```text
{{ticker}} @ {{close}} — alert fired
```

If the message is **valid JSON**, TradingView sends **`Content-Type: application/json`** (Fortress parses it). Otherwise it’s **plain text** (still stored in the queue).

Placeholders: see TradingView’s docs for **`{{ticker}}`**, **`{{close}}`**, **`{{timenow}}`**, etc.

---

### G5 — Enable **Webhook URL**

1. In the **same** alert dialog, find the **“Notifications”** tab **or** a section titled **Notifications** / **Alert actions** (scroll down if needed).
2. Find **“Webhook URL”**.
3. **Turn on** the toggle / check the box for **Webhook URL**.
4. In the URL field, paste **one continuous line** (no line breaks), for example:

   ```text
   https://hooks.yourdomain.com/api/hooks/tradingview?secret=PASTE_YOUR_SECRET_HERE
   ```

   Use the **exact** same `secret=` value as **`FORTRESS_TV_WEBHOOK_SECRET`** in your server `.env`.

5. Optional: leave **“Show pop-up”** / **email** on or off — they don’t affect the webhook.

---

### G6 — Name, expiration, and **Create**

1. Optionally set an **alert name** (helps you find it later in the list).
2. Set **expiration** (e.g. 1 month) if offered.
3. Click **“Create”** / **“Save”** to save the alert.

---

### G7 — Confirm it appears in the **alerts list**

1. Open the **alerts manager** (often a **bell** icon or **“Alerts”** list on the right / bottom panel — depends on layout).
2. You should see your new alert **enabled** (green / active).

---

### G8 — Fire the alert and verify Fortress

1. **Wait** until the market condition is true, **or** temporarily edit the alert to a condition that triggers soon (then change it back).  
2. In TradingView’s alert log / list, some UIs show **“Webhook status”** for delivery — use that if a POST fails (timeout, wrong URL, etc.).  
3. On Fortress: open **Command Center** in the browser → scroll to **“TRADINGVIEW SIGNAL QUEUE”** → you should see a new line with your JSON or text.  
4. On the server, **`data/tradingview_signal_queue.jsonl`** should gain one more line per successful POST.

**TradingView limits:** response must be handled within **~3 seconds**; they publish **IP ranges** to allowlist if you use a firewall — see [TradingView webhook article](https://www.tradingview.com/support/solutions/43000529348-how-to-configure-webhook-alerts/).

---

**POST test from your Mac** (Fortress on 8083 — OK for **curl**, not for TradingView):

```bash
curl -s -X POST "http://YOUR_PUBLIC_IP:8083/api/hooks/tradingview?secret=PASTE_YOUR_SECRET_HERE" \
  -H "Content-Type: text/plain" \
  -d "TEST from curl"
```

---

## 1. Prerequisites

- Command Center reachable from the internet **or** use a tunnel (ngrok, etc.) if TradingView must reach your laptop.
- Set a **shared secret** (strongly recommended):

```bash
# In .env on the server
FORTRESS_TV_WEBHOOK_SECRET=your-long-random-string
```

Restart `fortress-dashboard` after changing `.env`.

---

## 2. Webhook URL

Use **POST** (TradingView “Webhook URL”).

**Pattern (TradingView must use port 80 or 443 only):**

```text
https://YOUR_PUBLIC_HOST/api/hooks/tradingview?secret=your-long-random-string
```

(`YOUR_PUBLIC_HOST` = domain or IP **without** `:8083` — put nginx/Caddy on **443** and proxy to `127.0.0.1:8083`.)

If you prefer a header instead of query string, omit `?secret=` and configure a custom header in your proxy, **or** use TradingView’s URL field with query param only (simplest).

**Alternate header (for scripts):**

```http
X-Fortress-Webhook-Secret: your-long-random-string
```

If `FORTRESS_TV_WEBHOOK_SECRET` is **unset**, the hook accepts any caller (**not recommended** on public IPs).

**Dashboard Basic auth:** `/api/hooks/tradingview` is **exempt** so TradingView does not need your dashboard password.

---

## 3. TradingView alert configuration

1. Open your chart → **Alerts** → create or edit an alert.
2. **Webhook URL:** paste the URL from §2.
3. **Message** — choose one:

**Plain text (simple):**

```text
{{ticker}} long @ {{close}}
```

**JSON (recommended for parsing):**

```text
{"ticker":"{{ticker}}","action":"long","price":{{close}},"time":"{{timenow}}"}
```

Use TradingView’s placeholders (`{{ticker}}`, `{{close}}`, etc.) per their docs.

4. Save. Use **Test** / fire the alert once and check the dashboard queue.

---

## 4. Verify

**Browser / curl (GET ping):**

```bash
curl -s "https://YOUR_HOST:8083/api/hooks/tradingview?secret=YOUR_SECRET"
```

Expect JSON `ok: true`.

**POST sample:**

```bash
curl -s -X POST "http://127.0.0.1:8083/api/hooks/tradingview?secret=YOUR_SECRET" \
  -H "Content-Type: application/json" \
  -d '{"ticker":"MSFT","note":"test"}'
```

**UI:** Command Center → **TradingView signal queue** should show newest lines first.

**Disk:** `data/tradingview_signal_queue.jsonl` (append-only JSON lines).

**Trust ledger:** event type `tradingview_webhook_received` (best-effort).

---

## 5. Policy template for signal sleeves

Optional risk profile for smaller sleeves when acting on external signals:

```bash
python3 scripts/install_policy_template.py tv_signal_sleeve
# optional: make it active
python3 scripts/install_policy_template.py tv_signal_sleeve --activate
```

Other templates: `operator_conservative`, `operator_balanced_kit` — see `config/policy_templates/README.md`.

---

## 6. Compliance & safety

- This feature is **software / logging only** — not investment advice.
- **You** decide whether and how to trade; use **pre-trade gate**, **halt**, and **paper** as appropriate.
- Rotate `FORTRESS_TV_WEBHOOK_SECRET` if it leaks; consider IP allowlisting via reverse proxy for extra control.

---

## 7. Troubleshooting

| Symptom | Check |
|--------|--------|
| 403 from hook | `secret` query or header matches `FORTRESS_TV_WEBHOOK_SECRET` |
| 401 from other APIs | Normal if dashboard Basic auth is on — hook URL is still public |
| Empty queue | Alert not firing, wrong URL/port, firewall, or JSON typo in TV message |
| No row in UI | `GET /api/tradingview_signals` from same host; browser console for fetch errors |

---

*Fortress — you own the stack, you own the risk.*
