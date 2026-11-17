"""Configuration loaded from environment (.env)."""
import os

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
DEFAULT_LANG: str = os.getenv("DEFAULT_LANG", "fa")
# Numeric Telegram user ID that receives new-season / event notifications.
ADMIN_CHAT_ID: int = int(os.getenv("ADMIN_CHAT_ID", "0") or 0)

if not BOT_TOKEN or BOT_TOKEN == "put-your-botfather-token-here":
    raise RuntimeError(
        "TELEGRAM_BOT_TOKEN is not set. Copy .env.example to .env and add your BotFather token."
    )
