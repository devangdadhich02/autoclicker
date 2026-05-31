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
import re
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

META_FILENAME = ".velora_session_meta.json"
COOKIES_FILENAME = ".velora_cookies.json"

# Chrome cache — huge, not needed for login; causes "Permission denied" on server
_SKIP_DIR_PARTS = frozenset(
    {
        "Cache",
        "Code Cache",
        "GPUCache",
        "ShaderCache",
        "GrShaderCache",
        "blob_storage",
        "Crashpad",
        "BrowserMetrics",
        "Safe Browsing",
        "Service Worker",
    }
)
_SKIP_FILE_NAMES = frozenset({"LOCK", "LOG", "LOG.old", "Cookies-journal"})

# Common project paths on the VPS (Docker Compose)
COMPOSE_DIR_CANDIDATES = (
    "/home/autoclicker/autoclicker",
    "/home/autoclicker/AUTO_CLICKER",
    "/home/autoclicker/velora",
    "/opt/velora",
)


def _should_skip_profile_file(file: Path) -> bool:
    if file.name in _SKIP_FILE_NAMES:
        return True
    return any(part in _SKIP_DIR_PARTS for part in file.parts)


def zip_profile(profile_dir: Path, output_zip: Path) -> None:
    """Zip cookies + preferences only (skip Chrome cache folders)."""
    count = 0
    with zipfile.ZipFile(output_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for file in profile_dir.rglob("*"):
            if file.is_file() and not _should_skip_profile_file(file):
                zf.write(file, file.relative_to(profile_dir))
                count += 1
    print(f"  Zipped {count} profile files (cache folders skipped)")


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


def _host_bind_profile_dir(ssh, compose_dir: str | None) -> str:
    """Folder bind-mounted to /data/browser_profiles in docker-compose.yml."""
    base = compose_dir or "/home/autoclicker/autoclicker"
    return f"{base}/browser_profiles"


def _detect_backend_container(ssh) -> str | None:
    for docker_bin in ("docker", "sudo docker"):
        code, out, _ = _ssh_exec(
            ssh,
            f"{docker_bin} ps --format '{{{{.Names}}}}' 2>/dev/null "
            "| grep -E 'backend' | head -1",
        )
        if code == 0 and out.strip():
            return out.strip()
    return None


def _count_files(ssh, path: str) -> int:
    code, out, _ = _ssh_exec(ssh, f"find {path} -type f 2>/dev/null | wc -l")
    if code != 0:
        return 0
    try:
        return int(out.strip())
    except ValueError:
        return 0


def _count_files_in_container(ssh, container: str, profile_name: str) -> int:
    inner = f"/data/browser_profiles/{profile_name}"
    for docker_bin in ("docker", "sudo docker"):
        code, out, _ = _ssh_exec(
            ssh,
            f"{docker_bin} exec {container} find {inner} -type f 2>/dev/null | wc -l",
        )
        if code == 0:
            try:
                return int(out.strip())
            except ValueError:
                pass
    return 0


def _put_meta_sftp(ssh, remote_dir: str, session_meta: dict) -> None:
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


def _stop_backend_container(ssh) -> str | None:
    container = _detect_backend_container(ssh)
    if not container:
        return None
    print("  Stopping server bot container (so profile can be replaced)...")
    for docker_bin in ("docker", "sudo docker"):
        code, _, _ = _ssh_exec(ssh, f"{docker_bin} stop {container} 2>/dev/null", timeout=120)
        if code == 0:
            return container
    return container


def _start_backend_container(ssh, container: str | None) -> None:
    if not container:
        return
    for docker_bin in ("docker", "sudo docker"):
        if _ssh_exec(ssh, f"{docker_bin} start {container} 2>/dev/null")[0] == 0:
            print(f"  Restarted container: {container}")
            return


def _prepare_host_profile_dir(ssh, host_profile_dir: str, ssh_user: str) -> None:
    parent = str(Path(host_profile_dir).parent).replace("\\", "/")
    _ssh_exec(ssh, f"sudo mkdir -p {parent}")
    _ssh_exec(ssh, f"sudo rm -rf {host_profile_dir}")
    _ssh_exec(ssh, f"sudo mkdir -p {host_profile_dir}")
    _ssh_exec(ssh, f"sudo chown -R {ssh_user}:{ssh_user} {parent}")


def _upload_via_host_bind(
    ssh,
    remote_zip_host: str,
    host_profile_dir: str,
    profile_name: str,
    session_meta: dict | None,
    ssh_user: str,
) -> tuple[bool, str, int]:
    """SSH unzip into project/browser_profiles — works without docker CLI for the client."""
    stopped = _stop_backend_container(ssh)
    _prepare_host_profile_dir(ssh, host_profile_dir, ssh_user)
    unzip_cmd = (
        f"unzip -o {remote_zip_host} -d {host_profile_dir} && rm -f {remote_zip_host}"
    )
    code, _out, err = _ssh_exec(ssh, unzip_cmd)
    if code != 0:
        unzip_cmd = (
            f"sudo unzip -o {remote_zip_host} -d {host_profile_dir} && "
            f"sudo chown -R {ssh_user}:{ssh_user} {host_profile_dir} && "
            f"rm -f {remote_zip_host}"
        )
        code, _out, err = _ssh_exec(ssh, unzip_cmd)
    _start_backend_container(ssh, stopped)
    if code != 0:
        print(f"  Host upload failed: {err}")
        return False, host_profile_dir, 0
    if session_meta:
        _put_meta_sftp(ssh, host_profile_dir, session_meta)
    file_count = _count_files(ssh, host_profile_dir)
    print(f"  Uploaded via SSH → {host_profile_dir}")
    print(f"  Files on server folder: {file_count}")
    return True, host_profile_dir, file_count


def _upload_via_docker_cp(
    ssh,
    remote_zip_host: str,
    container: str,
    profile_name: str,
    session_meta: dict | None,
) -> tuple[bool, str, int]:
    inner_zip = f"/tmp/{profile_name}_profile.zip"
    inner_dir = f"/data/browser_profiles/{profile_name}"
    inner_cmd = (
        f"rm -rf {inner_dir} && mkdir -p {inner_dir} && "
        f"unzip -o {inner_zip} -d {inner_dir} && rm -f {inner_zip}"
    )
    for docker_bin in ("docker", "sudo docker"):
        cp_code, _cp_out, cp_err = _ssh_exec(
            ssh,
            f"{docker_bin} cp {remote_zip_host} {container}:{inner_zip}",
        )
        if cp_code != 0:
            continue
        ex_code, _ex_out, ex_err = _ssh_exec(
            ssh,
            f"{docker_bin} exec {container} sh -c {json.dumps(inner_cmd)}",
        )
        _ssh_exec(ssh, f"rm -f {remote_zip_host}")
        if ex_code != 0:
            print(f"  Docker exec failed ({docker_bin}): {ex_err}")
            continue
        if session_meta:
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
                f"{docker_bin} cp {host_meta} {container}:{inner_dir}/{META_FILENAME} "
                f"&& rm -f {host_meta}",
            )
        file_count = _count_files_in_container(ssh, container, profile_name)
        print(f"  Uploaded via {docker_bin} → container {container}")
        print(f"  Files visible to dashboard: {file_count}")
        return True, inner_dir, file_count
    return False, inner_dir, 0


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
    Upload session so the Velora dashboard can read it.
    Prefer host bind folder (no docker permission). Verify file count before SUCCESS.
    """
    remote_zip_host = f"/tmp/{profile_name}_profile.zip"
    min_files = 10

    try:
        import paramiko
    except ImportError:
        print("ERROR: paramiko not installed. Run: pip install paramiko")
        return False, "", 0

    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(server_ip, username=ssh_user, password=ssh_pass)

        sftp = ssh.open_sftp()
        sftp.put(str(zip_path), remote_zip_host)
        sftp.close()

        compose = compose_dir or _detect_compose_dir(ssh)
        bind_base = _host_bind_profile_dir(ssh, compose)
        host_profile_dir = f"{bind_base}/{profile_name}"
        _ssh_exec(ssh, f"mkdir -p {bind_base}")

        ok = False
        remote_path = host_profile_dir
        file_count = 0
        container_count = 0

        # 1) Host bind folder — client SSH only; matches docker-compose ./browser_profiles mount
        ok, remote_path, file_count = _upload_via_host_bind(
            ssh, remote_zip_host, host_profile_dir, profile_name, session_meta, ssh_user
        )
        if not ok:
            # zip was removed; re-upload for docker attempt
            sftp = ssh.open_sftp()
            sftp.put(str(zip_path), remote_zip_host)
            sftp.close()

        container = _detect_backend_container(ssh)
        if container:
            container_count = _count_files_in_container(ssh, container, profile_name)

        # 2) If bind mount not wired yet (host has files, container sees 0), try docker cp
        if ok and file_count >= min_files and container_count < min_files:
            print(
                "  Host folder has files but the app container does not see them yet."
            )
            print("  Trying direct docker copy...")
            sftp = ssh.open_sftp()
            sftp.put(str(zip_path), remote_zip_host)
            sftp.close()
            d_ok, d_path, container_count = _upload_via_docker_cp(
                ssh, remote_zip_host, container, profile_name, session_meta
            )
            if d_ok and container_count >= min_files:
                remote_path = d_path
                file_count = container_count
            elif file_count >= min_files and container_count < min_files:
                print(
                    "\n  *** SERVER NEEDS ONE-TIME UPDATE (admin, not client) ***"
                )
                print(
                    "  On the server once: cd ~/autoclicker && git pull && "
                    "mkdir -p browser_profiles && docker compose up -d --build"
                )
                print(
                    "  Then run login.ps1 again. Client steps stay the same."
                )
                ssh.close()
                return False, remote_path, container_count

        elif not ok and container:
            sftp = ssh.open_sftp()
            sftp.put(str(zip_path), remote_zip_host)
            sftp.close()
            ok, remote_path, file_count = _upload_via_docker_cp(
                ssh, remote_zip_host, container, profile_name, session_meta
            )
            container_count = file_count

        ssh.close()

        visible = max(file_count, container_count)
        if not ok or visible < min_files:
            print(
                f"\n  UPLOAD NOT ACCEPTED: only {visible} files (need {min_files}+)."
            )
            print("  Dashboard will show NO until this succeeds.")
            return False, remote_path, visible

        print(
            f"\n  Verified: {visible} files — dashboard Seller Session should show YES."
        )
        return True, remote_path, visible
    except Exception as e:
        print(f"Upload failed: {e}")
        return False, "", 0


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
        try:
            body = await page.evaluate("() => (document.body.innerText || '').slice(0, 4000)")
        except Exception:
            body = ""
        body_lower = body.lower()
        has_leads_feed = bool(
            re.search(
                r"\d+\s*(?:min|mins|hr|hrs|hour|hours|day|days)\s*ago",
                body,
                re.I,
            )
        )
        on_marketing = (
            "how to register" in body_lower
            and "success stories" in body_lower
            and "sign in" in body_lower
            and not has_leads_feed
        )
        login_ok = (
            not any(p in final_lower for p in ("login", "signin", "sign-in"))
            and not on_marketing
            and (has_leads_feed or "lead manager" in body_lower or "bltxn" in final_lower)
        )
        if on_marketing:
            print(
                "\n  ERROR: Still on public IndiaMART page. Open Recent Buy Leads, "
                "see buyer rows, then press ENTER."
            )
        elif not login_ok:
            print("\n  WARNING: Login not verified. Finish login on Recent Buy Leads.")
        else:
            print(f"\n  Login verified (leads feed visible). Page: {final_url}")

        session_meta = {
            "profile_name": profile_name,
            "uploaded_at": datetime.now(UTC).isoformat(),
            "login_url": url,
            "final_url": final_url,
            "uploaded_from": "login_local_and_upload",
            "login_verified": login_ok,
        }
        write_session_meta(profile_dir, session_meta)

        try:
            cookies = await browser.cookies()
            (profile_dir / COOKIES_FILENAME).write_text(
                json.dumps(cookies, ensure_ascii=False),
                encoding="utf-8",
            )
            print(
                f"  Exported {len(cookies)} portable cookies "
                f"(for Linux server — required after upload)"
            )
        except Exception as exc:
            print(f"  WARNING: Could not export portable cookies: {exc}")

        await browser.close()

    print(f"\n  Local session saved to: {profile_dir}")

    print(f"\n  Uploading to server {server_ip}...")

    if not ssh_pass:
        ssh_pass = input(f"  Enter SSH password for {ssh_user}@{server_ip}: ")

    with TemporaryDirectory() as tmpdir:
        zip_path = Path(tmpdir) / f"{profile_name}_profile.zip"
        print("  Zipping profile (cookies + login data only)...")
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
            print("\n  ========================================")
            print("  SUCCESS — seller session is on the server")
            print("  ========================================")
            print(f"  Files stored: {file_count}")
            print("  Open dashboard → Seller Session → Refresh → should be YES")
            print("  If still NO, wait 10 seconds and Refresh again.")
        else:
            print("\n  ========================================")
            print("  FAILED — session did NOT reach the dashboard")
            print("  ========================================")
            print("  Your login on this PC was saved, but the server did not get it.")
            print("  Try login.ps1 again. If it fails twice, contact Velora support.")
            sys.exit(1)

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
