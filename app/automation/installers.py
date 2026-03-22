"""
AI application full installer.

Downloads each installer binary completely, then runs it silently to
actually install the application on the host system.

Platform support:
  Linux   — .sh scripts, .AppImage, .deb, .rpm, .run, .tar.gz / .tar.bz2
  macOS   — .dmg (with .app copy or embedded .pkg), .pkg, .zip, .sh
  Windows — .exe (NSIS / Inno Setup silent flags), .msi, .zip (PowerShell)
"""

import asyncio
import os
import platform
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path
from typing import Callable, Awaitable
from urllib.parse import urlparse

import httpx

Emitter = Callable[..., Awaitable[None]]

SYSTEM      = platform.system()   # "Linux" | "Darwin" | "Windows"
_CHUNK      = 65_536              # 64 KB read chunks


# ─────────────────────────────────────────────────────────────────────────────
# Format detection
# ─────────────────────────────────────────────────────────────────────────────

def _detect_fmt(url: str, hint: str | None) -> str:
    """Return the package format string, preferring an explicit hint."""
    if hint:
        return hint.lower()
    p = urlparse(url).path.lower()
    if p.endswith(".tar.gz"):    return "tar.gz"
    if p.endswith(".tar.bz2"):   return "tar.bz2"
    if p.endswith(".appimage"):  return "appimage"
    if "appimage" in p:          return "appimage"
    if p.endswith(".sh"):        return "sh"
    if p.endswith(".run"):       return "run"
    if p.endswith(".deb"):       return "deb"
    if p.endswith(".rpm"):       return "rpm"
    if p.endswith(".dmg"):       return "dmg"
    if p.endswith(".pkg"):       return "pkg"
    if p.endswith(".zip"):       return "zip"
    if p.endswith(".exe"):       return "exe"
    if p.endswith(".msi"):       return "msi"
    # Path-word heuristics for extension-less download URLs
    if "nsis" in p or "windows" in p:   return "exe"
    if "/mac" in p or "darwin" in p:    return "dmg"
    if "/linux" in p:                   return "appimage"
    return "exe"   # safe fallback for Windows-oriented unknown URLs


# ─────────────────────────────────────────────────────────────────────────────
# Download
# ─────────────────────────────────────────────────────────────────────────────

_SUFFIX = {
    "tar.gz": ".tar.gz", "tar.bz2": ".tar.bz2",
    "appimage": ".AppImage", "sh": ".sh", "run": ".run",
    "deb": ".deb", "rpm": ".rpm", "dmg": ".dmg", "pkg": ".pkg",
    "zip": ".zip", "exe": ".exe", "msi": ".msi",
}


async def _download(url: str, fmt: str, name: str, emit: Emitter) -> Path | None:
    """Stream the full installer to a temp file. Returns path or None."""
    suffix = _SUFFIX.get(fmt, ".bin")
    tmp    = Path(tempfile.mktemp(suffix=suffix))

    filename = url.split("/")[-1].split("?")[0] or "installer"
    await emit("INFO", "INSTALLER", f"{name}: Downloading {filename}…", url)

    try:
        async with httpx.AsyncClient(
            timeout=300.0,
            follow_redirects=True,
            headers={"User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0 Safari/537.36"
            )},
        ) as client:
            async with client.stream("GET", url) as resp:
                if resp.status_code not in (200, 206):
                    await emit(
                        "WARN", "INSTALLER",
                        f"{name}: HTTP {resp.status_code} — blocked or geo-restricted",
                        url,
                    )
                    return None

                size = 0
                with open(tmp, "wb") as fh:
                    async for chunk in resp.aiter_bytes(_CHUNK):
                        fh.write(chunk)
                        size += len(chunk)

        await emit(
            "INFO", "INSTALLER",
            f"{name}: Download complete — {size / (1024 * 1024):.1f} MB",
            url,
        )
        return tmp

    except httpx.ConnectError as exc:
        await emit("BLOCKED", "INSTALLER",
                   f"{name}: Blocked by proxy/firewall ({exc})", url)
    except httpx.TimeoutException:
        await emit("BLOCKED", "INSTALLER",
                   f"{name}: Connection timed out — network policy blocking", url)
    except Exception as exc:
        await emit("ERROR", "INSTALLER", f"{name}: Download error — {exc}", url)

    return None


