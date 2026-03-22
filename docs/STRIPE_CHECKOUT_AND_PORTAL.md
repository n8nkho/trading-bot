# Stripe Checkout & Customer Portal (C)

Your app already has a **webhook** that writes **`stripe_license.json`** (`docs/BILLING_STRIPE.md`). **Checkout** and **Customer Portal** are configured in **Stripe**; you paste the resulting URLs into **`.env`** so **Proof Center** can show them (optional).

---

## 1. Payment Links (fastest “Buy” buttons)

1. Stripe Dashboard → **Product catalog** → pick a product → **Payment links** (or **Payment Links** in left nav).
2. Create a link per tier (**Starter / Pro / Enterprise**).
3. Copy each **https://buy.stripe.com/...** (or similar) URL.

Put in **customer** `.env` (or yours for testing):

```bash
STRIPE_PAYMENT_LINK_STARTER=https://buy.stripe.com/...
STRIPE_PAYMENT_LINK_PRO=https://buy.stripe.com/...
STRIPE_PAYMENT_LINK_ENTERPRISE=https://buy.stripe.com/...
```

Restart the dashboard. Links appear on **`/proof`** under **Billing (Stripe)** when set.

**Success URL:** set Payment Link success URL to your site or `https://YOUR_HOST:8083/setup` if you want them back in the app.

---

## 2. Checkout Sessions (more control)

Use **Stripe Checkout** via Dashboard **“Create payment link”** or your own backend later. Same idea: customer completes payment → subscription exists → **webhook** updates **`FORTRESS_LICENSE_PATH`** file.

Ensure webhook events include **`customer.subscription.updated`** (see `BILLING_STRIPE.md`).

---

## 3. Customer Portal (cancel / update card)

1. Stripe → **Settings → Billing → Customer portal**.
2. Enable **subscription cancellation**, **payment method update**, etc.
3. For each customer you can send a portal session URL from Stripe or use **“Generate portal link”** in test mode.

For a **static** marketing link is limited; portal links are often **one-time** session URLs. Practical pattern:

- On your **marketing site**, add “Manage subscription” → button that hits **your** small serverless function that creates a **Billing Portal session** and redirects (future work), **or**
- Email customers portal links from Stripe **Customer** page manually at first.

Optional env (if you have a stable landing page):

```bash
STRIPE_CUSTOMER_PORTAL_URL=https://billing.stripe.com/p/login/...
```

(Some Stripe portal login links are reusable for **test**; confirm in current Stripe docs.)

---

## 4. Lane 1 (you)

Leave **`STRIPE_PAYMENT_LINK_*`** unset on Oracle if you don’t sell from the operator UI. Your tier stays **`FORTRESS_LICENSE_TIER=master`**.

---

## Related

- `docs/BILLING_STRIPE.md` — webhook + `.env` for license file  
- `/proof` — optional display of payment links from env
