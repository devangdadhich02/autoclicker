"""
Velora — One-Time Browser Login Script
=======================================
Run this script ONCE to log into any website (e.g. IndiaMART seller portal).
The browser session/cookies are saved to the profile directory.
After this, the automation reuses the saved session automatically — no re-login needed.

Usage (Docker with virtual display - for servers without GUI):
    docker compose exec backend python scripts/login_browser.py --profile indiamart --url https://seller.indiamart.com/

Usage (local with visible browser):
    python scripts/login_browser.py --profile indiamart --url https://seller.indiamart.com/

For remote servers without display, use xvfb-run:
    xvfb-run python scripts/login_browser.py --profile indiamart --url https://seller.indiamart.com/

Arguments:
    --profile   Name for the browser profile (e.g. indiamart, tradeindia)
    --url       URL to open for login (default: https://seller.indiamart.com/)
    --timeout   Seconds to wait for manual login (default: 300 = 5 minutes)
    --xvfb      Use virtual display automatically (default: auto-detect)
"""

from __future__ import annotations

import argparse
import asyncio
import os
import subprocess
import sys
from pathlib import Path


def setup_virtual_display() -> tuple[bool, subprocess.Popen | None]:
    """Setup Xvfb virtual display if no DISPLAY is available."""
    if os.environ.get("DISPLAY"):
        return False, None  # Real display available

    # Try to start Xvfb
    try:
        xvfb_proc = subprocess.Popen(
            ["Xvfb", ":99", "-screen", "0", "1280x800x24", "-ac"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        os.environ["DISPLAY"] = ":99"
        print("  Virtual display (Xvfb) started on :99")
        return True, xvfb_proc
    except FileNotFoundError:
        print("ERROR: Xvfb not found. Install it: apt-get install xvfb")
        print("  Or run with: xvfb-run python scripts/login_browser.py ...")
        return False, None


async def run_login(profile_name: str, url: str, timeout_seconds: int, use_xvfb: bool | None = None) -> None:
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("ERROR: playwright not installed. Run: pip install playwright && playwright install chromium")
        sys.exit(1)

    # Setup virtual display if needed
    xvfb_proc = None
    if use_xvfb or (use_xvfb is None and not os.environ.get("DISPLAY")):
        using_xvfb, xvfb_proc = setup_virtual_display()
        if not using_xvfb and not os.environ.get("DISPLAY"):
            print("\nERROR: No display available and Xvfb not found.")
            print("Install Xvfb: apt-get install xvfb")
            print("Then run: xvfb-run python scripts/login_browser.py ...")
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
    if xvfb_proc:
        print(f"  Display : Virtual (Xvfb) — no GUI visible")
    print(f"{'='*60}")
    print("\n  Browser is starting...")
    if xvfb_proc:
        print("  (Running in virtual display — you won't see a window)")
        print("  The session will still be saved correctly.")
    print("  Please wait for the page to load...")
    print("  Once loaded, press ENTER to save the session.")
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

    # Cleanup Xvfb
    if xvfb_proc:
        xvfb_proc.terminate()
        print("  Virtual display stopped.")

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
    parser.add_argument(
        "--xvfb",
        action="store_true",
        default=None,
        help="Force use of virtual display (Xvfb). Auto-detected if no DISPLAY env var.",
    )
    parser.add_argument(
        "--no-xvfb",
        dest="xvfb",
        action="store_false",
        help="Disable virtual display even if no DISPLAY is available.",
    )
    args = parser.parse_args()
    asyncio.run(run_login(args.profile, args.url, args.timeout, args.xvfb))


if __name__ == "__main__":
    main()
