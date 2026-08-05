import json
import logging
import os
from datetime import datetime
from pathlib import Path

from telegram import Update
from telegram.ext import ContextTypes

from harvester import LinkedInHarvester, decode_cookies_from_env, find_emails_in_text
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
        "/hunt \u2014 Run harvest (default 2 pages/keyword)\n"
        "/hunt 5 \u2014 Custom pages per keyword\n"
        "/hunt ai \u2014 AI/ML keywords only\n"
        "/hunt 3 backend \u2014 Backend, 3 pages each\n"
        "/search <keywords> \u2014 Search your own keywords\n"
        "/status \u2014 Last harvest + DB stats\n"
        "/alldb \u2014 Download full email database\n"
        "/debug \u2014 Diagnose session & search\n"
        "/setcookies (base64) \u2014 Set LinkedIn session\n"
        "/help \u2014 All commands",
        parse_mode="HTML",
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "\U0001F4CB <b>Commands</b>\n\n"
        "/start \u2014 Welcome & DB stats\n"
        "/help \u2014 This message\n"
        "/hunt \u2014 Run harvest (2 pages/keyword)\n"
        "/hunt 5 \u2014 Custom pages per keyword\n"
        "/hunt ai \u2014 AI/ML keywords only\n"
        "/hunt 3 backend \u2014 Backend, 3 pages each\n"
        "/search <keywords> \u2014 Search your own keywords\n"
        "/status \u2014 Last run + master DB stats\n"
        "/alldb \u2014 Download complete email database\n"
        "/debug \u2014 Test session & keyword search\n"
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