# ─────────────────────────────────────────────────────────────────────────────
# Subprocess helper
# ─────────────────────────────────────────────────────────────────────────────

def _run_sync(cmd: list, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=300, **kw)


async def _run(cmd: list, **kw):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: _run_sync(cmd, **kw))


_ANSI_RE = __import__("re").compile(r"\x1b\[[0-9;]*[mABCDEFGHJKSTfhilmnprsu]")


async def _run_streaming(cmd: list, emit: Emitter, name: str, **kw) -> int:
    """Run a subprocess and emit each stdout/stderr line as it arrives."""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        **kw,
    )

    async def _relay(stream):
        while True:
            line = await stream.readline()
            if not line:
                break
            text = _ANSI_RE.sub("", line.decode(errors="replace")).rstrip()
            if text:
                await emit("INFO", "INSTALLER", f"{name}: {text}")

    await asyncio.gather(_relay(proc.stdout), _relay(proc.stderr))
    await proc.wait()
    return proc.returncode


def _mark_exec(path: Path):
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


# ─────────────────────────────────────────────────────────────────────────────
# Linux installer
# ─────────────────────────────────────────────────────────────────────────────

async def _install_linux(path: Path, fmt: str, name: str, emit: Emitter) -> bool:
    safe = name.replace(" ", "_")

    if fmt == "sh":
        _mark_exec(path)
        await emit("INFO", "INSTALLER", f"{name}: Running install script (may need sudo)…")
        rc = await _run_streaming(["bash", str(path)], emit, name)
        if rc != 0:
            await emit("WARN", "INSTALLER",
                       f"{name}: Installer exited {rc}")
        return rc == 0

    elif fmt == "appimage":
        # Place in ~/.local/bin so it is on PATH via XDG convention
        dest_dir = Path.home() / ".local" / "bin"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"{safe}.AppImage"
        shutil.copy2(path, dest)
        _mark_exec(dest)
        # Create .desktop entry for app menu
        desktop_dir = Path.home() / ".local" / "share" / "applications"
        desktop_dir.mkdir(parents=True, exist_ok=True)
        (desktop_dir / f"{safe}.desktop").write_text(
            f"[Desktop Entry]\nType=Application\nName={name}\n"
            f"Exec={dest} %U\nTerminal=false\nCategories=Network;AI;\n"
        )
        await emit(
            "INFO", "INSTALLER",
            f"{name}: AppImage installed → {dest}  (also added .desktop entry)",
        )
        return True

    elif fmt == "deb":
        await emit("INFO", "INSTALLER", f"{name}: Installing .deb package…")
        r = await _run(["sudo", "apt-get", "install", "-y", str(path)])
        if r.returncode != 0:
            # fallback to dpkg
            r = await _run(["sudo", "dpkg", "-i", str(path)])
            if r.returncode == 0:
                await _run(["sudo", "apt-get", "install", "-f", "-y"])   # fix deps

    elif fmt == "rpm":
        await emit("INFO", "INSTALLER", f"{name}: Installing .rpm package…")
        # Try dnf first, then rpm
        r = await _run(["sudo", "dnf", "install", "-y", str(path)])
        if r.returncode != 0:
            r = await _run(["sudo", "rpm", "-i", "--force", str(path)])

    elif fmt in ("tar.gz", "tar.bz2"):
        dest = Path.home() / ".local" / "share" / safe.lower()
        dest.mkdir(parents=True, exist_ok=True)
        flag = "z" if fmt == "tar.gz" else "j"
        await emit("INFO", "INSTALLER", f"{name}: Extracting archive → {dest}…")
        r = await _run(["tar", f"-x{flag}f", str(path), "-C", str(dest),
                        "--strip-components=1"])
        # Try to find and symlink any executable
        for exe in dest.rglob("*"):
            if exe.is_file() and (exe.stat().st_mode & stat.S_IEXEC):
                link = Path.home() / ".local" / "bin" / exe.name
                if not link.exists():
                    link.symlink_to(exe)
                    await emit("INFO", "INSTALLER",
                               f"{name}: Symlinked {exe.name} → ~/.local/bin/")
                break

    elif fmt == "run":
        _mark_exec(path)
        await emit("INFO", "INSTALLER", f"{name}: Running .run installer…")
        r = await _run([str(path), "--silent", "--noexec", "--target",
                        str(Path.home() / ".local" / "share" / safe.lower())])
        if r.returncode != 0:
            r = await _run([str(path)])

    else:
        _mark_exec(path)
        await emit("WARN", "INSTALLER",
                   f"{name}: Unknown format '{fmt}' — attempting direct execution")
        r = await _run([str(path)])

    ok = r.returncode == 0
    if not ok:
        msg = (r.stderr or r.stdout or "").strip()[:300]
        await emit("WARN", "INSTALLER",
                   f"{name}: Installer exited {r.returncode} — {msg}")
    return ok


