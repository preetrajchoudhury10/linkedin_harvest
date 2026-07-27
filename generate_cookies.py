"""
Run this script LOCALLY (on your computer) to generate LinkedIn cookies
for deployment to Railway.

Usage:
    python generate_cookies.py

Steps:
1. A browser window opens
2. Log in to LinkedIn manually
3. Press Enter in the terminal
4. Copy the base64 output
5. Set it as LINKEDIN_COOKIES in your Railway dashboard
"""

import json
import base64
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    logger.error("playwright not installed. Run: pip install playwright && playwright install chromium")
    exit(1)


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

        print("\n" + "=" * 60)
        print("COPY THIS BASE64 STRING (entire block):")
        print("=" * 60)
        print(encoded)
        print("=" * 60)
        print("\nSet it as LINKEDIN_COOKIES in your Railway environment variables.\n")

        page.close()
        browser.close()


if __name__ == "__main__":
    main()
