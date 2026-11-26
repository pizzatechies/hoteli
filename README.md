<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="static/brand/hoteli-logo-tagline-light.svg">
    <img src="static/brand/hoteli-logo-tagline.svg" alt="Hoteli – hotel management system" height="72">
  </picture>
</p>

# Hoteli – Hotel Management System with M-Pesa

A complete hotel management system for Kenyan hotels, built with Django. It covers the staff back office (front desk, billing, housekeeping, restaurant POS, reports) and a public hotel website where guests book and pay a deposit with an **M-Pesa STK push** (Lipa Na M-Pesa Online).

![Python](https://img.shields.io/badge/python-3.12%2B-blue) ![Django](https://img.shields.io/badge/django-5.2%20LTS-green)

## Live demo

| | |
| --- | --- |
| 🌐 **Hotel website (static preview)** | https://pizzatechies.github.io/hoteli/ |
| 🧭 **Demo guide, every screen** | https://pizzatechies.github.io/hoteli/demo/ |
| ▶️ **Full working demo** | [![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://codespaces.new/pizzatechies/hoteli?quickstart=1) |

- **GitHub Pages preview:** the real app rendered with demo data. You can browse the website and every staff screen. Saving, booking and paying are switched off, because Pages can't run a server; those buttons explain this instead. It is rebuilt automatically on every push and once a week.
- **Codespaces live demo:** starts the complete system on GitHub in about two minutes. Bookings, check-in and check-out, the POS and M-Pesa all work, with M-Pesa in simulation mode. Log in with `admin`, `manager`, `reception`, `accounts`, `housekeeping` or `restaurant`; the password is `demo12345`. You need a free GitHub account, and usage counts against that account's free Codespaces hours.

> **One-time setup for the Pages site:** in the repository, open **Settings → Pages → Build and deployment → Source** and choose **GitHub Actions**. Then re-run the *Deploy demo to GitHub Pages* workflow from the **Actions** tab. To serve the demo from a custom domain, set the repository variable `PAGES_BASE_PATH` to `/`.

## Features

**Front office**
- Front desk board: today's arrivals, departures, overdue departures, in-house guests and balances
- Room calendar (tape chart): click an empty cell to book that room and date. Rooms blocked by Booking.com, Airbnb or the owner show in grey.
- Reservations with live room availability, guest look-up, seasonal rates, rate overrides and booking sources (walk-in, phone, OTA, corporate…)
- Double-booking protection with row locks. Back-to-back stays are allowed.
- Check-in rules: ID/passport required, blacklisted guests blocked, dirty or out-of-order rooms blocked (manager override), late arrivals handled
- Check-out posts any un-posted nights, handles early and late departures and blocks unpaid balances (manager override). The room goes to housekeeping automatically.
- Room moves and stay extensions for in-house guests; cancellations with optional fee; no-shows
- Guest profiles with stay history, VIP and blacklist flags, and a printable statutory guest register

**Billing**
- Guest folio: room nights, food, laundry, minibar and other charges; discounts; voids with an audit trail
- Payments by cash, M-Pesa, card, bank or cheque, plus refunds, receipts and a printable invoice with a VAT 16% and catering levy 2% breakdown
- Promo codes (percentage or fixed amount, dates, minimum nights, usage limits), long-stay discounts (e.g. 10% off 7+ nights) and corporate rates for companies. The guest always gets the single best discount, and it is shown on the booking and invoice.
- Night audit posts nightly room charges, marks no-shows, releases expired online holds and extends overstays

**M-Pesa (Safaricom Daraja)**
- STK push from a booking folio or POS order. The guest gets a PIN prompt and the payment posts itself.
- A live status widget that polls until the payment succeeds, is cancelled, times out or fails, with a clear reason for each result (wrong PIN, insufficient funds and so on)
- If the callback never arrives, the system falls back to Daraja's STK query API. A late success callback is still honoured after a timeout.
- Duplicate callbacks are ignored, and the same M-Pesa receipt can never be recorded twice
- **Refunds straight to the guest's phone** (B2C) from the folio, limited to what the guest actually paid, with a refunds screen and the result posted to the folio automatically
- Paybill (C2B) payments are matched automatically when the guest enters the booking reference as the account number. Unmatched payments wait in a queue for manual allocation.
- A raw log of every callback for reconciliation, and a resend cooldown with per-phone throttling
- A **simulation mode** that demos the whole flow without credentials

**Operations**
- Housekeeping board, cleaning tasks (created automatically at check-out, urgent if an arrival is due) and room status updates
- Maintenance requests that can take a room out of order and warn about affected bookings
- Restaurant and bar POS: menu, orders, charge to room (split into food and beverage) or pay by cash, card or M-Pesa; printable bills
- Stock: drinks, food and supplies with reorder levels. Linking a menu item to a stock item deducts it when the order is paid or charged to a room, and puts it back if the order is cancelled. Receive deliveries (optionally recorded as an expense), count stock and see every movement.
- **Channel sync** with Booking.com, Airbnb, Expedia and any site that uses iCal calendars: their reservations block our rooms, and our bookings block theirs. Syncs every 30 minutes, warns about double bookings, and lets you block dates manually for owner stays.
- Text messages (Africa's Talking): booking confirmation, payment receipt and check-in welcome, each switchable, with automatic retries and a log of every message
- Staff app: install the staff area on a phone's home screen (Add to Home Screen), with an offline page when the connection drops

**Management**
- Dashboard with occupancy, collections, a 14-day revenue chart, an occupancy forecast and double-booking warnings
- Expenses by category and supplier, and a profit & loss statement (revenue by category against expenses) for any period
- A daily summary email each morning: yesterday's occupancy, revenue, collections, expenses, today's arrivals and departures, low stock and unread messages
- Guest feedback: after check-out the guest gets a link to rate their stay. Managers read every response and choose which to publish on the website as reviews.
- Reports: occupancy, ADR, RevPAR, revenue by category, collections by method, receivables, guest credits and M-Pesa totals, with CSV export
- Staff accounts with roles: Admin, Manager, Front Desk, Accountant, Housekeeping, Restaurant
- Audit log of every important action, and hotel settings (taxes, deposit %, hold time, policies)

**Security**
- Two-step login with an authenticator app (Google Authenticator, Microsoft Authenticator, Authy) and one-time recovery codes. Managers can make it compulsory for managers and administrators.
- Accounts lock for 15 minutes after 5 wrong passwords, and staff are signed out after 4 hours without activity
- Role-based access, CSRF protection, HTTPS redirect and secure, http-only cookies in production (turn on HSTS with `SECURE_HSTS_SECONDS` once your domain is final)

**Public website**
- Home, rooms and room details, dining menu (from the POS), facilities, and a contact form that feeds a staff inbox
- Availability search with seasonal pricing, then guest details, then an M-Pesa deposit, then instant confirmation by email
- "Manage my booking" look-up (reference plus phone or email), where guests can view the booking and pay the balance
- WhatsApp button, mobile friendly

**Hotel name & logos** (Staff → Hotel name & logos, for managers)
- Rename the hotel and change its tagline. The new name appears straight away on the website, browser tabs, staff area, login screen, confirmation emails (subject and sender name), invoices, receipts and POS bills. Every rename is recorded in the audit log.
- Optional registered business name (e.g. *Naivasha Hospitality Ltd*) printed on invoices and receipts
- Upload a main logo, a light logo for dark backgrounds, and a favicon (PNG, JPG, WebP, GIF, SVG or ICO)
- The logos appear in the website header and footer, the staff sidebar, the login screen, invoices, receipts and POS bills
- Option to hide the hotel name next to the logo when the logo already includes it
- Files are stored in the database, so they survive redeploys on hosts without persistent disks (Render, Railway, Heroku)
- Files are checked by content, not by name. SVGs are served in a sandbox so they can't run scripts.

**Website builder** (Staff → Website builder, for managers)
- Build pages from ready-made sections: hero banner with booking search, text, image and text, rooms and rates, facilities, menu highlights, photo gallery, icon features, guest reviews, FAQ, call to action, map and contact form
- Start a page from a template (Homepage, About us, Events & conferences, Contact & location) or from a blank page
- Add, edit, reorder, duplicate, hide and delete sections, with a live preview next to the editor
- Draft and publish, preview drafts privately, and choose which pages appear in the menu and in what order
- Use any builder page as the **homepage**. If none is set, the built-in homepage is used.
- Theme: primary, accent and dark colours, heading font and footer text, applied across the whole website
- Safe by design: text is escaped, links are restricted to http(s), relative, mailto and tel, colours are validated, and map embeds must come from Google Maps

## Quick start

```bash
python3 -m venv .venv
```

```bash
source .venv/bin/activate
```

```bash
pip install -r requirements.txt
```

```bash
cp .env.example .env
```

```bash
python manage.py migrate
```

```bash
python manage.py seed_demo
```

```bash
python manage.py runserver
```

- Website: http://localhost:8000/ (the demo homepage and *Events* page are built with the website builder)
- Staff area: http://localhost:8000/staff/

`seed_demo` creates these logins, all with the password `demo12345`: `admin`, `manager`, `reception`, `accounts`, `housekeeping` and `restaurant`. **Change or delete them before going live.**

With no Daraja keys in `.env`, M-Pesa runs in **simulation mode**. The payment widget then shows buttons to simulate the customer paying, cancelling, entering a wrong PIN and so on. No real money moves.

## M-Pesa setup

### 1. Sandbox (testing with Safaricom)

1. Create an app at <https://developer.safaricom.co.ke> with *Lipa Na M-Pesa Sandbox* enabled, and copy its **Consumer Key** and **Consumer Secret**.
2. Safaricom must reach your callback over **public HTTPS**. Locally, use a tunnel such as `ngrok http 8000` and add the ngrok host to `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS`.
3. In `.env`:

   ```ini
   MPESA_ENVIRONMENT=sandbox
   MPESA_CONSUMER_KEY=...
   MPESA_CONSUMER_SECRET=...
   MPESA_SHORTCODE=174379
   MPESA_PASSKEY=bfb279f9aa9bdbcf158e97dd71a467cd2e0c893059b10f78e6b72ada1ed2c919
   MPESA_CALLBACK_BASE_URL=https://<your-tunnel>.ngrok-free.app
   MPESA_CALLBACK_TOKEN=<long random string>
   ```

4. Check your credentials:

   ```bash
   python manage.py mpesa_test
   ```

5. Open a booking, choose **Send M-Pesa prompt** and enter your own Safaricom number. Sandbox prompts go to real phones, but no money is taken.

### 2. Paybill payments (C2B), optional

Guests can also pay manually: *Lipa na M-Pesa → Paybill → your number → Account no. = booking reference*. To have these payments matched automatically, register your URLs once:

```bash
python manage.py mpesa_register_c2b
```

To test in the sandbox:

```bash
python manage.py mpesa_simulate_c2b HBXXXXXX 100
```

Payments with an unknown account number appear under **M-Pesa → Paybill (C2B)**, where you can allocate them.

### 3. Refunds to the guest's phone (B2C), optional

Refunds are sent with Daraja's B2C API. In simulation mode refunds are simulated. With real keys but no B2C settings, the **Send refund to M-Pesa** option stays hidden and refunds are recorded by hand as before.

1. In the Daraja portal, add the B2C product to your app and note the initiator name (`testapi` in the sandbox).
2. Generate the **security credential** in the portal (it encrypts the initiator password with Safaricom's certificate).
3. Set `MPESA_B2C_INITIATOR_NAME` and `MPESA_B2C_SECURITY_CREDENTIAL`, and `MPESA_B2C_SHORTCODE` if refunds go out from a different shortcode than payments come in.

A refund can never exceed what the guest paid on that booking, less earlier refunds. Results arrive by callback and post to the folio automatically; **M-Pesa → Refunds** lists every request with its status. In production, Safaricom must enable B2C on the shortcode, and its utility account must hold enough money for the refund.

### 4. Going live

1. Complete Safaricom's *Go Live* process for your Paybill or Till to get production keys and the **production passkey**.
2. Set `MPESA_ENVIRONMENT=production` and your real `MPESA_SHORTCODE`, `MPESA_PASSKEY`, `MPESA_CONSUMER_KEY` and `MPESA_CONSUMER_SECRET`.
3. **Till numbers (Buy Goods):** set `MPESA_TRANSACTION_TYPE=CustomerBuyGoodsOnline`. Set `MPESA_SHORTCODE` to the store or head-office number and `MPESA_TILL_NUMBER` to the till.
4. Set `MPESA_CALLBACK_BASE_URL` to your HTTPS domain and use a long random `MPESA_CALLBACK_TOKEN`. **Settings → M-Pesa** shows the exact URLs and warns about common mistakes.
5. If you use Paybill payments, run `mpesa_register_c2b` again against production.
6. For refunds, use your production initiator name and security credential.

> ⚠️ While simulation mode is on, anyone can "pay" with the simulate buttons. Never run a real hotel in simulation mode. Setting the consumer key and secret turns it off; you can also force it off with `MPESA_SIMULATE=False`.

### Things this handles for you

| Situation | Behaviour |
| --- | --- |
| Phone typed as `0712…`, `712…`, `+254 712…` or `0110…` | Normalised to `2547…` / `2541…`. Invalid numbers are rejected before anything is sent to Safaricom. |
| Amount has cents | Rounded up to whole shillings (M-Pesa rejects decimals). The limit is KES 250,000 per transaction. |
| Callback URL contains "mpesa" or "safaricom" | Daraja rejects such URLs, so callbacks live under `/payments/callbacks/…` |
| Callback never arrives (firewall, downtime) | After 20 seconds the widget asks Daraja's STK query API. Run `mpesa_check_pending` from cron as well. |
| Query confirms payment but has no receipt number | The payment is recorded as `STK-…`, and the receipt is filled in when the callback arrives |
| Callback arrives after we gave up (timeout) | The success is still applied: the money is real |
| Duplicate callbacks or retries | Processed once, enforced with row locks and unique keys |
| Staff keys in an M-Pesa code that already arrived via Paybill | Linked to that Paybill entry instead of being duplicated |
| Online hold expires while the guest is entering their PIN | The hold is extended. If payment arrives after the hold expired, the booking is reinstated, or flagged for a refund if the room is gone. |
| Result codes 1032 / 1037 / 1 / 2001 / 1001 | Shown as plain messages (cancelled, phone unreachable, insufficient funds, wrong PIN, another transaction in progress) |

## Scheduled jobs

One background worker runs every scheduled job. On AWS and in docker compose it runs automatically as the `jobs` container:

```bash
python manage.py run_jobs
```

| Job | When | What it does |
| --- | --- | --- |
| Night audit | Daily at `NIGHT_AUDIT_TIME` (default 23:30) | Posts room charges, marks no-shows and extends overstays |
| Expire holds | Every 5 minutes | Releases unpaid online bookings |
| M-Pesa check | Every 2 minutes | Resolves STK pushes whose callback was missed |
| SMS retry | Every 2 minutes | Resends text messages that failed because of a network or provider error |
| Calendar sync | Every 30 minutes | Imports reservations from Booking.com, Airbnb and other connected calendars |
| Daily report | Daily at `DAILY_REPORT_TIME` (default 07:00) | Emails yesterday's summary to the addresses in Hotel settings |

Every job is safe to run twice, and daily jobs are recorded so they run once a day even with several workers. The system also does these tasks on demand when people use it, and managers can run the night audit from the dashboard.

## Hosting on AWS

`deploy/aws/` contains everything needed for a production setup that GitHub Actions deploys automatically on every push:

```
CloudFront (free HTTPS, *.cloudfront.net or your domain)
   └─ Application Load Balancer (only accepts traffic from CloudFront)
        └─ ECS Fargate task: web container + background-jobs container
             └─ RDS PostgreSQL 18 (private subnets, encrypted, daily backups for 7 days)
Secrets Manager: Django key, admin password, database password, M-Pesa/email/SMS keys
CloudWatch Logs: 30 days
```

**Cost:** roughly **US$55–70 a month** at the defaults. That covers one 0.5 vCPU / 1 GB container (about $18), the load balancer (about $20), a db.t4g.micro database with 20 GB (about $15), public IPv4 addresses (about $11), plus small amounts for CloudFront, Secrets Manager and logs. There's no NAT gateway, to keep the bill down. For a budget option, see *Single server* below.

### One-time setup (about 10 minutes, then fully automatic)

1. **Choose a region.** `eu-west-1` (Ireland) is the default. `af-south-1` (Cape Town) is closer to Kenya but must first be enabled under *Account → AWS Regions*.
2. **Create the setup stack.** In the AWS Console go to **CloudFormation → Create stack → With new resources**, upload `deploy/aws/bootstrap.yml` and name the stack `hoteli-bootstrap`. Keep the defaults, unless your account already has the GitHub identity provider; if so, set *CreateGitHubOIDCProvider* to `false`. Tick the IAM acknowledgement and create the stack. This makes a deploy role for GitHub, with no stored keys, and an image registry.
3. **Connect GitHub.** In the repository, open **Settings → Secrets and variables → Actions → Variables** and add:
   - `AWS_DEPLOY_ROLE_ARN`: the *DeployRoleArn* output of the setup stack.
   - `AWS_REGION`: the region you chose.
4. **Deploy.** Open **Actions → Deploy to AWS → Run workflow**. The first run takes 20–30 minutes, because the database and CloudFront are being created. Later pushes deploy in about 5 minutes. The run summary lists your website and staff addresses.
5. **Sign in.** Use username `admin`. The password is in Secrets Manager under `hoteli/prod/admin-password`; the run summary links to it. Change it after your first login.
6. **Add your keys.** In Secrets Manager, edit `hoteli/prod/integrations` and fill in your M-Pesa (Daraja), email (SMTP) and SMS keys. Then run the workflow again with **Only restart the app** ticked. M-Pesa stays in simulation mode until real keys are added.

**Optional repository variables:** `HOTELI_CUSTOM_DOMAIN` + `HOTELI_CERTIFICATE_ARN` (an ACM certificate in us-east-1; point the domain's CNAME at the *CloudFrontDomain* output), `MPESA_ENVIRONMENT` (`production` when going live), `MPESA_SHORTCODE`, `MPESA_TRANSACTION_TYPE`, `MPESA_TILL_NUMBER`, `MPESA_B2C_SHORTCODE` (for refunds), `EMAIL_HOST` (e.g. `email-smtp.eu-west-1.amazonaws.com` for Amazon SES), `DEFAULT_FROM_EMAIL`, `SMS_BACKEND` (`africastalking`), `SMS_USERNAME`, `SMS_SENDER_ID`, `HOTELI_DESIRED_COUNT`.

**Safety built in:** the database has deletion protection and takes a final snapshot if it is ever removed. Deploys roll back automatically if the new version fails its health checks. Containers can't be reached except through CloudFront.

### Single server (budget, about US$10–20 a month)

On one AWS Lightsail or EC2 instance with Docker installed and a domain pointing at it:

```bash
git clone https://github.com/pizzatechies/hoteli.git && cd hoteli
```

```bash
cp .env.example .env
```

Edit `.env` and set at least `DEBUG=False`, `SECRET_KEY`, `DOMAIN`, `DB_PASSWORD`, `DJANGO_ADMIN_USERNAME` and `DJANGO_ADMIN_PASSWORD`. Then start everything:

```bash
docker compose up -d --build
```

This runs the app, the background jobs, PostgreSQL, Caddy (which gets a free HTTPS certificate automatically) and a daily database backup into `./backups` that keeps 14 days.

### Other hosts

**Render:** create a *Blueprint* from `render.yaml`. **Railway / Heroku-style:** the `Procfile` runs migrations on release. **Any container host:** the `Dockerfile` serves the site with `web` (the default command) and runs the scheduler with `jobs`. Load balancers can use `/healthz/` as the health check.

In production, always set `DEBUG=False`, a long `SECRET_KEY`, `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS`, plus real SMTP settings so guests receive their confirmations.

## Roles

| Role | Access |
| --- | --- |
| Administrator | Everything, including staff accounts and settings |
| Manager | All operations, reports, room types and rates, menu, website content, audit log, and overrides (check-out with a balance) |
| Front Desk | Bookings, guests, check-in and check-out, charges, payments, M-Pesa prompts, housekeeping view, POS, inbox |
| Accountant | Bookings (read), payments, refunds, voids, M-Pesa reconciliation, reports |
| Housekeeping | Housekeeping board, tasks, room status, maintenance |
| Restaurant / Bar | POS orders, payments, charge to room |

## Brand

The official Hoteli logos live in [`static/brand/`](static/brand/), with usage rules in [`branding/README.md`](branding/README.md). There are colour, light (for dark backgrounds), single-colour, stacked and tagline versions, plus favicons, app icons and a GitHub social-preview image. Each hotel's own logo (uploaded under *Hotel name & logos*) is what guests see. The Hoteli logo appears in the staff area, the login screen and the demo.

## Development

```bash
python manage.py test
```

Build the static demo locally. This refuses to run unless the database is a demo database, so real guest data is never published.

```bash
python manage.py export_static_demo --out _site --base /hoteli/ --repo pizzatechies/hoteli
```

Project layout:

```
hoteli/        settings, URLs
accounts/      staff users and roles
core/          hotel settings, dashboard, reports, audit log, management commands
rooms/         room types, rooms, seasonal rates
bookings/      guests, bookings, folio (charges and payments), booking engine (services.py)
mpesa/         Daraja client, STK push, callbacks, C2B, reconciliation
housekeeping/  cleaning tasks and maintenance
pos/           restaurant and bar menu and orders
website/       public website, online booking and the website builder (builder.py)
templates/     HTML templates (Bootstrap 5)
static/        CSS and JS (live M-Pesa status widget, booking form)
```