# ─────────────────────────────────────────────────────────────────────────────
# macOS installer
# ─────────────────────────────────────────────────────────────────────────────

async def _install_darwin(path: Path, fmt: str, name: str, emit: Emitter) -> bool:

    if fmt == "dmg":
        await emit("INFO", "INSTALLER", f"{name}: Mounting DMG…")
        mount_r = await _run([
            "hdiutil", "attach", str(path),
            "-nobrowse", "-noverify", "-noautoopen",
        ])
        if mount_r.returncode != 0:
            await emit("WARN", "INSTALLER",
                       f"{name}: DMG mount failed — {mount_r.stderr[:200]}")
            return False

        # Parse mount point from hdiutil tab-delimited output
        mount_pt = None
        for line in mount_r.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) >= 3 and "/Volumes/" in parts[-1]:
                mount_pt = Path(parts[-1].strip())
                break
        if not mount_pt or not mount_pt.exists():
            await emit("WARN", "INSTALLER",
                       f"{name}: Cannot find DMG mount point")
            return False

        success = False
        try:
            items = list(mount_pt.iterdir())

            # Prefer .app bundle
            for item in items:
                if item.suffix == ".app":
                    dest = Path("/Applications") / item.name
                    await emit("INFO", "INSTALLER",
                               f"{name}: Copying {item.name} → /Applications…")
                    r = await _run(["cp", "-R", str(item), str(dest)])
                    success = (r.returncode == 0)
                    break
            else:
                # Embedded .pkg inside DMG
                for item in items:
                    if item.suffix == ".pkg":
                        await emit("INFO", "INSTALLER",
                                   f"{name}: Installing embedded .pkg…")
                        r = await _run([
                            "sudo", "installer",
                            "-pkg", str(item), "-target", "/",
                        ])
                        success = (r.returncode == 0)
                        break
                else:
                    await emit("WARN", "INSTALLER",
                               f"{name}: No .app or .pkg found inside DMG")
        finally:
            await _run(["hdiutil", "detach", str(mount_pt), "-force"])

        if not success:
            await emit("WARN", "INSTALLER",
                       f"{name}: DMG installation did not complete")
        return success

    elif fmt == "pkg":
        await emit("INFO", "INSTALLER", f"{name}: Installing .pkg…")
        r = await _run(["sudo", "installer", "-pkg", str(path), "-target", "/"])
        ok = r.returncode == 0
        if not ok:
            await emit("WARN", "INSTALLER",
                       f"{name}: pkg exit {r.returncode} — {r.stderr[:200]}")
        return ok

    elif fmt == "zip":
        await emit("INFO", "INSTALLER", f"{name}: Extracting .zip…")
        tmp_dir = Path(tempfile.mkdtemp())
        r = await _run(["unzip", "-q", str(path), "-d", str(tmp_dir)])
        for app in sorted(tmp_dir.rglob("*.app")):
            dest = Path("/Applications") / app.name
            await emit("INFO", "INSTALLER",
                       f"{name}: Copying {app.name} → /Applications…")
            await _run(["cp", "-R", str(app), str(dest)])
            break
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return r.returncode == 0

    elif fmt == "sh":
        _mark_exec(path)
        await emit("INFO", "INSTALLER", f"{name}: Running install script…")
        rc = await _run_streaming(["bash", str(path)], emit, name)
        if rc != 0:
            await emit("WARN", "INSTALLER", f"{name}: Script exit {rc}")
        return rc == 0

    else:
        await emit("WARN", "INSTALLER",
                   f"{name}: Unknown macOS format '{fmt}'")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Windows installer
