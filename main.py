import asyncio
import logging
import sys
from os import getenv

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.types import Message, BotCommand, Update
from dotenv import load_dotenv

from bot.handlers import router as main_router
from database.db import init_db, add_user
from services.alerts import setup_scheduler, check_alerts
from aiohttp import web

# Configure logging FIRST so all modules can use it
logging.basicConfig(level=logging.INFO, stream=sys.stdout)

load_dotenv()

TOKEN = getenv("BOT_TOKEN")
PORT = int(getenv("PORT", 8080))

# Initialize Bot
bot = None
if TOKEN:
    bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))

dp = Dispatcher()
dp.include_router(main_router)

# --- FastAPI Setup for Vercel Serverless ---
from fastapi import FastAPI, Request, HTTPException

app = FastAPI(title="Crypto Alert Bot Serverless")

@app.post("/webhook")
async def webhook_handler(request: Request):
    if not bot:
        raise HTTPException(status_code=500, detail="Bot not initialized")
    try:
        payload = await request.json()
        await init_db()
        update = Update.model_validate(payload, context={"bot": bot})
        await dp.feed_update(bot, update)
        return {"status": "ok"}
    except Exception as e:
        logging.error(f"Error handling webhook: {e}")
        return {"status": "error", "message": str(e)}

@app.get("/api/check-alerts")
async def cron_alerts_handler():
    if not bot:
        raise HTTPException(status_code=500, detail="Bot not initialized")
    
    try:
        await init_db()
        logging.info("Checking alerts via serverless cron endpoint...")
        await check_alerts(bot)
        return {"status": "ok", "message": "Alerts checked successfully"}
    except Exception as e:
        logging.error(f"Error during alert checks: {e}")
        return {"status": "error", "message": str(e)}

@app.get("/api/set-webhook")
async def set_webhook_handler(request: Request):
    if not bot:
        raise HTTPException(status_code=500, detail="Bot not initialized")
    
    host = request.headers.get("host")
    scheme = "https" if "vercel.app" in host or "localhost" not in host else "http"
    webhook_url = f"{scheme}://{host}/webhook"
    
    try:
        await bot.set_webhook(webhook_url)
        return {"status": "ok", "message": f"Webhook successfully set to {webhook_url}"}
    except Exception as e:
        logging.error(f"Error setting webhook: {e}")
        return {"status": "error", "message": str(e)}

@app.get("/api/diagnose")
async def diagnose_handler():
    diagnostics = {}
    
    # 1. Check Bot Token
    if not TOKEN:
        diagnostics["bot_token"] = "Missing BOT_TOKEN environment variable!"
    else:
        hidden_token = TOKEN[:6] + "..." + TOKEN[-6:] if len(TOKEN) > 12 else "Too Short"
        diagnostics["bot_token"] = f"Configured ({hidden_token})"
        try:
            bot_info = await bot.get_me()
            diagnostics["telegram_api"] = f"Connected successfully as @{bot_info.username}"
        except Exception as e:
            diagnostics["telegram_api"] = f"Failed to connect to Telegram: {e}"
    
    # 2. Check Database Connection
    db_url = getenv("DATABASE_URL")
    if not db_url:
        diagnostics["database_type"] = "SQLite (Fallback) - WARNING: SQLite will fail on Vercel's read-only filesystem!"
    else:
        diagnostics["database_type"] = "PostgreSQL (Neon/Supabase)"
        
    try:
        from sqlalchemy.future import select
        from sqlalchemy import text
        from database.db import AsyncSessionLocal
        
        await init_db()
        diagnostics["database_init"] = "Success (tables created/verified)"
        
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        diagnostics["database_query"] = "Success (connection is active)"
    except Exception as e:
        diagnostics["database_query"] = f"Failed: {e}"
        
    return diagnostics

@app.get("/")
async def root_handler():
    return {"status": "alive", "service": "Crypto Alert Bot Webhook"}



# --- Local Web Server for non-Serverless runs ---
async def handle_ping(request):
    return web.Response(text="Bot is alive!")

async def handle_health(request):
    return web.Response(text="OK", status=200)

async def start_web_server():
    app_http = web.Application()
    app_http.router.add_get("/", handle_ping)
    app_http.router.add_get("/health", handle_health)
    runner = web.AppRunner(app_http)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logging.info(f"✅ Web server started on port {PORT}")


@dp.message(CommandStart())
async def command_start_handler(message: Message) -> None:
    await add_user(message.from_user.id, message.from_user.username)
    await message.answer(
        f"Hello, <b>{message.from_user.full_name}</b>!\n\n"
        "Welcome to the <b>Crypto Analytics & Alert Bot</b>. 🚀\n\n"
        "I can help you track real-time prices for any coin on decentralized exchanges.\n\n"
        "<b>Commands:</b>\n"
        "🔍 /search - Find a coin\n"
        "🔥 /trending - View trending coins\n"
        "🔔 /alerts - Set price alerts\n"
        "❓ /help - See all commands"
    )

async def set_commands(bot: Bot):
    commands = [
        BotCommand(command="start", description="Start the bot"),
        BotCommand(command="search", description="Search for a coin"),
        BotCommand(command="trending", description="View trending DEX coins"),
        BotCommand(command="alerts", description="Manage alerts"),
        BotCommand(command="help", description="Show help")
    ]
    await bot.set_my_commands(commands)


async def main() -> None:
    if not TOKEN:
        logging.error("❌ BOT_TOKEN environment variable is not set!")
        sys.exit(1)

    # Initialize DB
    try:
        await init_db()
        logging.info("✅ Database initialized successfully.")
    except Exception as e:
        logging.error(f"❌ Failed to initialize database: {e}")
        sys.exit(1)
    
    bot_local = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    
    # Setup background alerts
    setup_scheduler(bot_local)
    
    # Start the local web server FIRST
    await start_web_server()
    
    await set_commands(bot_local)
    logging.info("🤖 Bot is starting polling...")
    await dp.start_polling(bot_local)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Bot stopped!")

