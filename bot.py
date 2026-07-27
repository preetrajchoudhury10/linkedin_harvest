import json
import logging
import os
from datetime import datetime
from pathlib import Path

from telegram import Update
from telegram.ext import ContextTypes

from harvester import LinkedInHarvester, decode_cookies_from_env
from extractor import categorize_and_write
from email_db import EmailDatabase

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent
CONFIG_FILE = BASE_DIR / "config.json"
OUTPUT_DIR = BASE_DIR / "output"
DB_FILE = BASE_DIR / "email_db.json"


def load_config():
    with open(CONFIG_FILE, encoding="utf-8") as f:
        return json.load(f)


def get_db():
    return EmailDatabase(DB_FILE)


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = get_db()
    bd = db.breakdown()
    await update.message.reply_text(
        "\U0001F916 <b>LinkedIn Email Harvester Bot</b>\n\n"
        "I search LinkedIn hiring posts for email addresses\n"
        "and send you only <b>fresh</b> ones each day.\n\n"
        f"\U0001F4CA <b>Master DB:</b> {bd['total']} unique emails collected\n"
        f"  \U0001F916 AI/ML: {bd['ai']}  |  \u2615 Backend: {bd['backend']}\n\n"
        "<b>Commands:</b>\n"
        "/hunt \u2014 Run harvest now\n"
        "/status \u2014 Last harvest + DB stats\n"
        "/alldb \u2014 Download full email database\n"
        "/setcookies (base64) \u2014 Set LinkedIn session\n"
        "/help \u2014 All commands",
        parse_mode="HTML",
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "\U0001F4CB <b>Commands</b>\n\n"
        "/start \u2014 Welcome & DB stats\n"
        "/help \u2014 This message\n"
        "/hunt \u2014 Run LinkedIn harvest immediately\n"
        "/status \u2014 Last run + master DB stats\n"
        "/alldb \u2014 Download complete email database\n"
        "/setcookies + base64 \u2014 Upload LinkedIn cookies\n\n"
        "<b>How dedup works:</b>\n"
        "Each email is stored in the master DB on first sight.\n"
        "Daily files only contain <b>new</b> (unseen) emails.\n"
        "Use /alldb anytime to get everything collected so far.",
        parse_mode="HTML",
    )


async def cmd_setcookies(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "Usage: /setcookies (base64_string)\n\n"
            "Run <code>generate_cookies.py</code> locally first.",
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
            "Use /hunt to start harvesting.",
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
        await harvester.start_browser(cookies_data=cookies)

        if not await harvester.is_session_valid():
            await status_msg.edit_text(
                "\u274C LinkedIn session expired.\n"
                "Re-run generate_cookies.py and /setcookies again.",
                parse_mode="HTML",
            )
            context.bot_data["is_hunting"] = False
            await harvester.close()
            return

        config = load_config()
        total_keywords = len(config["ai_ml_keywords"]) + len(config["java_backend_keywords"])
        db = get_db()

        await status_msg.edit_text(
            f"\u2705 Session valid! Searching {total_keywords} keywords "
            f"(DB has {db.total_count()} emails already)..."
        )

        ai_posts, backend_posts, total_posts = await harvester.harvest(config)

        await status_msg.edit_text(
            f"\u2705 Scan complete! {total_posts} posts collected.\n"
            "\U0001F4E8 Filtering new emails..."
        )

        OUTPUT_DIR.mkdir(exist_ok=True)
        stats = categorize_and_write(ai_posts, backend_posts, OUTPUT_DIR, email_db=db)
        stats["total_posts"] = total_posts

        context.bot_data["last_hunt"] = {
            "time": datetime.now().isoformat(),
            "ai_new": stats["ai"]["new"],
            "ai_total": stats["ai"]["total_found"],
            "backend_new": stats["backend"]["new"],
            "backend_total": stats["backend"]["total_found"],
            "total_posts": total_posts,
        }

        total_new = stats["ai"]["new"] + stats["backend"]["new"]
        db_breakdown = db.breakdown()

        summary = (
            f"\u2705 <b>Harvest Complete</b>\n\n"
            f"\U0001F4E8 <b>New emails today:</b> {total_new}\n"
            f"  \U0001F916 AI/ML: {stats['ai']['new']} new (found {stats['ai']['total_found']})\n"
            f"  \u2615 Backend: {stats['backend']['new']} new (found {stats['backend']['total_found']})\n"
            f"\U0001F50E Posts scanned: {total_posts}\n\n"
            f"\U0001F4CA <b>Master DB:</b> {db_breakdown['total']} total unique\n"
            f"  \U0001F916 AI/ML: {db_breakdown['ai']}  |  \u2615 Backend: {db_breakdown['backend']}"
        )

        await status_msg.edit_text(summary, parse_mode="HTML")

        if total_new > 0:
            for label in ("ai", "backend"):
                fp = stats[label]["file"]
                if Path(fp).stat().st_size > 0:
                    with open(fp, "rb") as f:
                        await context.bot.send_document(
                            chat_id=update.effective_chat.id,
                            document=f,
                            filename=Path(fp).name,
                        )
        else:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="\U0001F4AD No new emails found this time. All emails already in DB.",
            )

    except Exception as e:
        logger.error(f"Harvest error: {e}")
        await status_msg.edit_text(f"\u274C Harvest failed: {e}")
    finally:
        await harvester.close()
        context.bot_data["is_hunting"] = False


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = get_db()
    db_breakdown = db.breakdown()
    last = context.bot_data.get("last_hunt")

    lines = [
        f"\U0001F4CA <b>Master Email Database</b>\n",
        f"\U0001F4E6 Total unique emails: {db_breakdown['total']}",
        f"  \U0001F916 AI/ML: {db_breakdown['ai']}",
        f"  \u2615 Backend: {db_breakdown['backend']}",
    ]

    if last:
        lines += [
            "",
            f"\U0001F5D3 <b>Last Harvest</b>",
            f"  Time: {last['time']}",
            f"  New AI: {last['ai_new']} (found {last['ai_total']})",
            f"  New Backend: {last['backend_new']} (found {last['backend_total']})",
            f"  Posts scanned: {last['total_posts']}",
        ]

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def cmd_alldb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = get_db()
    if db.total_count() == 0:
        await update.message.reply_text("No emails in database yet. Use /hunt to start.")
        return

    await update.message.reply_text("\U0001F4E6 Exporting master database...")
    export_path = OUTPUT_DIR / "master_db_all.txt"
    db.export_all_txt(export_path)

    with open(export_path, "rb") as f:
        await context.bot.send_document(
            chat_id=update.effective_chat.id,
            document=f,
            filename="master_db_all.txt",
            caption=f"\U0001F4CA Master DB — {db.total_count()} total emails\n"
                    f"AI/ML: {db.breakdown()['ai']}  |  Backend: {db.breakdown()['backend']}",
        )
