import asyncio
import base64
import json
import logging
import os
import random

from playwright.async_api import async_playwright

logger = logging.getLogger(__name__)


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


class LinkedInHarvester:
    def __init__(self):
        self._playwright = None
        self._browser = None
        self._context = None
        self._cookies_data = None

    async def start_browser(self, cookies_data=None):
        self._cookies_data = cookies_data
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--single-process",
                "--disable-extensions",
                "--disable-component-extensions-with-background-pages",
                "--disable-background-timer-throttling",
                "--disable-backgrounding-occluded-windows",
                "--disable-renderer-backgrounding",
                "--disable-ipc-flooding-protection",
                "--mute-audio",
            ],
        )
        self._context = await self._browser.new_context(
            viewport={"width": 1280, "height": 720},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            ),
            ignore_https_errors=True,
        )
        await self._context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'plugins', { get: () => [1,2,3,4,5] });
        """)

        if cookies_data:
            try:
                await self._context.add_cookies(cookies_data)
            except Exception as e:
                logger.warning(f"Error adding cookies: {e}")

        return self._context

    async def _ensure_browser(self):
        if self._context is None:
            logger.info("No browser context exists, creating new one")
            await self.start_browser(self._cookies_data)
            return True

        try:
            p = await self._context.new_page()
            await p.close()
            return True
        except Exception:
            logger.warning("Browser context dead, recreating...")
            await self._cleanup()
            await self.start_browser(self._cookies_data)
            return True

    async def _cleanup(self):
        try:
            if self._context:
                await self._context.close()
        except Exception:
            pass
        try:
            if self._browser:
                await self._browser.close()
        except Exception:
            pass
        try:
            if self._playwright:
                await self._playwright.stop()
        except Exception:
            pass
        self._context = None
        self._browser = None
        self._playwright = None

    async def _safe_page(self):
        await self._ensure_browser()
        return await self._context.new_page()

    async def is_session_valid(self):
        await self._ensure_browser()
        page = await self._context.new_page()
        try:
            await page.goto(
                "https://www.linkedin.com/feed/",
                wait_until="domcontentloaded",
                timeout=30000,
            )
            result = "feed" in page.url
            logger.info(f"LinkedIn session valid: {result}")
            await page.close()
            return result
        except Exception as e:
            logger.error(f"Session validation error: {e}")
            try:
                await page.close()
            except Exception:
                pass
            return False

    async def _search_keyword(self, keyword, max_posts=200):
        encoded = keyword.replace(" ", "%20")
        url = (
            f"https://www.linkedin.com/search/results/content/"
            f"?keywords={encoded}&origin=SWITCH_SEARCH_VERTICAL"
        )
        logger.info(f"Searching: '{keyword}'")

        page = await self._safe_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=45000)
        except Exception as e:
            logger.warning(f"Navigation failed for '{keyword}': {e}")
            await page.close()
            return []

        await asyncio.sleep(random.uniform(3, 5))

        seen_texts = set()
        scroll_attempts = 0
        max_scrolls = 30
        no_new_count = 0

        selectors = [
            "div.feed-shared-update-v2__description",
            "div.update-components-text",
            "div[class*='break-words']",
            "span.break-words",
            "div.occludable-update",
            "article",
        ]

        while len(seen_texts) < max_posts and scroll_attempts < max_scrolls:
            scroll_attempts += 1
            try:
                await page.evaluate("window.scrollBy(0, 900)")
            except Exception:
                break
            await asyncio.sleep(random.uniform(1.5, 3))

            found_any = False
            for sel in selectors:
                try:
                    elements = await page.query_selector_all(sel)
                    for el in elements:
                        text = (await el.inner_text()).strip()
                        if len(text) > 15 and text not in seen_texts:
                            seen_texts.add(text)
                            found_any = True
                except Exception:
                    continue

            if not found_any:
                no_new_count += 1
            else:
                no_new_count = 0

            if no_new_count >= 8:
                break

        try:
            await page.close()
        except Exception:
            pass

        results = list(seen_texts)[:max_posts]
        logger.info(f"  {len(results)} posts for '{keyword}'")
        return results

    async def harvest(self, config, progress_callback=None):
        settings = config["settings"]
        posts_per_keyword = settings.get("posts_per_keyword", 200)
        delay_range = settings.get("delay_between_keywords_sec", [5, 10])

        ai_ml_posts = []
        backend_posts = []
        total_posts = 0

        for category, keyword_list, target_list in [
            ("AI/ML", config["ai_ml_keywords"], ai_ml_posts),
            ("Backend", config["java_backend_keywords"], backend_posts),
        ]:
            kw_count = len(keyword_list)
            for idx, kw in enumerate(keyword_list, 1):
                try:
                    posts_found = 0
                    try:
                        posts = await self._search_keyword(kw, max_posts=posts_per_keyword)
                        for post in posts:
                            target_list.append((post, kw))
                        posts_found = len(posts)
                        total_posts += posts_found
                    except Exception as e:
                        logger.error(f"Error searching '{kw}': {e}")

                    if progress_callback:
                        try:
                            await progress_callback(category, idx, kw_count, kw, posts_found, total_posts)
                        except Exception:
                            pass

                except Exception as e:
                    logger.error(f"Unhandled error for '{kw}': {e}")

                delay = random.uniform(*delay_range)
                await asyncio.sleep(delay)

        return ai_ml_posts, backend_posts, total_posts

    async def close(self):
        await self._cleanup()
