# Tirtira Business Studio V4

Telegram AI business bot with Gemini, credits, AI image/advertisement, Text→PDF, PDF→Text, Photo→PDF and PDF OCR workflow.

## Render environment variables
Required:
- BOT_TOKEN
- GEMINI_API_KEY

Recommended:
- GEMINI_MODEL=gemini-3.6-flash
- GEMINI_IMAGE_MODEL=gemini-3.1-flash-image
- ADMIN_ID=7268036089
- ADMIN_USERNAME=ahmu2021
- WEBHOOK_URL=https://tirtira-business-bot.onrender.com

Payment starter variables:
- TELEBIRR_NUMBER=0920210606
- CBE_ACCOUNT=1000384896287
- CBE_NAME=Ahmed

## Credits
- New user: 20
- Referral: referrer +20, referred +10
- AI 1, Text→PDF 2, Photo→PDF 2, PDF→Text 2, OCR 3, Poster 10, AI Image 15

## Important
The payment flow in this V4 remains the existing manual Telebirr/CBE approval flow. Chapa V2 should be integrated separately after testing the content tools.
SQLite is suitable for a starter/demo deployment; use PostgreSQL for serious production.
