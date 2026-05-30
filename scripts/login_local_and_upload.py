"""
Velora — Local Login + Auto Upload to Server
==============================================
Run this ON YOUR LOCAL LAPTOP (Windows/Mac) with Chrome visible.
After you login manually, this script automatically uploads the session to your server.

Usage (Client's laptop):
    python login_local_and_upload.py --server 68.178.160.47 --user autoclicker --profile indiamart

Requirements:
    pip install playwright paramiko
    playwright install chromium
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

META_FILENAME = ".velora_session_meta.json"


def zip_profile(profile_dir: Path, output_zip: Path) -> None:
    """Zip the browser profile for upload."""
    with zipfile.ZipFile(output_zip, 'w', zipfile.ZIP_DEFLATED) as zf:
        for file in profile_dir.rglob('*'):
            if file.is_file():
                zf.write(file, file.relative_to(profile_dir))


def write_session_meta(profile_dir: Path, meta: dict) -> None:
    (profile_dir / META_FILENAME).write_text(
        json.dumps(meta, indent=2),
        encoding="utf-8",
    )


def upload_to_server(
    zip_path: Path,
    server_ip: str,
    ssh_user: str,
    ssh_pass: str,
    profile_name: str,
    session_meta: dict | None = None,
) -> tuple[bool, str]:
    """Upload zipped profile to /data/browser_profiles (Docker volume path)."""
    remote_dir = f"/data/browser_profiles/{profile_name}"
    try:
        import paramiko
    except ImportError:
        print("ERROR: paramiko not installed. Run: pip install paramiko")
        return False, remote_dir

    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(server_ip, username=ssh_user, password=ssh_pass)

        # Remove old session first so uploads do not stack — one profile = one active session
        ssh.exec_command(f"rm -rf {remote_dir}")
        ssh.exec_command(f"mkdir -p {remote_dir} && chmod -R 755 /data/browser_profiles 2>/dev/null || true")

        sftp = ssh.open_sftp()
        remote_zip = f"/tmp/{profile_name}_profile.zip"
        sftp.put(str(zip_path), remote_zip)
        sftp.close()

        stdin, stdout, stderr = ssh.exec_command(
            f"unzip -o {remote_zip} -d {remote_dir} && rm -f {remote_zip}"
        )
        exit_code = stdout.channel.recv_exit_status()
        if exit_code != 0:
            err = stderr.read().decode(errors="replace")
            print(f"Unzip failed (exit {exit_code}): {err}")
            ssh.close()
            return False, remote_dir

        if session_meta:
            import tempfile
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".json", delete=False, encoding="utf-8"
            ) as tmp:
                json.dump(session_meta, tmp)
                local_meta = tmp.name
            sftp = ssh.open_sftp()
            sftp.put(local_meta, f"{remote_dir}/{META_FILENAME}")
            sftp.close()
            Path(local_meta).unlink(missing_ok=True)

        ssh.close()
        return True, remote_dir
    except Exception as e:
        print(f"Upload failed: {e}")
        return False, remote_dir


async def run_local_login(
    profile_name: str,
    url: str,
    server_ip: str,
    ssh_user: str,
    ssh_pass: str | None,
    timeout_seconds: int = 300
) -> None:
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("ERROR: playwright not installed. Run: pip install playwright && playwright install chromium")
        sys.exit(1)

    # Local profile directory
    profile_base = Path.home() / ".velora_profiles"
    profile_base.mkdir(parents=True, exist_ok=True)
    profile_dir = profile_base / profile_name

    print(f"\n{'='*60}")
    print("  Velora — Local Login + Server Upload")
    print(f"{'='*60}")
    print(f"  Profile     : {profile_name}")
    print(f"  Local path  : {profile_dir}")
    print(f"  Server      : {server_ip}")
    print(f"  Server user : {ssh_user}")
    print(f"  URL         : {url}")
    print(f"{'='*60}")
    print("\n  A Chrome window will open on YOUR COMPUTER.")
    print("  Please LOG IN manually to IndiaMART.")
    print("  After login, press ENTER here to upload session to server.")
    print(f"  (You have {timeout_seconds} seconds)\n")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=False,  # VISIBLE browser on local machine
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
            viewport={"width": 1280, "height": 800},
        )

        page = browser.pages[0] if browser.pages else await browser.new_page()
        await page.goto(url, wait_until="domcontentloaded", timeout=30_000)

        print(f"  Chrome opened: {url}")
        print("  >>> LOG IN NOW, then come back and press ENTER <<<\n")

        # Wait for user
        loop = asyncio.get_event_loop()
        try:
            await asyncio.wait_for(
                loop.run_in_executor(None, input, "  Press ENTER after login is complete: "),
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError:
            print(f"\n  Timeout! Saving session...")

        final_url = page.url
        final_lower = final_url.lower()
        login_ok = not any(p in final_lower for p in ("login", "signin", "sign-in"))
        if not login_ok:
            print("\n  WARNING: Still on login page. Finish login before pressing ENTER.")
        else:
            print(f"\n  Login looks OK (current page: {final_url})")

        session_meta = {
            "profile_name": profile_name,
            "uploaded_at": datetime.now(UTC).isoformat(),
            "login_url": url,
            "final_url": final_url,
            "uploaded_from": "login_local_and_upload",
            "login_verified": login_ok,
        }
        write_session_meta(profile_dir, session_meta)

        await browser.close()

    print(f"\n  Local session saved to: {profile_dir}")

    # Upload to server
    print(f"\n  Uploading to server {server_ip}...")
    
    if not ssh_pass:
        ssh_pass = input(f"  Enter SSH password for {ssh_user}@{server_ip}: ")

    with TemporaryDirectory() as tmpdir:
        zip_path = Path(tmpdir) / f"{profile_name}_profile.zip"
        print(f"  Zipping profile...")
        zip_profile(profile_dir, zip_path)
        
        print(f"  Uploading...")
        ok, remote_dir = upload_to_server(
            zip_path, server_ip, ssh_user, ssh_pass, profile_name, session_meta
        )
        if ok:
            print(f"\n  SUCCESS! Session uploaded to server.")
            print(f"  Server path: {remote_dir}")
            print(f"  Previous '{profile_name}' session was replaced (not stacked).")
            print(f"  Open Velora dashboard → Seller Session to verify YES/NO.")
            print(f"  Set job Browser Profile Name = '{profile_name}' and restart job.")
        else:
            print(f"\n  FAILED to upload. Manual upload needed:")
            print(f"  Zip file: {zip_path}")
            print(f"  On server run: sudo mkdir -p {remote_dir}")
            print(f"  Then unzip profile into: {remote_dir}")

    print(f"{'='*60}\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Login locally and upload session to Velora server"
    )
    parser.add_argument(
        "--profile",
        default="indiamart",
        help="Profile name. Default: indiamart",
    )
    parser.add_argument(
        "--url",
        default="https://seller.indiamart.com/bltxn/?pref=recent",
        help="URL to open for login. Default: IndiaMART recent leads page",
    )
    parser.add_argument(
        "--server",
        required=True,
        help="Server IP address (e.g., 68.178.160.47)",
    )
    parser.add_argument(
        "--user",
        default="autoclicker",
        help="SSH username for server. Default: autoclicker",
    )
    parser.add_argument(
        "--password",
        default=None,
        help="SSH password (will prompt if not provided)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Seconds to wait for login. Default: 300 (5 minutes)",
    )
    args = parser.parse_args()

    asyncio.run(run_local_login(
        args.profile,
        args.url,
        args.server,
        args.user,
        args.password,
        args.timeout
    ))


if __name__ == "__main__":
    main()
