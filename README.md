# Tirtira Business Bot — Final Starter Version

Gemini-powered Amharic/English Telegram business assistant with:
- Shortcut menu
- Gemini AI
- SQLite users/credits/jobs/payments/referrals
- Starter credit bonus
- Referral rewards
- Buy Credits with Telebirr/CBE
- Admin payment approval/rejection
- FastAPI Telegram webhook for Render

## Render Environment Variables

Required:
- `BOT_TOKEN`
- `GEMINI_API_KEY`

Optional:
- `GEMINI_MODEL` (default: `gemini-2.5-flash`)
- `WEBHOOK_URL` (recommended: your Render URL, e.g. `https://your-service.onrender.com`)
- `ADMIN_ID` (default: `7268036089`)
- `ADMIN_USERNAME` (default: `ahmu2021`)
- `TELEBIRR_NUMBER` (default: `0920210606`)
- `CBE_ACCOUNT` (default: `1000384896287`)
- `CBE_NAME` (default: `Ahmed`)

## Packages
- 100 Credits = 50 ETB
- 500 Credits = 200 ETB
- 1,000 Credits = 350 ETB
- 3,000 Credits = 900 ETB

New users receive 20 free credits.
Referral: referrer gets 20 credits; new referred user gets 10 bonus credits.
Each successful AI request costs 1 credit.

## Payment flow
User selects Buy Credits -> selects package -> receives payment instructions -> sends transaction/reference + screenshot -> admin gets Approve/Reject buttons -> credits are added only after approval.

SQLite is created automatically as `tirtira.db`.
