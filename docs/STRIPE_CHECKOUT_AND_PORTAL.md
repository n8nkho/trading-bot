# Stripe Payment Links — step by step

Your Fortress app shows optional **Subscribe** links on **`/proof`** when you set env vars. Stripe creates the actual checkout pages. You also need a **webhook** so paid customers get a license file — see **`docs/BILLING_STRIPE.md`**.

**Use Test mode** until everything works, then repeat in **Live mode**.

---

## Part A — Products & prices (one-time per tier)

Do this for **Starter**, **Pro**, and **Enterprise** (three products, or one product with three prices — Payment Links usually attach to **one price**).

1. Log in to **[dashboard.stripe.com](https://dashboard.stripe.com)**.
2. Turn **Test mode** ON (toggle top right) while learning.
3. Left sidebar → **Product catalog** → **Add product**.
4. **Name:** e.g. `Fortress Starter`.
5. Under **Pricing**:
   - Choose **Recurring** (e.g. monthly or yearly).
   - Set **Price** (e.g. `49` USD) — match your story to `config/pricing_gates.json` if you like.
6. **Save product**.
7. On the product page, find **Pricing** and copy the **Price ID** (`price_xxxxxxxx`). You will use it in **`STRIPE_PRICE_STARTER`** (see `BILLING_STRIPE.md`).
8. Repeat for **Pro** and **Enterprise** (note each **`price_...`** for `STRIPE_PRICE_PRO`, `STRIPE_PRICE_ENTERPRISE`).

---

## Part B — Payment Link per tier (the “buy” URL)

Create **one Payment Link per price** (Starter / Pro / Enterprise).

1. Left sidebar → **Payment Links** (under **Product catalog**), or open the product → **Create payment link**.
2. **Select product** → pick **Fortress Starter** (or your name) → select the **recurring price** you created.
3. **After payment** (optional but useful):
   - Set **Confirmation page** message, or  
   - **Redirect** customers to a URL after checkout, e.g.  
     `https://YOUR_PUBLIC_HOST:8083/setup`  
     (replace with your real hostname; use **HTTPS** in production).
4. **Customer information:** turn on **Collect customers’ email addresses** (recommended so you can find them in Stripe and support them).
5. Click **Create link** (or **Save**).
6. Stripe shows the link — copy the full URL. It usually looks like  
   `https://buy.stripe.com/test_...` (test) or `https://buy.stripe.com/...` (live).
7. Repeat steps 1–6 for **Pro** and **Enterprise**.

You now have **three URLs**.

---

## Part C — Put URLs in `.env` (Oracle or customer VM)

Edit **`~/trading-bot/.env`** on the machine where the **dashboard** runs:

```bash
# Optional: show on https://YOUR_HOST:8083/proof
STRIPE_PAYMENT_LINK_STARTER=https://buy.stripe.com/test_xxxxx
STRIPE_PAYMENT_LINK_PRO=https://buy.stripe.com/test_yyyyy
STRIPE_PAYMENT_LINK_ENTERPRISE=https://buy.stripe.com/test_zzzzz
```

Use your **exact** copied links (no quotes needed unless the shell requires them).

**Restart the dashboard:**

```bash
sudo systemctl restart fortress-dashboard
```

**Check:** open **`http://YOUR_PUBLIC_IP:8083/proof`** (replace with your Oracle public IP). Use **http://** if you have no TLS yet.

**If you see “Billing (Stripe)” but “No links loaded”:**

The UI is working; the **VM’s** `~/trading-bot/.env` has **no** usable values for the four keys below (or they’re commented out). **Deploy rsync copies `.env` from your laptop** — if Stripe URLs exist only in a different file or only on the Mac *outside* the repo you deploy from, Oracle won’t get them.

On the **server**, verify (expect non-empty lines, not `#`):

```bash
grep -E '^[^#]*STRIPE_PAYMENT_LINK_|^[^#]*STRIPE_CUSTOMER_PORTAL_URL' /home/ubuntu/trading-bot/.env
```

**Don’t use** `grep buy.stripe.com` on `/proof` HTML alone — the “No links loaded” help text used to contain fake `buy.stripe.com/...` examples. Prefer:

```bash
curl -s http://127.0.0.1:8083/proof | grep -o 'href="https://buy.stripe.com/[^"]*"'
```

Or open **`/api/billing/proof_links_status`** (JSON: paths, whether `.env` is readable, how many keys the dashboard parsed — **no URLs**). This path is **public** (no Basic auth) so `curl` works; other `/api/*` routes may require **`-u USER:PASS`** if `FORTRESS_DASHBOARD_USER` / `FORTRESS_DASHBOARD_PASS` are set.

If that prints nothing, append the real URLs to **`/home/ubuntu/trading-bot/.env`**, then:

```bash
sudo systemctl restart fortress-dashboard
```

**If the “Billing” block is missing entirely:** older template — deploy latest `dashboard/templates/proof_center.html`.

**Other checks:**

1. Use exact names: `STRIPE_PAYMENT_LINK_STARTER`, `STRIPE_PAYMENT_LINK_PRO`, `STRIPE_PAYMENT_LINK_ENTERPRISE`, `STRIPE_CUSTOMER_PORTAL_URL` (not `STRIPE_PRICE_*` — those are for the webhook).
2. No spaces around `=` (e.g. `STRIPE_PAYMENT_LINK_PRO=https://...`). `export KEY=value` is OK.
3. **`sudo systemctl restart fortress-dashboard`** after editing `.env`.
4. Hard-refresh the browser (**Cmd+Shift+R** / **Ctrl+Shift+R**) on `/proof`.
5. Confirm systemd unit loads env: **`grep EnvironmentFile /etc/systemd/system/fortress-dashboard.service`** — should show `EnvironmentFile=-/home/ubuntu/trading-bot/.env` (or similar). If missing, reinstall from `deploy/systemd/` template or add that line and `sudo systemctl daemon-reload`.

6. **`python3 -c "load_dotenv…"` prints the URL but /proof doesn’t?** Deploy the latest `command_center.py` (reads those keys from the file with UTF-8 BOM + `export` support) and restart the service.

**Lane 1 (your operator Oracle):** you can leave these **unset** if you don’t want subscribe links on your personal server.

---

## Part D — Webhook + license file (required for access control)

Payment Links alone **do not** update Fortress tiers until Stripe hits your webhook.

1. Follow **`docs/BILLING_STRIPE.md`**: add endpoint  
   `https://YOUR_PUBLIC_HOST:8083/api/billing/stripe-webhook`  
   and set **`STRIPE_WEBHOOK_SECRET`**, **`STRIPE_PRICE_*`**, **`FORTRESS_LICENSE_PATH`**, etc.
2. After a **test** subscription checkout, confirm **`data/stripe_license.json`** (or your `STRIPE_LICENSE_OUT_PATH`) updates and **`get_plan()`** reflects **pro/starter/enterprise**.

---

## Part E — Customer Portal (manage card / cancel)

1. Stripe Dashboard → **Settings** (gear) → **Billing** → **Customer portal**.
2. Turn the portal **on** and choose what customers can do (e.g. **cancel subscription**, **update payment method**).
3. **Save**.

**Getting a link for one customer (manual, fine for early days):**

- **Customers** → click customer → look for **Portal** or **Create portal link** (wording varies).  
  Many flows generate a **one-time** URL — send that in email.

**Static “Manage billing” URL:** Stripe sometimes offers a **login**-style portal link for your account branding; it changes by product. If you find a stable HTTPS URL in the portal settings, you can try:

```bash
STRIPE_CUSTOMER_PORTAL_URL=https://billing.stripe.com/...
```

If it doesn’t work or expires, leave it unset and use per-customer links from the Dashboard.

Long-term, many apps add a small backend route that calls Stripe’s API to create a **Billing Portal session** and redirects — not required for your first sales.

---

## Part F — Go live

1. Switch Stripe to **Live mode**.
2. Recreate **products**, **prices**, **payment links** in live (test objects don’t carry over).
3. Create a **live** webhook endpoint with a **live** signing secret `whsec_...`.
4. Update **`.env`** on the **production** server with **live** links and secrets.
5. Restart **`fortress-dashboard`**.

---

## Quick checklist

| Step | Done? |
|------|--------|
| Test products + recurring prices | ☐ |
| Three Payment Links copied | ☐ |
| `STRIPE_PAYMENT_LINK_*` in `.env` | ☐ |
| `sudo systemctl restart fortress-dashboard` | ☐ |
| `/proof` shows Billing section | ☐ |
| Webhook + `STRIPE_WEBHOOK_SECRET` + `STRIPE_PRICE_*` + `FORTRESS_LICENSE_PATH` | ☐ |
| Test checkout → `stripe_license.json` updates | ☐ |
| Customer portal configured in Stripe | ☐ |

---

## Related

- `docs/BILLING_STRIPE.md` — webhook, license file, tier mapping  
- `docs/LANE1_HARDENING_AND_ROUTINE.md` — deploy + restart  
- `.env.example` — all `STRIPE_*` variable names  
