import logging
import os
from datetime import time as dtime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from telegram.ext import Application, CommandHandler, MessageHandler, filters

from bot import cmd_start, cmd_help, cmd_hunt, cmd_status, cmd_setcookies
from harvester import LinkedInHarvester, decode_cookies_from_env
from extractor import categorize_and_write
from pathlib import Path
import json

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent
CONFIG_FILE = BASE_DIR / "config.json"
OUTPUT_DIR = BASE_DIR / "output"


def load_config():
    with open(CONFIG_FILE, encoding="utf-8") as f:
        return json.load(f)


async def scheduled_hunt(app: Application):
    if app.bot_data.get("is_hunting"):
        logger.info("Skipping scheduled hunt — one already in progress")
        return

    cookies = app.bot_data.get("linkedin_cookies")
    if not cookies:
        cookies = decode_cookies_from_env()
        if not cookies:
            logger.warning("Skipping scheduled hunt — no cookies available")
            return
        app.bot_data["linkedin_cookies"] = cookies

    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not chat_id:
        logger.warning("Skipping scheduled hunt — no TELEGRAM_CHAT_ID")
        return

    app.bot_data["is_hunting"] = True
    logger.info("Starting scheduled harvest...")

    harvester = LinkedInHarvester()
    try:
        await app.bot.send_message(
            chat_id=chat_id,
            text="\U0001F50D <b>Scheduled LinkedIn harvest started...</b>",
            parse_mode="HTML",
        )

        harvester.start_browser(cookies_data=cookies)

        if not harvester.is_session_valid():
            await app.bot.send_message(
                chat_id=chat_id,
                text="\u274C Session expired. Re-run generate_cookies.py and update LINKEDIN_COOKIES.",
            )
            app.bot_data["is_hunting"] = False
            harvester.close()
            return

        config = load_config()
        ai_posts, backend_posts, total_posts = harvester.harvest(config)

        OUTPUT_DIR.mkdir(exist_ok=True)
        stats = categorize_and_write(ai_posts, backend_posts, OUTPUT_DIR)
        stats["total_posts"] = total_posts

        app.bot_data["last_hunt"] = {
            "time": __import__("datetime").datetime.now().isoformat(),
            "ai_count": stats["ai"]["count"],
            "backend_count": stats["backend"]["count"],
            "total_posts": total_posts,
        }

        summary = (
            f"\u2705 <b>Scheduled Harvest Complete</b>\n\n"
            f"\U0001F916 AI/ML \u2192 {stats['ai']['count']} emails\n"
            f"\u2615 Backend \u2192 {stats['backend']['count']} emails\n"
            f"\U0001F50E Posts scanned: {total_posts}"
        )
        await app.bot.send_message(chat_id=chat_id, text=summary, parse_mode="HTML")

        for label in ("ai", "backend"):
            fp = stats[label]["file"]
            if Path(fp).stat().st_size > 0:
                with open(fp, "rb") as f:
                    await app.bot.send_document(
                        chat_id=chat_id,
                        document=f,
                        filename=Path(fp).name,
                    )

        logger.info(f"Scheduled harvest complete: {stats}")

    except Exception as e:
        logger.error(f"Scheduled harvest failed: {e}")
        await app.bot.send_message(
            chat_id=chat_id,
            text=f"\u274C Scheduled harvest failed: {e}",
        )
    finally:
        harvester.close()
        app.bot_data["is_hunting"] = False


def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN not set")
        return

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("hunt", cmd_hunt))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("setcookies", cmd_setcookies))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, cmd_help))

    async def post_init(application: Application):
        application.bot_data["has_cookies"] = False
        application.bot_data["is_hunting"] = False
        application.bot_data["linkedin_cookies"] = decode_cookies_from_env()

        scheduler = AsyncIOScheduler()
        scheduler.add_job(
            scheduled_hunt,
            CronTrigger(hour=9, minute=0),
            args=[application],
            id="daily_hunt",
            name="Daily LinkedIn harvest at 09:00",
        )
        scheduler.start()
        logger.info("Scheduler started: daily harvest at 09:00")

        chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
        if chat_id:
            await application.bot.send_message(
                chat_id=chat_id,
                text="\U0001F916 <b>LinkedIn Email Harvester Bot is live!</b>\n\n"
                     "Daily harvest scheduled at 09:00.\n"
                     "Use /hunt to run now, /help for commands.",
                parse_mode="HTML",
            )

    app.post_init = post_init
    logger.info("Starting bot polling...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
