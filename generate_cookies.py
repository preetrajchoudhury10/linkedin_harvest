"""
Run this script LOCALLY (on your computer) to generate LinkedIn cookies
for deployment to Railway.

Usage:
    python generate_cookies.py

Steps:
1. A browser window opens
2. Log in to LinkedIn manually
3. Press Enter in the terminal
4. The base64 string is saved to linkedin_cookies.txt
5. Open that file, copy contents, set as LINKEDIN_COOKIES in Railway
"""

import json
import base64
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    logger.error("playwright not installed. Run: pip install playwright && playwright install chromium")
    exit(1)

OUTPUT_FILE = Path(__file__).parent / "linkedin_cookies.txt"


def main():
    print("=" * 60)
    print("LinkedIn Cookie Generator")
    print("=" * 60)
    print("\nA browser window will open.")
    print("Log in to LinkedIn, then press Enter here.\n")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(
            viewport={"width": 1366, "height": 768},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()
        page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded")

        input(">>> Press Enter after you've logged in...")

        cookies = context.cookies()
        cookies_json = json.dumps(cookies)
        encoded = base64.b64encode(cookies_json.encode()).decode()

        OUTPUT_FILE.write_text(encoded)
        print(f"\n✅ Cookies saved to: {OUTPUT_FILE}")
        print(f"   ({len(cookies)} cookies, {len(encoded)} characters)")
        print("\nOpen linkedin_cookies.txt, copy the entire contents,")
        print("and paste it as LINKEDIN_COOKIES in your Railway dashboard.\n")

        page.close()
        browser.close()


if __name__ == "__main__":
    main()
