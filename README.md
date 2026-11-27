# Tirtira Business Studio V5

Telegram AI business assistant with Gemini, user credits, manual payment review, AI images/advertisements with an exact user-text overlay, text-to-PDF, PDF-to-text, photo-to-PDF and scanned-PDF OCR.

## Included files

- `main.py` — Telegram bot and business logic
- `main_web.py` — FastAPI webhook server for Render
- `assets/NotoSansEthiopic-Regular.ttf` — Ethiopic font used for readable Amharic advertisement text overlays
- `requirements.txt` — Python dependencies
- `render.yaml` — Render deployment blueprint
- `Procfile` — web start command
- `.env.example` — environment variable template

## Required environment variables

- `BOT_TOKEN` — Telegram bot token from BotFather
- `GEMINI_API_KEY` — Google AI Studio / Gemini API key
- `ADMIN_ID` — your Telegram numeric user ID, used to approve/reject payments

Payment details are optional in environment variables but must be set before customers can pay:
- `TELEBIRR_NUMBER`
- `CBE_ACCOUNT`
- `CBE_NAME`

Recommended:
- `ADMIN_USERNAME`
- `WEBHOOK_URL` — your Render service URL, e.g. `https://your-service.onrender.com`
- `TELEGRAM_WEBHOOK_SECRET` — a long random string
- `DATABASE_PATH=/var/data/tirtira.db` when using the Render disk in `render.yaml`

## Deploy on Render

1. Upload the project files to a GitHub repository.
2. In Render, create a **Blueprint** from that repository, or create a Web Service manually.
3. Add the required environment variables in Render. Never put bot tokens or API keys in GitHub.
4. Deploy. Open `https://YOUR-SERVICE.onrender.com/health`; it should return `{"status":"healthy"}`.
5. Open your Telegram bot and send `/start`.

The `render.yaml` blueprint attaches a 1 GB persistent disk at `/var/data` so the SQLite database can survive normal service restarts. Confirm that persistent disks are available on your Render plan.

## Local run (polling mode)

```bash
python -m pip install -r requirements.txt
```

Set environment variables, then run:

```bash
python main.py
```

On Windows CMD, for the current terminal only:

```bat
set BOT_TOKEN=YOUR_TELEGRAM_BOT_TOKEN
set GEMINI_API_KEY=YOUR_GEMINI_API_KEY
set ADMIN_ID=YOUR_NUMERIC_TELEGRAM_ID
python main.py
```

## Features and credit costs

- New account: 20 credits
- Referral: referrer +20; referred user +10
- AI text/chat: 1 credit
- Text → PDF: 2 credits
- Photo → PDF: 2 credits per photo
- PDF → Text: 2 credits
- PDF OCR: 3 credits
- Advertisement poster: 10 credits
- AI image: 15 credits

Credit packages:
- 100 credits — 50 ETB
- 500 credits — 200 ETB
- 1,000 credits — 350 ETB
- 3,000 credits — 900 ETB

Payments use manual Telebirr/CBE confirmation. The admin must verify the payment independently before approving it.

## Important notes

- OCR uses Gemini vision and processes up to 8 PDF pages per request.
- Text-to-PDF attempts to use an installed Unicode/Ethiopic font. For best Amharic output, provide a suitable `.ttf` font and set `PDF_FONT_PATH`.
- SQLite is suitable for a small deployment. For higher traffic or multi-instance production, migrate to PostgreSQL.
- Keep all secrets in Render environment variables, not in source code or GitHub.
- Test all payment, credit and file workflows with a private test bot before promoting it to customers.


## Advertisement text overlay

For `📸 Photo Advertisement`, Gemini creates the visual background and the bot then adds the business details supplied by the user as a separate readable text panel. This helps preserve phone numbers and Amharic wording exactly as typed. The supplied text is not rewritten by the image model. Keep the advertisement details concise enough to fit the poster. You can override the bundled font with `AD_FONT_PATH` if needed.
