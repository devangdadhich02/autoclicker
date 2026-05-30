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

# Common project paths on the VPS (Docker Compose)
COMPOSE_DIR_CANDIDATES = (
    "/home/autoclicker/autoclicker",
    "/home/autoclicker/AUTO_CLICKER",
    "/home/autoclicker/velora",
    "/opt/velora",
)


def zip_profile(profile_dir: Path, output_zip: Path) -> None:
    """Zip the browser profile for upload."""
    with zipfile.ZipFile(output_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for file in profile_dir.rglob("*"):
            if file.is_file():
                zf.write(file, file.relative_to(profile_dir))


def write_session_meta(profile_dir: Path, meta: dict) -> None:
    (profile_dir / META_FILENAME).write_text(
        json.dumps(meta, indent=2),
        encoding="utf-8",
    )


def _ssh_exec(ssh, command: str, timeout: int = 180) -> tuple[int, str, str]:
    _stdin, stdout, stderr = ssh.exec_command(command, timeout=timeout)
    exit_code = stdout.channel.recv_exit_status()
    return (
        exit_code,
        stdout.read().decode(errors="replace"),
        stderr.read().decode(errors="replace"),
    )


def _detect_compose_dir(ssh) -> str | None:
    for directory in COMPOSE_DIR_CANDIDATES:
        code, out, _ = _ssh_exec(
            ssh, f"test -f {directory}/docker-compose.yml && echo {directory}"
        )
        if code == 0 and out.strip():
            return out.strip()
    return None


def _upload_meta_docker(
    ssh,
    compose_dir: str,
    profile_name: str,
    container_profile: str,
    session_meta: dict,
) -> None:
    import tempfile

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as tmp:
        json.dump(session_meta, tmp)
        local_meta = tmp.name
    host_meta = f"/tmp/{profile_name}_session_meta.json"
    sftp = ssh.open_sftp()
    sftp.put(local_meta, host_meta)
    sftp.close()
    Path(local_meta).unlink(missing_ok=True)
    _ssh_exec(
        ssh,
        f"cd {compose_dir} && docker compose cp {host_meta} "
        f"backend:{container_profile}/{META_FILENAME} && rm -f {host_meta}",
    )


def upload_to_server(
    zip_path: Path,
    server_ip: str,
    ssh_user: str,
    ssh_pass: str,
    profile_name: str,
    session_meta: dict | None = None,
    compose_dir: str | None = None,
) -> tuple[bool, str, int]:
    """
    Upload profile into the backend container volume (/data/browser_profiles).
    SSH to host /data alone does NOT work when Velora runs in Docker.
    Returns (ok, remote_path, file_count).
    """
    host_profile = f"/data/browser_profiles/{profile_name}"
    container_profile = f"/data/browser_profiles/{profile_name}"
    remote_zip_host = f"/tmp/{profile_name}_profile.zip"
    file_count = 0

    try:
        import paramiko
    except ImportError:
        print("ERROR: paramiko not installed. Run: pip install paramiko")
        return False, host_profile, 0

    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(server_ip, username=ssh_user, password=ssh_pass)

        sftp = ssh.open_sftp()
        sftp.put(str(zip_path), remote_zip_host)
        sftp.close()

        compose = compose_dir or _detect_compose_dir(ssh)
        used_docker = False

        if compose:
            inner_zip = f"/tmp/{profile_name}_profile.zip"
            inner_cmd = (
                f"rm -rf {container_profile} && mkdir -p {container_profile} && "
                f"unzip -o {inner_zip} -d {container_profile} && rm -f {inner_zip}"
            )
            docker_cmd = (
                f"cd {compose} && "
                f"docker compose cp {remote_zip_host} backend:{inner_zip} && "
                f"docker compose exec -T backend sh -c {json.dumps(inner_cmd)} && "
                f"rm -f {remote_zip_host}"
            )
            code, out, err = _ssh_exec(ssh, docker_cmd)
            if code == 0:
                used_docker = True
                remote_path = container_profile
                print(f"  Uploaded via Docker ({compose}) → {remote_path}")
            else:
                print(f"  Docker upload failed, trying host path: {err or out}")

        if not used_docker:
            _ssh_exec(ssh, f"rm -rf {host_profile}")
            code, out, err = _ssh_exec(
                ssh,
                f"mkdir -p {host_profile} && unzip -o {remote_zip_host} -d {host_profile} "
                f"&& rm -f {remote_zip_host}",
            )
            if code != 0:
                print(f"Unzip failed (exit {code}): {err or out}")
                ssh.close()
                return False, host_profile, 0
            remote_path = host_profile
            print(f"  Uploaded to host path: {remote_path}")
            print(
                "  NOTE: If Velora uses Docker, files may not appear in the dashboard. "
                "Use docker compose on the server or re-run this script after deploy."
            )

        if session_meta:
            if used_docker and compose:
                _upload_meta_docker(
                    ssh, compose, profile_name, container_profile, session_meta
                )
            else:
                import tempfile

                with tempfile.NamedTemporaryFile(
                    mode="w", suffix=".json", delete=False, encoding="utf-8"
                ) as tmp:
                    json.dump(session_meta, tmp)
                    local_meta = tmp.name
                sftp = ssh.open_sftp()
                sftp.put(local_meta, f"{remote_path}/{META_FILENAME}")
                sftp.close()
                Path(local_meta).unlink(missing_ok=True)

        if used_docker and compose:
            code, out, _ = _ssh_exec(
                ssh,
                f"cd {compose} && docker compose exec -T backend "
                f"find {container_profile} -type f 2>/dev/null | wc -l",
            )
            if code == 0:
                try:
                    file_count = int(out.strip())
                except ValueError:
                    file_count = 0

        ssh.close()
        return True, remote_path, file_count
    except Exception as e:
        print(f"Upload failed: {e}")
        return False, host_profile, 0


async def run_local_login(
    profile_name: str,
    url: str,
    server_ip: str,
    ssh_user: str,
    ssh_pass: str | None,
    timeout_seconds: int = 300,
    compose_dir: str | None = None,
) -> None:
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print(
            "ERROR: playwright not installed. Run: pip install playwright "
            "&& playwright install chromium"
        )
        sys.exit(1)

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
            headless=False,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
            viewport={"width": 1280, "height": 800},
        )

        page = browser.pages[0] if browser.pages else await browser.new_page()
        await page.goto(url, wait_until="domcontentloaded", timeout=30_000)

        print(f"  Chrome opened: {url}")
        print("  >>> LOG IN NOW, then come back and press ENTER <<<\n")

        loop = asyncio.get_event_loop()
        try:
            await asyncio.wait_for(
                loop.run_in_executor(
                    None, input, "  Press ENTER after login is complete: "
                ),
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError:
            print("\n  Timeout! Saving session...")

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

    print(f"\n  Uploading to server {server_ip}...")

    if not ssh_pass:
        ssh_pass = input(f"  Enter SSH password for {ssh_user}@{server_ip}: ")

    with TemporaryDirectory() as tmpdir:
        zip_path = Path(tmpdir) / f"{profile_name}_profile.zip"
        print("  Zipping profile...")
        zip_profile(profile_dir, zip_path)

        print("  Uploading into Docker backend volume...")
        ok, remote_dir, file_count = upload_to_server(
            zip_path,
            server_ip,
            ssh_user,
            ssh_pass,
            profile_name,
            session_meta,
            compose_dir=compose_dir,
        )
        if ok:
            print("\n  SUCCESS! Session uploaded to server.")
            print(f"  Server path: {remote_dir}")
            print(f"  Files on server: {file_count}")
            if file_count < 10:
                print(
                    "  WARNING: Very few files — upload may be incomplete. "
                    "Re-login, press ENTER, and check Seller Session = YES."
                )
            print(f"  Previous '{profile_name}' session was replaced (not stacked).")
            print("  Open Velora dashboard → Seller Session (should show YES).")
            print("  Restart your IndiaMART job if it was already running.")
        else:
            print("\n  FAILED to upload. Manual upload:")
            print(f"  Zip file: {zip_path}")
            print(
                f"  On server: cd ~/autoclicker && docker compose cp {zip_path} "
                f"backend:/tmp/profile.zip && docker compose exec -T backend "
                f"unzip -o /tmp/profile.zip -d {remote_dir}"
            )

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
        "--compose-dir",
        default=None,
        help="Path to docker-compose project on server (auto-detected if omitted)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Seconds to wait for login. Default: 300 (5 minutes)",
    )
    args = parser.parse_args()

    asyncio.run(
        run_local_login(
            args.profile,
            args.url,
            args.server,
            args.user,
            args.password,
            args.timeout,
            args.compose_dir,
        )
    )


if __name__ == "__main__":
    main()
