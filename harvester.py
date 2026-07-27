import json
import base64
import logging
import os
import random
import time

from playwright.sync_api import sync_playwright

logger = logging.getLogger(__name__)


def decode_cookies_from_env():
    raw = os.environ.get("LINKEDIN_COOKIES", "")
    if not raw:
        return None
    try:
        decoded = base64.b64decode(raw).decode()
        return json.loads(decoded)
    except Exception as e:
        logger.error(f"Failed to decode LINKEDIN_COOKIES: {e}")
        return None


def validate_session(page):
    page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded", timeout=30000)
    if "feed" in page.url:
        logger.info("LinkedIn session is valid")
        return True
    logger.warning("LinkedIn session expired or blocked")
    return False


def search_keyword(page, keyword, max_posts=200):
    encoded = keyword.replace(" ", "%20")
    url = (
        f"https://www.linkedin.com/search/results/content/"
        f"?keywords={encoded}&origin=SWITCH_SEARCH_VERTICAL"
    )
    logger.info(f"Searching: '{keyword}' (max {max_posts} posts)")
    page.goto(url, wait_until="domcontentloaded", timeout=30000)
    time.sleep(random.uniform(3, 5))

    seen_texts = set()
    scroll_attempts = 0
    max_scrolls = 80
    no_new_count = 0

    selectors = [
        "div.feed-shared-update-v2__description",
        "div.update-components-text",
        "div[class*='break-words']",
        "span.break-words",
        "div[data-view-name='search-result-entity']",
        "div.occludable-update",
        "span[dir='ltr']",
        "article",
    ]

    while len(seen_texts) < max_posts and scroll_attempts < max_scrolls:
        scroll_attempts += 1
        page.evaluate("window.scrollBy(0, 900)")
        time.sleep(random.uniform(1.5, 3))

        found_any = False
        for sel in selectors:
            try:
                elements = page.query_selector_all(sel)
                for el in elements:
                    text = el.inner_text().strip()
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

    results = list(seen_texts)[:max_posts]
    logger.info(f"  Collected {len(results)} posts for '{keyword}'")
    return results


class LinkedInHarvester:
    def __init__(self):
        self._playwright = None
        self._browser = None
        self._context = None

    def start_browser(self, cookies_data=None):
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
            ],
        )
        self._context = self._browser.new_context(
            viewport={"width": 1366, "height": 768},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            ),
        )
        self._context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'plugins', { get: () => [1,2,3,4,5] });
        """)

        if cookies_data:
            self._context.add_cookies(cookies_data)

        return self._context

    def is_session_valid(self):
        if not self._context:
            return False
        page = self._context.new_page()
        try:
            result = validate_session(page)
            page.close()
            return result
        except Exception as e:
            logger.error(f"Session validation error: {e}")
            page.close()
            return False

    def harvest(self, config):
        settings = config["settings"]
        posts_per_keyword = settings.get("posts_per_keyword", 200)
        delay_between_keywords = settings.get("delay_between_keywords_sec", [10, 20])

        page = self._context.new_page()
        ai_ml_posts = []
        backend_posts = []
        total_posts = 0

        for category, keyword_list, target_list in [
            ("AI/ML", config["ai_ml_keywords"], ai_ml_posts),
            ("Backend", config["java_backend_keywords"], backend_posts),
        ]:
            logger.info(f"Searching {len(keyword_list)} {category} keywords")
            for kw in keyword_list:
                try:
                    posts = search_keyword(page, kw, max_posts=posts_per_keyword)
                    for post in posts:
                        target_list.append((post, kw))
                    total_posts += len(posts)
                except Exception as e:
                    logger.error(f"Error searching '{kw}': {e}")

                delay = random.uniform(*delay_between_keywords)
                time.sleep(delay)

        page.close()
        return ai_ml_posts, backend_posts, total_posts

    def close(self):
        try:
            if self._context:
                self._context.close()
            if self._browser:
                self._browser.close()
            if self._playwright:
                self._playwright.stop()
        except Exception as e:
            logger.error(f"Error closing browser: {e}")
