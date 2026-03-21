# Stripe billing → Fortress license (Lanes 2–3)

Stripe sends webhooks to your Command Center; the app writes **`data/stripe_license.json`** (or `STRIPE_LICENSE_OUT_PATH`). **`config/license.py`** reads that file when **`FORTRESS_LICENSE_PATH`** points to it.

**Lane 1 (you):** you can leave all Stripe vars unset and keep **`FORTRESS_LICENSE_TIER=master`** on Oracle.

---

## 1. Stripe Dashboard (Test mode first)

1. Create **Products** (e.g. Starter / Pro / Enterprise) with **recurring prices**.
2. Copy each **Price ID** (`price_...`) — not the Product id.
3. **Developers → Webhooks → Add endpoint**  
   - URL: `https://YOUR_PUBLIC_HOST:8083/api/billing/stripe-webhook`  
     (use your real hostname / reverse proxy; port **8083** unless you terminate TLS on 443 and proxy.)
4. Subscribe to events (minimum):
   - `customer.subscription.created`
   - `customer.subscription.updated`
   - `customer.subscription.deleted`
   - `checkout.session.completed` (optional; see below)
5. Copy the endpoint **Signing secret** (`whsec_...`).

---

## 2. `.env` on the customer VM (or your test VM)

```bash
STRIPE_WEBHOOK_SECRET=whsec_xxxxxxxx
STRIPE_PRICE_STARTER=price_xxx
STRIPE_PRICE_PRO=price_yyy
STRIPE_PRICE_ENTERPRISE=price_zzz
STRIPE_LICENSE_OUT_PATH=data/stripe_license.json
FORTRESS_LICENSE_PATH=/home/ubuntu/trading-bot/data/stripe_license.json
```

Remove or comment **`FORTRESS_LICENSE_TIER`** when the **file** should define the plan (otherwise env tier can override missing file fields — see `config/license.py`).

**Optional:** `STRIPE_SECRET_KEY=sk_test_...` — needed if you rely on **`checkout.session.completed`** and Stripe only sends subscription as an **id** string (the handler will fetch the Subscription).

---

## 3. Install dependency

```bash
cd ~/trading-bot
source venv/bin/activate
pip install stripe==11.4.1
```

Or reinstall from `requirements.txt`.

---

## 4. Restart dashboard

```bash
sudo systemctl restart fortress-dashboard
```

---

## 5. Test (Stripe CLI)

```bash
stripe listen --forward-to localhost:8083/api/billing/stripe-webhook
stripe trigger customer.subscription.updated
```

Check **`data/stripe_license.json`** and trust ledger for `stripe_license_updated`.

---

## 6. Security notes

- The route is **public** but **Stripe signature** verification is mandatory; random callers get **400**.
- Use **HTTPS** in production (reverse proxy).
- Never commit **`STRIPE_WEBHOOK_SECRET`** or **`STRIPE_SECRET_KEY`** to git (`.env` is gitignored).

---

## Related

- `utils/stripe_license_sync.py` — mapping + file write  
- `docs/INSTALL_LOCAL.md` — customer install  
- `docs/examples/license.example.json` — manual file shape without Stripe
