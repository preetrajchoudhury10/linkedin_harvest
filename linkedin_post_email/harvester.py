import asyncio
import base64
import json
import logging
import os
import random
import re

import httpx

logger = logging.getLogger(__name__)

EMAIL_REGEX = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")

BLOCKED_DOMAINS = {
    "linkedin.com", "example.com", "domain.com", "email.com",
    "mail.com", "test.com", "yourcompany.com", "company.com",
    "yourdomain.com", "mydomain.com", "your.email", "company.co",
    "abc.com", "xyz.com", "domain.co", "site.com",
}


def decode_cookies_from_env():
    raw = os.environ.get("LINKEDIN_COOKIES", "")
    if not raw:
        return None
    try:
        raw = raw.strip()
        padding = 4 - len(raw) % 4
        if padding != 4:
            raw += "=" * padding
        decoded = base64.b64decode(raw).decode()
        return json.loads(decoded)
    except Exception as e:
        logger.error(f"Failed to decode LINKEDIN_COOKIES: {e}")
        return None


def cookies_to_dict(playwright_cookies):
    return {c["name"]: c["value"] for c in playwright_cookies if "name" in c and "value" in c}


def is_valid_email(email):
    email_lower = email.lower()
    local_part, domain = email_lower.split("@", 1)
    if domain in BLOCKED_DOMAINS:
        return False
    if len(local_part) < 2 or len(domain) < 4:
        return False
    if re.search(r"(\.{2,}|_{2,})", email_lower):
        return False
    return True


def find_emails_in_text(text):
    found = EMAIL_REGEX.findall(text)
    return {e.strip().lower() for e in found if is_valid_email(e.strip().lower())}


class LinkedInHarvester:
    def __init__(self):
        self._client = None
        self._cookies_dict = {}

    async def start_browser(self, cookies_data=None):
        self._cookies_dict = cookies_to_dict(cookies_data) if cookies_data else {}
        self._client = httpx.AsyncClient(
            cookies=self._cookies_dict,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/126.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
                "DNT": "1",
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1",
            },
            follow_redirects=True,
            timeout=30.0,
        )
        return self._client

    async def _ensure_browser(self):
        if self._client is None:
            logger.info("Creating new httpx client")
            await self.start_browser()
        return True

    async def _cleanup(self):
        if self._client:
            await self._client.aclose()
            self._client = None

    async def is_session_valid(self):
        await self._ensure_browser()
        try:
            resp = await self._client.get("https://www.linkedin.com/feed/")
            valid = "feed" in str(resp.url)
            logger.info(f"Session valid: {valid} (url: {resp.url}, status: {resp.status_code})")
            return valid
        except Exception as e:
            logger.error(f"Session validation error: {e}")
            return False

    async def _search_keyword(self, keyword):
        encoded = keyword.replace(" ", "%20")
        url = (
            f"https://www.linkedin.com/search/results/content/"
            f"?keywords={encoded}&origin=SWITCH_SEARCH_VERTICAL"
        )
        logger.info(f"Searching: '{keyword}'")

        await self._ensure_browser()
        try:
            resp = await self._client.get(url)
        except Exception as e:
            logger.warning(f"Request failed: {e}")
            return []

        logger.info(f"  Status: {resp.status_code}, URL: {resp.url}, Size: {len(resp.text)} bytes")

        if resp.status_code != 200:
            logger.warning(f"  Non-200 response")
            return []

        page_title = ""
        m = __import__("re").search(r"<title>(.*?)</title>", resp.text, __import__("re").IGNORECASE | __import__("re").DOTALL)
        if m:
            page_title = m.group(1).strip()
        at_count = resp.text.count("@")
        logger.info(f"  Title: {page_title[:120]}, @ count: {at_count}")
        if at_count == 0 and len(resp.text) > 200:
            snippet = resp.text[:400]
            logger.info(f"  HTML snippet: {snippet}")
            if "sign-in" in snippet.lower() or "login" in snippet.lower():
                logger.warning("  -> Looks like a login page!")
            elif "__NEXT_DATA__" in snippet or "deferred-state" in snippet:
                logger.info("  -> Client-rendered shell (no server content)")

        emails = find_emails_in_text(resp.text)
        result = list(emails)

        if result:
            logger.info(f"  {len(result)} emails: {result[:3]}...")
        else:
            logger.info(f"  0 emails")

        return result

    async def harvest(self, config, progress_callback=None):
        settings = config["settings"]
        delay_range = settings.get("delay_between_keywords_sec", [1, 3])

        ai_emails = []
        backend_emails = []

        for category, keyword_list, target_list in [
            ("AI/ML", config["ai_ml_keywords"], ai_emails),
            ("Backend", config["java_backend_keywords"], backend_emails),
        ]:
            kw_count = len(keyword_list)
            for idx, kw in enumerate(keyword_list, 1):
                emails = []
                try:
                    emails = await self._search_keyword(kw)
                    for e in emails:
                        target_list.append((e, kw))
                except Exception as e:
                    logger.error(f"Error searching '{kw}': {e}")

                if progress_callback:
                    try:
                        await progress_callback(
                            category, idx, kw_count, kw,
                            len(emails), len(target_list),
                        )
                    except Exception:
                        pass

                await asyncio.sleep(random.uniform(*delay_range))

        return ai_emails, backend_emails, len(ai_emails) + len(backend_emails)

    async def close(self):
        await self._cleanup()
