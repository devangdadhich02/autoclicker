"""
Velora — One-Time Browser Login Script
=======================================
Run this script ONCE to log into any website (e.g. IndiaMART seller portal).
The browser session/cookies are saved to the profile directory.
After this, the automation reuses the saved session automatically — no re-login needed.

Usage (Docker):
    docker compose exec backend python scripts/login_browser.py --profile indiamart --url https://seller.indiamart.com/

Usage (local):
    python scripts/login_browser.py --profile indiamart --url https://seller.indiamart.com/

Arguments:
    --profile   Name for the browser profile (e.g. indiamart, tradeindia)
    --url       URL to open for login (default: https://seller.indiamart.com/)
    --timeout   Seconds to wait for manual login (default: 300 = 5 minutes)
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path


async def run_login(profile_name: str, url: str, timeout_seconds: int) -> None:
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("ERROR: playwright not installed. Run: pip install playwright && playwright install chromium")
        sys.exit(1)

    # Determine profile directory
    # Works both inside Docker (/data/browser_profiles) and locally (./data/browser_profiles)
    base_dirs = [Path("/data/browser_profiles"), Path("./data/browser_profiles")]
    profile_base = None
    for d in base_dirs:
        try:
            d.mkdir(parents=True, exist_ok=True)
            profile_base = d
            break
        except PermissionError:
            continue

    if profile_base is None:
        print("ERROR: Cannot create browser profile directory.")
        sys.exit(1)

    profile_dir = profile_base / profile_name
    profile_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*60}")
    print("  Velora — One-Time Login Helper")
    print(f"{'='*60}")
    print(f"  Profile : {profile_name}")
    print(f"  Saved at: {profile_dir}")
    print(f"  URL     : {url}")
    print(f"  Timeout : {timeout_seconds} seconds")
    print(f"{'='*60}")
    print("\n  A browser window will open.")
    print("  Please LOG IN manually in the browser.")
    print("  Once logged in, press ENTER here to save the session.")
    print("  (You have", timeout_seconds, "seconds)\n")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=False,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
            ],
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        )

        page = browser.pages[0] if browser.pages else await browser.new_page()
        await page.goto(url, wait_until="domcontentloaded", timeout=30_000)

        print(f"  Browser opened: {url}")
        print("  >>> Log in now, then come back here and press ENTER <<<\n")

        # Wait for user input or timeout
        loop = asyncio.get_event_loop()
        try:
            await asyncio.wait_for(
                loop.run_in_executor(None, input, "  Press ENTER after login is complete: "),
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError:
            print(f"\n  Timeout reached ({timeout_seconds}s). Saving whatever session exists...")

        # Verify login by checking current URL
        current_url = page.url
        print(f"\n  Current URL: {current_url}")

        if "login" in current_url.lower() or "signin" in current_url.lower():
            print("  WARNING: Still on login page — session may not be saved correctly.")
            print("  Try again and make sure you complete the login before pressing ENTER.")
        else:
            print("  Session looks good! Saving...")

        await browser.close()

    print(f"\n  Session saved to: {profile_dir}")
    print(f"\n  NOW — In your Velora job, set:")
    print(f"    Browser Profile Name = {profile_name}")
    print(f"\n  The automation will reuse this session automatically.")
    print(f"{'='*60}\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="One-time browser login to save session for Velora automation"
    )
    parser.add_argument(
        "--profile",
        default="default",
        help="Profile name (e.g. indiamart, tradeindia). Default: default",
    )
    parser.add_argument(
        "--url",
        default="https://seller.indiamart.com/",
        help="URL to open for login. Default: https://seller.indiamart.com/",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Seconds to wait for manual login. Default: 300 (5 minutes)",
    )
    args = parser.parse_args()
    asyncio.run(run_login(args.profile, args.url, args.timeout))


if __name__ == "__main__":
    main()