# ─────────────────────────────────────────────────────────────────────────────

async def _install_windows(path: Path, fmt: str, name: str, emit: Emitter) -> bool:

    if fmt == "exe":
        await emit("INFO", "INSTALLER",
                   f"{name}: Running silent installer…")
        # Silent flag sets in rough order of popularity
        for flags in [
            ["/S"],                                        # NSIS
            ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"],  # Inno Setup
            ["/silent"],
            ["/quiet", "/norestart"],
            [],                                            # last resort: interactive
        ]:
            r = await _run([str(path)] + flags)
            if r.returncode == 0:
                return True
        await emit("WARN", "INSTALLER",
                   f"{name}: Installer exited non-zero with all silent flags")
        return False

    elif fmt == "msi":
        await emit("INFO", "INSTALLER", f"{name}: Installing MSI package…")
        r = await _run([
            "msiexec", "/i", str(path),
            "/qn", "/norestart", "/l*v",
            str(Path(tempfile.gettempdir()) / f"{name.replace(' ','_')}_install.log"),
        ])
        ok = r.returncode == 0
        if not ok:
            await emit("WARN", "INSTALLER",
                       f"{name}: MSI exit {r.returncode} — {r.stderr[:200]}")
        return ok

    elif fmt == "zip":
        local_app = Path(
            os.environ.get("LOCALAPPDATA",
                           str(Path.home() / "AppData" / "Local"))
        )
        dest = local_app / name.replace(" ", "")
        dest.mkdir(parents=True, exist_ok=True)
        await emit("INFO", "INSTALLER",
                   f"{name}: Extracting .zip → {dest}…")
        r = await _run([
            "powershell", "-NoProfile", "-Command",
            f"Expand-Archive -Path '{path}' -DestinationPath '{dest}' -Force",
        ])
        ok = r.returncode == 0
        if not ok:
            await emit("WARN", "INSTALLER",
                       f"{name}: Extract failed — {r.stderr[:200]}")
        return ok

    else:
        await emit("WARN", "INSTALLER",
                   f"{name}: Unknown Windows format '{fmt}' — attempting direct run")
        r = await _run([str(path)])
        return r.returncode == 0


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────

async def install_app(installer: dict, emit: Emitter) -> dict:
    """Download and silently install an AI application on the current system."""
    url  = (installer.get("urls") or {}).get(SYSTEM)
    name = installer["name"]
    hint = (installer.get("fmt")  or {}).get(SYSTEM)
    fmt  = _detect_fmt(url or "", hint)

    if not url:
        await emit(
            "WARN", "INSTALLER",
            f"{name}: No installer available for {SYSTEM} — skipping",
            name,
        )
        return {"skipped": True, "reason": f"No {SYSTEM} installer"}

    # ── Download ──────────────────────────────────────────────────────────────
    path = await _download(url, fmt, name, emit)
    if path is None:
        return {"success": False, "reason": "download_failed"}

    # ── Install ───────────────────────────────────────────────────────────────
    await emit("INFO", "INSTALLER",
               f"{name}: Installing ({SYSTEM} · {fmt})…")
    success = False
    try:
        if   SYSTEM == "Linux":   success = await _install_linux(path, fmt, name, emit)
        elif SYSTEM == "Darwin":  success = await _install_darwin(path, fmt, name, emit)
        elif SYSTEM == "Windows": success = await _install_windows(path, fmt, name, emit)
        else:
            await emit("WARN", "INSTALLER",
                       f"{name}: Unsupported platform: {SYSTEM}")
    finally:
        try:
            path.unlink(missing_ok=True)
        except Exception:
            pass

    if success:
        await emit(
            "ALERT", "INSTALLER",
            f"INSTALLED: {name} — application installed and ready to use",
            url,
        )
        return {"success": True, "installed": True, "url": url}
    else:
        await emit(
            "ERROR", "INSTALLER",
            f"INSTALL FAILED: {name} — see terminal output for details",
            url,
        )
        return {"success": False, "installed": False, "url": url}
