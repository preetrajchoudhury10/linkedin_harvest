import json
import logging
import os
from datetime import datetime
from pathlib import Path

from telegram import Update
from telegram.ext import ContextTypes

from harvester import LinkedInHarvester, decode_cookies_from_env
from extractor import categorize_and_write

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent
CONFIG_FILE = BASE_DIR / "config.json"
OUTPUT_DIR = BASE_DIR / "output"


def load_config():
    with open(CONFIG_FILE, encoding="utf-8") as f:
        return json.load(f)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "\U0001F916 <b>LinkedIn Email Harvester Bot</b>\n\n"
        "I search LinkedIn hiring posts for email addresses\n"
        "and send them to you as .txt files.\n\n"
        "<b>Commands:</b>\n"
        "/hunt \u2014 Run the harvest now\n"
        "/status \u2014 Last harvest stats\n"
        "/setcookies <base64> \u2014 Set LinkedIn session cookies\n"
        "/help \u2014 This message",
        parse_mode="HTML",
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "\U0001F4CB <b>Commands</b>\n\n"
        "/start \u2014 Welcome & info\n"
        "/help \u2014 This message\n"
        "/hunt \u2014 Run LinkedIn harvest immediately\n"
        "/status \u2014 Last run results\n"
        "/setcookies <base64> \u2014 Upload LinkedIn cookies\n\n"
        "<b>Setup:</b>\n"
        "1. Run <code>generate_cookies.py</code> locally\n"
        "2. Send /setcookies followed by the base64 string\n"
        "3. Then use /hunt to start harvesting",
        parse_mode="HTML",
    )


async def cmd_setcookies(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "Usage: /setcookies <base64_string>\n\n"
            "Run <code>generate_cookies.py</code> locally first to get the base64 string.",
            parse_mode="HTML",
        )
        return

    raw = " ".join(context.args)
    try:
        import base64
        decoded = base64.b64decode(raw)
        cookies = json.loads(decoded)
        context.bot_data["linkedin_cookies"] = cookies
        context.bot_data["has_cookies"] = True
        await update.message.reply_text(
            f"\u2705 LinkedIn cookies saved! {len(cookies)} cookies loaded.\n\n"
            "Use /hunt to start harvesting emails.",
        )
    except Exception as e:
        await update.message.reply_text(f"\u274C Invalid cookie data: {e}")


async def cmd_hunt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.bot_data.get("is_hunting"):
        await update.message.reply_text("\u23F3 Harvest already in progress...")
        return

    cookies = context.bot_data.get("linkedin_cookies")
    if not cookies:
        env_cookies = decode_cookies_from_env()
        if env_cookies:
            cookies = env_cookies
            context.bot_data["linkedin_cookies"] = cookies
            context.bot_data["has_cookies"] = True
        else:
            await update.message.reply_text(
                "\u274C No LinkedIn cookies found.\n\n"
                "Run <code>generate_cookies.py</code> locally, "
                "then use /setcookies to upload.",
                parse_mode="HTML",
            )
            return

    context.bot_data["is_hunting"] = True
    status_msg = await update.message.reply_text("\U0001F50D Starting LinkedIn harvest...")

    harvester = LinkedInHarvester()
    try:
        await status_msg.edit_text("\U0001F50D Launching browser & validating session...")
        harvester.start_browser(cookies_data=cookies)

        if not harvester.is_session_valid():
            await status_msg.edit_text(
                "\u274C LinkedIn session expired.\n"
                "Re-run <code>generate_cookies.py</code> locally and /setcookies again.",
                parse_mode="HTML",
            )
            context.bot_data["is_hunting"] = False
            harvester.close()
            return

        await status_msg.edit_text(
            "\u2705 Session valid! Searching "
            f"{len(load_config()['ai_ml_keywords'])} AI and "
            f"{len(load_config()['java_backend_keywords'])} backend keywords..."
        )

        config = load_config()
        ai_posts, backend_posts, total_posts = harvester.harvest(config)

        await status_msg.edit_text(
            f"\u2705 Scan complete! {total_posts} posts collected.\n"
            "\U0001F4E8 Extracting emails..."
        )

        OUTPUT_DIR.mkdir(exist_ok=True)
        stats = categorize_and_write(ai_posts, backend_posts, OUTPUT_DIR)
        stats["total_posts"] = total_posts

        context.bot_data["last_hunt"] = {
            "time": datetime.now().isoformat(),
            "ai_count": stats["ai"]["count"],
            "backend_count": stats["backend"]["count"],
            "total_posts": total_posts,
        }

        summary = (
            f"\u2705 <b>Harvest Complete</b>\n\n"
            f"\U0001F916 AI/ML \u2192 {stats['ai']['count']} emails\n"
            f"\u2615 Backend \u2192 {stats['backend']['count']} emails\n"
            f"\U0001F50E Posts scanned: {total_posts}\n"
            f"\U0001F4EC Total unique: {stats['ai']['count'] + stats['backend']['count']}"
        )

        await status_msg.edit_text(summary, parse_mode="HTML")

        for label in ("ai", "backend"):
            fp = stats[label]["file"]
            if Path(fp).stat().st_size > 0:
                with open(fp, "rb") as f:
                    await context.bot.send_document(
                        chat_id=update.effective_chat.id,
                        document=f,
                        filename=Path(fp).name,
                    )

    except Exception as e:
        logger.error(f"Harvest error: {e}")
        await status_msg.edit_text(f"\u274C Harvest failed: {e}")
    finally:
        harvester.close()
        context.bot_data["is_hunting"] = False


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    last = context.bot_data.get("last_hunt")
    if not last:
        await update.message.reply_text("No harvests yet. Use /hunt to start.")
        return

    await update.message.reply_text(
        f"\U0001F4CA <b>Last Harvest</b>\n\n"
        f"\U0001F5D3 Time: {last['time']}\n"
        f"\U0001F916 AI/ML emails: {last['ai_count']}\n"
        f"\u2615 Backend emails: {last['backend_count']}\n"
        f"\U0001F50E Posts scanned: {last['total_posts']}",
        parse_mode="HTML",
    )