async def cmd_debug(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("Running diagnostics...")
    lines = ["<b>Diagnostics</b>\n"]

    raw = os.environ.get("LINKEDIN_COOKIES", "")
    lines.append(f"<b>Cookies:</b>")
    lines.append(f"  Env exists: {'yes' if raw else 'no'} ({len(raw)} chars)")
    cookies = context.bot_data.get("linkedin_cookies") or decode_cookies_from_env()
    if cookies:
        lines.append(f"  Decoded: {len(cookies)} cookies")
        for c in cookies[:3]:
            lines.append(f"    {c.get('name','?')}: {c.get('value','')[:30]}...")
    else:
        lines.append("  \u274C No cookies")

    h = LinkedInHarvester()
    try:
        await h.start_browser(cookies_data=cookies)
        valid = await h.is_session_valid()
        lines.append(f"\n<b>Session:</b> {'\u2705 Valid' if valid else '\u274C Invalid'}")
    except Exception as e:
        lines.append(f"\n<b>Session:</b> \u274C Error: {e}")
        await h.close()
        await msg.edit_text("\n".join(lines), parse_mode="HTML")
        return

    import re as re_mod
    kw = "hiring generative AI engineer"
    lines.append(f"\n<b>Test search:</b> \"{kw}\"")
    try:
        encoded = kw.replace(" ", "%20")
        url = f"https://www.linkedin.com/search/results/content/?keywords={encoded}&origin=SWITCH_SEARCH_VERTICAL"
        await h._ensure_browser()
        resp = await h._client.get(url)
        lines.append(f"  Status: {resp.status_code}, URL: {resp.url}")
        lines.append(f"  Size: {len(resp.text)} bytes")

        m = re_mod.search(r"<title>(.*?)</title>", resp.text, re_mod.I | re_mod.S)
        title = m.group(1).strip()[:80] if m else "N/A"
        lines.append(f"  Title: {title}")

        at_count = resp.text.count("@")
        lines.append(f"  '@' count: {at_count}")

        if "sign-in" in resp.text.lower()[:2000]:
            lines.append("  \u274C Looks like a LOGIN page")
        elif "challenge" in resp.text.lower()[:2000]:
            lines.append("  \u26A0 Might be a CHALLENGE page")

        found = find_emails_in_text(resp.text)
        if found:
            for e in list(found)[:10]:
                lines.append(f"  <code>{e}</code>")
        else:
            lines.append("  \u274C No emails found in page")
    except Exception as e:
        lines.append(f"  \u274C Error: {e}")
    finally:
        await h.close()

    await msg.edit_text("\n".join(lines), parse_mode="HTML")


async def cmd_hunt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.bot_data.get("is_hunting"):
        await update.message.reply_text("\u23F3 Harvest already in progress...")
        return

    pages = None
    category = None
    if context.args:
        for arg in context.args:
            low = arg.lower()
            if low.isdigit():
                pages = max(1, int(low))
            elif low in ("ai", "ml", "aiml"):
                category = "ai"
            elif low in ("backend", "java", "spring"):
                category = "backend"
            else:
                await update.message.reply_text(
                    "Usage: <code>/hunt [pages] [category]</code>\n\n"
                    "Examples:\n"
                    "  <code>/hunt</code> \u2014 all keywords, 2 pages each\n"
                    "  <code>/hunt 5</code> \u2014 all, 5 pages each\n"
                    "  <code>/hunt ai</code> \u2014 AI/ML only\n"
                    "  <code>/hunt 3 backend</code> \u2014 Backend only, 3 pages\n"
                    "  <code>/hunt 5 ai</code> \u2014 AI/ML only, 5 pages",
                    parse_mode="HTML",
                )
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
    parts = []
    if category:
        parts.append(category.upper())
    if pages:
        parts.append(f"{pages} pages/keyword")
    tag = f" ({', '.join(parts)})" if parts else ""
    status_msg = await update.message.reply_text(f"\U0001F50D Starting LinkedIn harvest{tag}...")

    harvester = LinkedInHarvester()
    try:
        await status_msg.edit_text("\U0001F50D Validating session...")
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
        if category == "ai":
            config["java_backend_keywords"] = []
        elif category == "backend":
            config["ai_ml_keywords"] = []
        total_keywords = len(config["ai_ml_keywords"]) + len(config["java_backend_keywords"])
        db = get_db()

        effective_pages = pages if pages else config['settings'].get('pages_per_keyword', 2)
        cat_tag = f" [{category.upper()}]" if category else ""
        await status_msg.edit_text(
            f"\u2705 Session valid! Searching {total_keywords} keywords{cat_tag} "
            f"({effective_pages} pages each, "
            f"DB has {db.total_count()} emails already)..."
        )

        async def progress(category, idx, total, keyword, emails_found, cumulative):
            nonlocal status_msg
            try:
                await status_msg.edit_text(
                    f"\U0001F50E <b>{category}</b> \u2014 keyword {idx}/{total}\n"
                    f"   \u201C{keyword}\u201D \u2192 {emails_found} emails\n"
                    f"   \U0001F4E6 Cumulative: {cumulative} emails"
                )
            except Exception:
                pass

        ai_emails, backend_emails, total_emails = await harvester.harvest(config, pages=pages, progress_callback=progress)

        await status_msg.edit_text(
            f"\u2705 Scan complete! {total_emails} emails found.\n"
            "\U0001F4E8 Filtering new..."
        )

        OUTPUT_DIR.mkdir(exist_ok=True)
        stats = categorize_and_write(ai_emails, backend_emails, OUTPUT_DIR, email_db=db)
        stats["total_emails"] = total_emails

        context.bot_data["last_hunt"] = {
            "time": datetime.now().isoformat(),
            "ai_new": stats["ai"]["new"],
            "ai_total": stats["ai"]["total_found"],
            "backend_new": stats["backend"]["new"],
            "backend_total": stats["backend"]["total_found"],
            "total_emails": total_emails,
        }

        total_new = stats["ai"]["new"] + stats["backend"]["new"]
        db_breakdown = db.breakdown()

        summary = (
            f"\u2705 <b>Harvest Complete</b>\n\n"
            f"\U0001F4E8 <b>New emails today:</b> {total_new}\n"
            f"  \U0001F916 AI/ML: {stats['ai']['new']} new (found {stats['ai']['total_found']})\n"
            f"  \u2615 Backend: {stats['backend']['new']} new (found {stats['backend']['total_found']})\n"
            f"\U0001F50E Emails found: {total_emails}\n\n"
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


async def cmd_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.bot_data.get("is_hunting"):
        await update.message.reply_text("\u23F3 A harvest is already in progress...")
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: <code>/search &lt;keywords&gt;</code>\n\n"
            "Search LinkedIn with your own keywords and get fresh emails.\n\n"
            "Examples:\n"
            "  <code>/search We're Hiring For AI / ML</code>\n"
            "  <code>/search Java developer|Spring Boot hiring</code>\n"
            "  <code>/search 3 AI engineer|ML engineer</code>\n\n"
            "Separate multiple keywords with <code>|</code> (pipe).\n"
            "A leading number sets pages per keyword.",
            parse_mode="HTML",
        )
        return

    raw = " ".join(context.args).strip()
    tokens = raw.split()
    pages = None
    if tokens and tokens[0].isdigit():
        pages = max(1, int(tokens[0]))
        raw = " ".join(tokens[1:])

    keywords = [k.strip() for k in raw.split("|") if k.strip()]
    if not keywords:
        await update.message.reply_text("\u274C No valid keywords found.", parse_mode="HTML")
        return
    if len(keywords) > 20:
        await update.message.reply_text("\u26A0 Maximum 20 keywords per search.", parse_mode="HTML")
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
    effective_pages = pages or 2
    status_msg = await update.message.reply_text(
        f"\U0001F50D Custom search: {len(keywords)} keyword(s), "
        f"{effective_pages} pages each..."
    )

    harvester = LinkedInHarvester()
    try:
        await status_msg.edit_text("\U0001F50D Validating session...")
        await harvester.start_browser(cookies_data=cookies)

        if not await harvester.is_session_valid():
            await status_msg.edit_text(
                "\u274C LinkedIn session expired.\n"
                "Re-run generate_cookies.py and /setcookies again.",
                parse_mode="HTML",
            )
            return

        db = get_db()
        await status_msg.edit_text(
            f"\u2705 Session valid! Searching {len(keywords)} custom keyword(s) "
            f"(DB has {db.total_count()} emails already)..."
        )

        config = load_config()
        delay_range = config["settings"].get("delay_between_keywords_sec", [1, 3])

        async def progress(category, idx, total, keyword, emails_found, cumulative):
            nonlocal status_msg
            try:
                await status_msg.edit_text(
                    f"\U0001F50E <b>{category}</b> \u2014 keyword {idx}/{total}\n"
                    f"   \u201C{keyword}\u201D \u2192 {emails_found} emails\n"
                    f"   \U0001F4E6 Cumulative: {cumulative} emails"
                )
            except Exception:
                pass

        pairs = await harvester.harvest_custom(
            keywords,
            pages=effective_pages,
            delay_range=delay_range,
            progress_callback=progress,
        )

        total_emails = len(pairs)
        await status_msg.edit_text(
            f"\u2705 Scan complete! {total_emails} emails found.\n"
            "\U0001F4E8 Filtering new..."
        )

        OUTPUT_DIR.mkdir(exist_ok=True)
        new_pairs = db.add_emails(pairs, "custom")
        new_emails = [e for e, _ in new_pairs]

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = OUTPUT_DIR / f"custom_{ts}.txt"
        with open(filepath, "w", encoding="utf-8") as f:
            for email in sorted(new_emails):
                f.write(f"{email}\n")

        db_breakdown = db.breakdown()
        summary = (
            f"\u2705 <b>Custom Search Complete</b>\n\n"
            f"\U0001F4E8 <b>New emails:</b> {len(new_emails)}\n"
            f"\U0001F50E Emails found: {total_emails}\n\n"
            f"\U0001F4CA <b>Master DB:</b> {db_breakdown['total']} total unique\n"
            f"  \U0001F916 AI/ML: {db_breakdown['ai']}  |  \u2615 Backend: {db_breakdown['backend']}"
            f"  |  \U0001F4C0 Custom: {db_breakdown['custom']}"
        )
        await status_msg.edit_text(summary, parse_mode="HTML")

        if new_emails:
            with open(filepath, "rb") as f:
                await context.bot.send_document(
                    chat_id=update.effective_chat.id,
                    document=f,
                    filename=filepath.name,
                )
        else:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="\U0001F4AD No new emails this time. All already in DB.",
            )

    except Exception as e:
        logger.error(f"Custom search error: {e}")
        await status_msg.edit_text(f"\u274C Custom search failed: {e}")
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
            f"  Emails found: {last['total_emails']}",
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
