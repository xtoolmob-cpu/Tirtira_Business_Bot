import os, logging
from fastapi import FastAPI, Request
from telegram import Update
from main import build
logging.basicConfig(level=logging.INFO); logger=logging.getLogger(__name__)
app=FastAPI(title="Tirtira Business Studio")
bot=build()
@app.on_event("startup")
async def startup():
    await bot.initialize(); await bot.start()
    base=(os.getenv("WEBHOOK_URL") or os.getenv("RENDER_EXTERNAL_URL") or "").rstrip("/")
    if base:
        url=f"{base}/telegram/webhook"; await bot.bot.set_webhook(url=url); logger.info("Telegram webhook set: %s",url)
@app.on_event("shutdown")
async def shutdown(): await bot.stop(); await bot.shutdown()
@app.get("/")
async def root(): return {"status":"ok","service":"Tirtira Business Studio"}
@app.get("/health")
async def health(): return {"status":"healthy"}
@app.post("/telegram/webhook")
async def webhook(request:Request):
    data=await request.json(); await bot.process_update(Update.de_json(data,bot.bot)); return {"ok":True}
