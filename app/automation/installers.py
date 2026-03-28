"""Installer orchestration with URL resolution, classification, caching, and dedup."""

from __future__ import annotations

import asyncio
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Awaitable, Callable
from urllib.parse import urlparse

import httpx

from app.core.app_catalog import get_app, platform_supported

Emitter = Callable[..., Awaitable[None]]

SYSTEM = platform.system()  # "Linux" | "Darwin" | "Windows"
PLATFORM_KEY = {"Linux": "linux", "Darwin": "darwin", "Windows": "windows"}.get(SYSTEM, "linux")
ARCH_KEY = "arm64" if platform.machine().lower() in ("aarch64", "arm64") else "x64"
_CHUNK = 65_536

STATUS = {
    "INSTALLED_OK": "INSTALLED_OK",
    "ALREADY_INSTALLED": "ALREADY_INSTALLED",
    "URL_INVALID_OR_STALE": "URL_INVALID_OR_STALE",
    "HTTP_404_NOT_FOUND": "HTTP_404_NOT_FOUND",
    "HTTP_403_FORBIDDEN": "HTTP_403_FORBIDDEN",
    "HTTP_451_UNAVAILABLE": "HTTP_451_UNAVAILABLE",
    "DNS_RESOLUTION_FAILED": "DNS_RESOLUTION_FAILED",
    "CONNECTION_FAILED": "CONNECTION_FAILED",
    "PROXY_BLOCKED": "PROXY_BLOCKED",
    "PLATFORM_NOT_SUPPORTED": "PLATFORM_NOT_SUPPORTED",
    "NO_LINUX_BUILD_AVAILABLE": "NO_LINUX_BUILD_AVAILABLE",
    "INSTALLER_STARTED": "INSTALLER_STARTED",
    "INSTALLER_FAILED": "INSTALLER_FAILED",
    "STARTABLE": "STARTABLE",
    "START_FAILED": "START_FAILED",
    "MANUAL_DOWNLOAD_REQUIRED": "MANUAL_DOWNLOAD_REQUIRED",
}

DOWNLOAD_CACHE_DIR = Path("simulator_data/download_cache")
DOWNLOAD_CACHE_DIR.mkdir(parents=True, exist_ok=True)

_URL_CACHE: dict[tuple[str, str, str], dict] = {}
_ARTIFACT_CACHE: dict[str, Path] = {}
_INSTALL_LOCK = asyncio.Lock()
_INFLIGHT_INSTALLS: set[str] = set()

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[mABCDEFGHJKSTfhilmnprsu]")
_DNS_HINTS = (
    "name or service not known",
    "temporary failure in name resolution",
    "no address associated with hostname",
    "nodename nor servname provided",
    "errno -2",
)


def _detect_fmt(url: str, hint: str | None) -> str:
    if hint:
        return hint.lower()
    p = urlparse(url).path.lower()
    if p.endswith(".tar.gz"):
        return "tar.gz"
    if p.endswith(".tar.bz2"):
        return "tar.bz2"
    if p.endswith(".appimage"):
        return "appimage"
    if "appimage" in p:
        return "appimage"
    if p.endswith(".sh"):
        return "sh"
    if p.endswith(".run"):
        return "run"
    if p.endswith(".deb"):
        return "deb"
    if p.endswith(".rpm"):
        return "rpm"
    if p.endswith(".dmg"):
        return "dmg"
    if p.endswith(".pkg"):
        return "pkg"
    if p.endswith(".zip"):
        return "zip"
    if p.endswith(".exe"):
        return "exe"
    if p.endswith(".msi"):
        return "msi"
    if "/linux" in p:
        return "appimage"
    return "bin"


_SUFFIX = {
    "tar.gz": ".tar.gz",
    "tar.bz2": ".tar.bz2",
    "appimage": ".AppImage",
    "sh": ".sh",
    "run": ".run",
    "deb": ".deb",
    "rpm": ".rpm",
    "dmg": ".dmg",
    "pkg": ".pkg",
    "zip": ".zip",
    "exe": ".exe",
    "msi": ".msi",
}


def _normalize(installer: dict) -> dict:
    if "app_id" in installer:
        return dict(installer)

    app_id = installer.get("id", "")
    from_catalog = get_app(app_id)
    if from_catalog:
        return from_catalog

    urls = installer.get("urls") or {}
    fmts = installer.get("fmt") or {}
    platform_url = urls.get(SYSTEM)
    platform_fmt = fmts.get(SYSTEM)
    supported = [PLATFORM_KEY] if platform_url else []
    return {
        "app_id": app_id,
        "display_name": installer.get("name", app_id),
        "desc": installer.get("desc", ""),
        "category": "legacy",
        "supported_platforms": supported,
        "install_type": platform_fmt or _detect_fmt(platform_url or "", None),
        "homepage_url": "",
        "download_url": platform_url,
        "fallback_urls": [],
        "validation_strategy": "binary_version",
        "launch_strategy": "binary",
        "binary_name": app_id,
        "install_dir_hint": "",
        "known_limitations": "",
        "checksum_url": None,
        "release_discovery_strategy": {"type": "stable_endpoint"},
        "launch_type": "binary",
        "launch_command_linux": [app_id],
        "launch_command_windows": [app_id],
        "post_install_validation_command": [app_id, "--version"],
        "requires_terminal": False,
        "requires_service": False,
        "requires_elevated_permissions": False,
    }


def _status_from_http(status_code: int) -> str:
    if status_code == 404:
        return STATUS["HTTP_404_NOT_FOUND"]
    if status_code == 403:
        return STATUS["HTTP_403_FORBIDDEN"]
    if status_code == 451:
        return STATUS["HTTP_451_UNAVAILABLE"]
    if status_code == 407:
        return STATUS["PROXY_BLOCKED"]
    if status_code >= 400:
        return STATUS["URL_INVALID_OR_STALE"]
    return STATUS["INSTALLED_OK"]


def classify_network_error(exc: Exception) -> str:
    text = str(exc).lower()
    if any(h in text for h in _DNS_HINTS):
        return STATUS["DNS_RESOLUTION_FAILED"]
    if "proxy" in text or "407" in text:
        return STATUS["PROXY_BLOCKED"]
    if isinstance(exc, httpx.ConnectError):
        return STATUS["CONNECTION_FAILED"]
    if isinstance(exc, httpx.TimeoutException):
        return STATUS["CONNECTION_FAILED"]
    return STATUS["CONNECTION_FAILED"]


async def _run(cmd: list[str], **kw):
    loop = asyncio.get_event_loop()

    def _sync_run():
        return subprocess.run(cmd, capture_output=True, text=True, timeout=300, **kw)

    return await loop.run_in_executor(None, _sync_run)


async def _run_streaming(cmd: list[str], emit: Emitter, name: str, **kw) -> int:
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


def _binary_exists(app: dict) -> tuple[bool, str]:
    binary_name = app.get("binary_name") or app.get("app_id")
    if not binary_name:
        return False, ""

    # Direct path if already tracked
    if os.path.isabs(binary_name) and Path(binary_name).exists():
        return True, binary_name

    found = shutil.which(binary_name)
    if found:
        return True, found

    # AppImage fallback naming convention
    candidate = Path.home() / ".local" / "bin" / f"{app.get('display_name', binary_name).replace(' ', '_')}.AppImage"
    if candidate.exists():
        return True, str(candidate)

    return False, ""


async def _detect_version(app: dict, binary_path: str) -> str:
    cmd = app.get("post_install_validation_command") or []
    if not cmd and binary_path:
        cmd = [binary_path, "--version"]
    if cmd and binary_path and cmd[0] == app.get("binary_name"):
        cmd = [binary_path] + cmd[1:]
    if not cmd:
        return ""
    try:
        res = await _run(cmd)
        out = (res.stdout or res.stderr or "").strip().splitlines()
        return out[0][:120] if out else ""
    except Exception:
        return ""


async def _ollama_health() -> tuple[bool, str]:
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get("http://127.0.0.1:11434/api/tags")
            if resp.status_code == 200:
                return True, "Ollama API healthy"
    except Exception as exc:
        return False, str(exc)
    return False, "Ollama API unavailable"


async def preflight_install_state(app: dict) -> dict:
    installed, binary_path = _binary_exists(app)
    version = ""
    if installed:
        version = await _detect_version(app, binary_path)

    healthy = None
    if app.get("app_id") == "ollama" and installed:
        healthy, _ = await _ollama_health()

    return {
        "installed": installed,
        "binary_path": binary_path,
        "version": version,
        "healthy": healthy,
    }


async def _resolve_github_asset(app: dict, platform_key: str, arch_key: str) -> dict:
    strategy = app.get("release_discovery_strategy") or {}
    repo = strategy.get("repo")
    if not repo:
        return {
            "ok": False,
            "classification": STATUS["URL_INVALID_OR_STALE"],
            "message": "GitHub strategy missing repo",
        }

    api_url = f"https://api.github.com/repos/{repo}/releases/latest"
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        resp = await client.get(api_url)
    if resp.status_code != 200:
        return {
            "ok": False,
            "classification": _status_from_http(resp.status_code),
            "message": f"GitHub API status {resp.status_code}",
            "http_status": resp.status_code,
            "resolved_url": api_url,
        }

    data = resp.json()
    assets = data.get("assets", [])
    pats = (strategy.get("asset_patterns") or {}).get(platform_key) or []

    def _score(name: str) -> int:
        n = name.lower()
        score = 0
        if arch_key in n:
            score += 10
        if platform_key in n:
            score += 5
        return score

    matches: list[dict] = []
    for asset in assets:
        name = asset.get("name", "")
        if any(re.search(pat, name) for pat in pats):
            matches.append(asset)

    if not matches:
        return {
            "ok": False,
            "classification": STATUS["URL_INVALID_OR_STALE"],
            "message": f"No release asset matched {platform_key}/{arch_key}",
            "resolved_url": data.get("html_url", api_url),
        }

    chosen = sorted(matches, key=lambda a: _score(a.get("name", "")), reverse=True)[0]
    return {
        "ok": True,
        "resolved_url": chosen.get("browser_download_url"),
        "release_page": data.get("html_url"),
        "version": data.get("tag_name", ""),
        "fallback_used": None,
    }


async def _head_validate(url: str) -> dict:
    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            resp = await client.head(url)
        if resp.status_code in (405,):
            async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
                resp = await client.get(url, headers={"Range": "bytes=0-0"})

        if resp.status_code >= 400:
            return {
                "ok": False,
                "classification": _status_from_http(resp.status_code),
                "http_status": resp.status_code,
                "resolved_url": str(resp.url),
            }

        return {
            "ok": True,
            "classification": STATUS["INSTALLED_OK"],
            "http_status": resp.status_code,
            "resolved_url": str(resp.url),
            "content_length": resp.headers.get("content-length"),
            "etag": resp.headers.get("etag"),
            "last_modified": resp.headers.get("last-modified"),
        }
    except Exception as exc:
        return {
            "ok": False,
            "classification": classify_network_error(exc),
            "message": str(exc),
            "resolved_url": url,
        }


async def resolve_download_url(app: dict, platform_key: str = PLATFORM_KEY, arch_key: str = ARCH_KEY) -> dict:
    cache_key = (app["app_id"], platform_key, arch_key)
    if cache_key in _URL_CACHE:
        return dict(_URL_CACHE[cache_key])

    if not platform_supported(app, SYSTEM):
        classification = STATUS["NO_LINUX_BUILD_AVAILABLE"] if SYSTEM == "Linux" else STATUS["PLATFORM_NOT_SUPPORTED"]
        out = {
            "ok": False,
            "classification": classification,
            "resolved_url": "",
            "message": f"{app['display_name']} is not available on {SYSTEM}",
        }
        _URL_CACHE[cache_key] = out
        return dict(out)

    strategy = (app.get("release_discovery_strategy") or {}).get("type", "stable_endpoint")
    candidate_urls: list[str] = []
    fallback_used = None

    try:
        if strategy == "github_latest_asset":
            github_res = await _resolve_github_asset(app, platform_key, arch_key)
            if github_res.get("ok"):
                candidate_urls.append(github_res["resolved_url"])
                release_page = github_res.get("release_page")
                if release_page:
                    candidate_urls.append(release_page)
            else:
                fallback_used = "github_release_api"
        elif strategy == "pypi_package":
            package = (app.get("release_discovery_strategy") or {}).get("package")
            if package:
                candidate_urls.append(f"https://pypi.org/pypi/{package}/json")

        # Platform-specific override first.
        platform_url = app.get(f"{platform_key}_download")
        if platform_url:
            candidate_urls.insert(0, platform_url)

        if app.get("download_url"):
            candidate_urls.append(app["download_url"])
        candidate_urls.extend(app.get("fallback_urls") or [])

        # De-duplicate while preserving order.
        seen = set()
        unique_candidates = []
        for item in candidate_urls:
            if not item or item in seen:
                continue
            seen.add(item)
            unique_candidates.append(item)

        for idx, candidate in enumerate(unique_candidates):
            check = await _head_validate(candidate)
            if check.get("ok"):
                out = {
                    "ok": True,
                    "classification": STATUS["INSTALLED_OK"],
                    "resolved_url": check.get("resolved_url") or candidate,
                    "http_status": check.get("http_status"),
                    "fallback_used": fallback_used if idx == 0 else unique_candidates[idx - 1],
                    "content_length": check.get("content_length"),
                    "etag": check.get("etag"),
                    "last_modified": check.get("last_modified"),
                }
                _URL_CACHE[cache_key] = out
                return dict(out)

            last_error = {
                "ok": False,
                "classification": check.get("classification", STATUS["URL_INVALID_OR_STALE"]),
                "resolved_url": check.get("resolved_url", candidate),
                "http_status": check.get("http_status"),
                "fallback_used": candidate,
                "message": check.get("message", "URL check failed"),
            }

        _URL_CACHE[cache_key] = last_error
        return dict(last_error)
    except Exception as exc:
        out = {
            "ok": False,
            "classification": classify_network_error(exc),
            "message": str(exc),
            "resolved_url": "",
        }
        _URL_CACHE[cache_key] = out
        return dict(out)


def _artifact_meta_path(path: Path) -> Path:
    return path.with_suffix(path.suffix + ".meta.json")


def _safe_name(app_id: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]", "_", app_id)


async def _download_to_cache(app: dict, resolved: dict, emit: Emitter) -> dict:
    url = resolved.get("resolved_url")
    if not url:
        return {"ok": False, "classification": STATUS["URL_INVALID_OR_STALE"]}

    fmt = _detect_fmt(url, app.get(f"{PLATFORM_KEY}_install_type") or app.get("install_type"))
    suffix = _SUFFIX.get(fmt, ".bin")
    cache_path = DOWNLOAD_CACHE_DIR / f"{_safe_name(app['app_id'])}{suffix}"
    meta_path = _artifact_meta_path(cache_path)

    expected_len = resolved.get("content_length")
    if cache_path.exists() and meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text())
            if meta.get("resolved_url") == url:
                if expected_len is None or str(cache_path.stat().st_size) == str(expected_len):
                    _ARTIFACT_CACHE[url] = cache_path
                    await emit("INFO", "INSTALLER", f"{app['display_name']}: Reusing cached installer", url, classification="CACHED_ARTIFACT_REUSED")
                    return {
                        "ok": True,
                        "classification": "CACHED_ARTIFACT_REUSED",
                        "path": cache_path,
                        "fmt": fmt,
                    }
        except Exception:
            pass

    await emit("INFO", "INSTALLER", f"{app['display_name']}: Downloading installer", url, classification="DOWNLOAD_STARTED")
    try:
        async with httpx.AsyncClient(timeout=300.0, follow_redirects=True) as client:
            async with client.stream("GET", url) as resp:
                if resp.status_code >= 400:
                    return {
                        "ok": False,
                        "classification": _status_from_http(resp.status_code),
                        "http_status": resp.status_code,
                        "resolved_url": str(resp.url),
                    }

                size = 0
                with open(cache_path, "wb") as fh:
                    async for chunk in resp.aiter_bytes(_CHUNK):
                        fh.write(chunk)
                        size += len(chunk)

        meta_path.write_text(json.dumps({
            "resolved_url": url,
            "size": cache_path.stat().st_size,
            "etag": resolved.get("etag"),
            "last_modified": resolved.get("last_modified"),
        }, indent=2))
        _ARTIFACT_CACHE[url] = cache_path
        await emit("INFO", "INSTALLER", f"{app['display_name']}: Download complete ({size / (1024 * 1024):.1f} MB)", url, classification="DOWNLOADED")
        return {
            "ok": True,
            "classification": "DOWNLOADED",
            "path": cache_path,
            "fmt": fmt,
            "resolved_url": url,
        }
    except Exception as exc:
        return {
            "ok": False,
            "classification": classify_network_error(exc),
            "message": str(exc),
            "resolved_url": url,
        }


async def _install_linux(path: Path, fmt: str, app: dict, emit: Emitter) -> tuple[bool, str]:
    name = app["display_name"]
    safe = name.replace(" ", "_")

    if fmt == "sh":
        _mark_exec(path)
        rc = await _run_streaming(["bash", str(path)], emit, name)
        return rc == 0, ""

    if fmt == "appimage":
        dest_dir = Path.home() / ".local" / "bin"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"{safe}.AppImage"
        shutil.copy2(path, dest)
        _mark_exec(dest)
        desktop_dir = Path.home() / ".local" / "share" / "applications"
        desktop_dir.mkdir(parents=True, exist_ok=True)
        (desktop_dir / f"{safe}.desktop").write_text(
            "[Desktop Entry]\n"
            "Type=Application\n"
            f"Name={name}\n"
            f"Exec={dest} %U\n"
            "Terminal=false\n"
            "Categories=Network;AI;\n"
        )
        return True, str(dest)

    if fmt == "deb":
        r = await _run(["sudo", "apt-get", "install", "-y", str(path)])
        if r.returncode != 0:
            r = await _run(["sudo", "dpkg", "-i", str(path)])
            if r.returncode == 0:
                await _run(["sudo", "apt-get", "install", "-f", "-y"])
        return r.returncode == 0, ""

    if fmt in ("tar.gz", "tar.bz2"):
        dest = Path.home() / ".local" / "share" / safe.lower()
        dest.mkdir(parents=True, exist_ok=True)
        flag = "z" if fmt == "tar.gz" else "j"
        r = await _run(["tar", f"-x{flag}f", str(path), "-C", str(dest), "--strip-components=1"])
        if r.returncode != 0:
            return False, ""
        for exe in dest.rglob("*"):
            if exe.is_file() and (exe.stat().st_mode & stat.S_IEXEC):
                link_dir = Path.home() / ".local" / "bin"
                link_dir.mkdir(parents=True, exist_ok=True)
                link = link_dir / exe.name
                if not link.exists():
                    link.symlink_to(exe)
                return True, str(link)
        return True, str(dest)

    if fmt == "run":
        _mark_exec(path)
        r = await _run([str(path), "--silent"])
        if r.returncode != 0:
            r = await _run([str(path)])
        return r.returncode == 0, ""

    # Fallback direct execution
    _mark_exec(path)
    r = await _run([str(path)])
    return r.returncode == 0, ""


async def _install_darwin(path: Path, fmt: str, app: dict, emit: Emitter) -> tuple[bool, str]:
    # Keep behavior minimal and safe for CI/non-mac hosts.
    if fmt == "zip":
        tmp_dir = Path(tempfile.mkdtemp())
        r = await _run(["unzip", "-q", str(path), "-d", str(tmp_dir)])
        return r.returncode == 0, str(tmp_dir)
    if fmt in ("dmg", "pkg", "sh", "exe"):
        return False, ""
    return False, ""


async def _install_windows(path: Path, fmt: str, app: dict, emit: Emitter) -> tuple[bool, str]:
    if fmt == "exe":
        for flags in (["/S"], ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"], []):
            r = await _run([str(path)] + flags)
            if r.returncode == 0:
                return True, ""
        return False, ""
    if fmt == "msi":
        r = await _run(["msiexec", "/i", str(path), "/qn", "/norestart"])
        return r.returncode == 0, ""
    return False, ""


async def _install_artifact(path: Path, fmt: str, app: dict, emit: Emitter) -> tuple[bool, str]:
    if SYSTEM == "Linux":
        return await _install_linux(path, fmt, app, emit)
    if SYSTEM == "Darwin":
        return await _install_darwin(path, fmt, app, emit)
    if SYSTEM == "Windows":
        return await _install_windows(path, fmt, app, emit)
    return False, ""


async def validate_install(app: dict) -> dict:
    pre = await preflight_install_state(app)
    if not pre["installed"]:
        return {
            "ok": False,
            "classification": STATUS["START_FAILED"],
            "installed": False,
            "binary_path": "",
            "version": "",
        }
    return {
        "ok": True,
        "classification": STATUS["STARTABLE"],
        "installed": True,
        "binary_path": pre["binary_path"],
        "version": pre.get("version", ""),
    }


async def install_app(installer: dict, emit: Emitter, reinstall: bool = False) -> dict:
    app = _normalize(installer)
    app_id = app["app_id"]
    name = app["display_name"]

    async with _INSTALL_LOCK:
        if app_id in _INFLIGHT_INSTALLS:
            return {
                "app_id": app_id,
                "installed": False,
                "classification": "INSTALL_SKIPPED_DUPLICATE_IN_FLIGHT",
                "message": "Install already running for this app",
                "startable": False,
            }
        _INFLIGHT_INSTALLS.add(app_id)

    try:
        supported = platform_supported(app, SYSTEM)
        if not supported:
            classification = STATUS["NO_LINUX_BUILD_AVAILABLE"] if SYSTEM == "Linux" else STATUS["PLATFORM_NOT_SUPPORTED"]
            await emit("WARN", "INSTALLER", f"{name}: Unsupported on {SYSTEM}", app_id, classification=classification)
            return {
                "app_id": app_id,
                "installed": False,
                "classification": classification,
                "message": f"No installer available for {SYSTEM}",
                "startable": False,
            }

        pre = await preflight_install_state(app)
        if pre["installed"] and not reinstall:
            await emit("SUCCESS", "INSTALLER", f"{name}: Already installed, skipping reinstall", app_id, classification=STATUS["ALREADY_INSTALLED"], binary_path=pre["binary_path"], version=pre.get("version", ""))
            return {
                "app_id": app_id,
                "installed": True,
                "classification": STATUS["ALREADY_INSTALLED"],
                "message": "Already installed",
                "binary_path": pre["binary_path"],
                "version": pre.get("version", ""),
                "startable": True,
                "resolved_url": "",
                "fallback_url_used": None,
                "http_status": None,
                "dns_status": "ok",
            }

        install_type = (app.get(f"{PLATFORM_KEY}_install_type") or app.get("install_type") or "").lower()
        if install_type == "manual":
            await emit(
                "WARN",
                "INSTALLER",
                f"{name}: Manual download required on this platform",
                app_id,
                classification=STATUS["MANUAL_DOWNLOAD_REQUIRED"],
                remediation_hint="Use homepage_url for manual installation steps",
            )
            return {
                "app_id": app_id,
                "installed": False,
                "classification": STATUS["MANUAL_DOWNLOAD_REQUIRED"],
                "message": "Manual installation required",
                "resolved_url": app.get("homepage_url", ""),
                "startable": False,
            }

        if install_type == "pip":
            package_name = (app.get("release_discovery_strategy") or {}).get("package") or app.get("binary_name") or app_id
            await emit("INFO", "INSTALLER", f"{name}: Installing via pip ({package_name})", app_id, classification=STATUS["INSTALLER_STARTED"])
            run = await _run([sys.executable, "-m", "pip", "install", "-U", package_name])
            if run.returncode != 0:
                await emit("ERROR", "INSTALLER", f"{name}: pip install failed", app_id, classification=STATUS["INSTALLER_FAILED"], remediation_hint=(run.stderr or run.stdout or "")[:200])
                return {
                    "app_id": app_id,
                    "installed": False,
                    "classification": STATUS["INSTALLER_FAILED"],
                    "message": "pip install failed",
                    "startable": False,
                }

            validated = await validate_install(app)
            await emit("ALERT", "INSTALLER", f"INSTALLED: {name}", app_id, classification=STATUS["INSTALLED_OK"], binary_path=validated.get("binary_path", ""), version=validated.get("version", ""), validation_state="Validated" if validated.get("ok") else "Installed")
            return {
                "app_id": app_id,
                "installed": True,
                "classification": STATUS["INSTALLED_OK"],
                "message": "Installed successfully",
                "resolved_url": f"pip://{package_name}",
                "binary_path": validated.get("binary_path", ""),
                "version": validated.get("version", ""),
                "startable": True,
            }

        resolved = await resolve_download_url(app)
        if not resolved.get("ok"):
            await emit("WARN", "INSTALLER", f"{name}: URL resolution failed ({resolved.get('classification')})", app_id, classification=resolved.get("classification"), resolved_url=resolved.get("resolved_url", ""), http_status=resolved.get("http_status"), remediation_hint="Check app catalog URL strategy and fallback URLs")
            return {
                "app_id": app_id,
                "installed": False,
                "classification": resolved.get("classification"),
                "message": resolved.get("message", "URL resolution failed"),
                "resolved_url": resolved.get("resolved_url", ""),
                "fallback_url_used": resolved.get("fallback_used"),
                "http_status": resolved.get("http_status"),
                "dns_status": "failed" if resolved.get("classification") == STATUS["DNS_RESOLUTION_FAILED"] else "unknown",
                "startable": False,
            }

        await emit("INFO", "INSTALLER", f"{name}: Installer started", app_id, classification=STATUS["INSTALLER_STARTED"], resolved_url=resolved.get("resolved_url"), fallback_url_used=resolved.get("fallback_used"), http_status=resolved.get("http_status"))
        artifact = await _download_to_cache(app, resolved, emit)
        if not artifact.get("ok"):
            await emit("WARN", "INSTALLER", f"{name}: Download failed ({artifact.get('classification')})", app_id, classification=artifact.get("classification"), resolved_url=artifact.get("resolved_url", resolved.get("resolved_url")), http_status=artifact.get("http_status"), remediation_hint="Try fallback URL or update app catalog")
            return {
                "app_id": app_id,
                "installed": False,
                "classification": artifact.get("classification", STATUS["INSTALLER_FAILED"]),
                "message": artifact.get("message", "Download failed"),
                "resolved_url": artifact.get("resolved_url", resolved.get("resolved_url")),
                "fallback_url_used": resolved.get("fallback_used"),
                "http_status": artifact.get("http_status", resolved.get("http_status")),
                "dns_status": "failed" if artifact.get("classification") == STATUS["DNS_RESOLUTION_FAILED"] else "ok",
                "startable": False,
            }

        ok, installed_path = await _install_artifact(artifact["path"], artifact["fmt"], app, emit)
        if not ok:
            await emit("ERROR", "INSTALLER", f"{name}: Installer failed", app_id, classification=STATUS["INSTALLER_FAILED"], resolved_url=resolved.get("resolved_url"), remediation_hint="Review installer output and package format")
            return {
                "app_id": app_id,
                "installed": False,
                "classification": STATUS["INSTALLER_FAILED"],
                "message": "Installer execution failed",
                "resolved_url": resolved.get("resolved_url"),
                "fallback_url_used": resolved.get("fallback_used"),
                "http_status": resolved.get("http_status"),
                "startable": False,
            }

        validated = await validate_install(app)
        final_binary = validated.get("binary_path") or pre.get("binary_path")
        version = validated.get("version") or pre.get("version", "")

        await emit("ALERT", "INSTALLER", f"INSTALLED: {name}", app_id, classification=STATUS["INSTALLED_OK"], resolved_url=resolved.get("resolved_url"), fallback_url_used=resolved.get("fallback_used"), http_status=resolved.get("http_status"), installed_path=installed_path, binary_path=final_binary, version=version, validation_state="Validated" if validated.get("ok") else "Installed")
        return {
            "app_id": app_id,
            "installed": True,
            "classification": STATUS["INSTALLED_OK"],
            "message": "Installed successfully",
            "resolved_url": resolved.get("resolved_url"),
            "fallback_url_used": resolved.get("fallback_used"),
            "http_status": resolved.get("http_status"),
            "dns_status": "ok",
            "installed_path": installed_path,
            "binary_path": final_binary,
            "version": version,
            "startable": True,
        }
    finally:
        async with _INSTALL_LOCK:
            _INFLIGHT_INSTALLS.discard(app_id)


async def install_group(group: list[dict], emit: Emitter, label: str, reinstall: bool = False, max_concurrent_downloads: int = 3) -> list[dict]:
    # Phase 1: normalize and de-duplicate IDs.
    unique_apps: list[dict] = []
    seen: set[str] = set()
    for installer in group:
        app = _normalize(installer)
        if app["app_id"] in seen:
            continue
        seen.add(app["app_id"])
        unique_apps.append(app)

    await emit("INFO", "INSTALLER", f"{label}: resolving URLs for {len(unique_apps)} apps")

    # Phase 2: resolve URLs.
    resolution: dict[str, dict] = {}
    for app in unique_apps:
        install_type = (app.get(f"{PLATFORM_KEY}_install_type") or app.get("install_type") or "").lower()
        if install_type in ("manual", "pip"):
            resolution[app["app_id"]] = {"ok": True, "skip_download": True}
        else:
            resolution[app["app_id"]] = await resolve_download_url(app)

    # Phase 3: download in parallel with cap.
    sem = asyncio.Semaphore(max_concurrent_downloads)
    downloads: dict[str, dict] = {}

    async def _dl(app: dict):
        async with sem:
            res = resolution.get(app["app_id"], {})
            if not res.get("ok"):
                downloads[app["app_id"]] = {"ok": False, "classification": res.get("classification")}
                return
            if res.get("skip_download"):
                downloads[app["app_id"]] = {"ok": True, "skip_download": True}
                return
            downloads[app["app_id"]] = await _download_to_cache(app, res, emit)

    await emit("INFO", "INSTALLER", f"{label}: downloading installers (max {max_concurrent_downloads} concurrent)")
    await asyncio.gather(*[_dl(a) for a in unique_apps])

    # Phase 4: install sequentially.
    await emit("INFO", "INSTALLER", f"{label}: installing sequentially")
    results: list[dict] = []
    for app in unique_apps:
        app_id = app["app_id"]
        pre = await preflight_install_state(app)
        install_type = (app.get(f"{PLATFORM_KEY}_install_type") or app.get("install_type") or "").lower()
        if pre["installed"] and not reinstall:
            results.append({
                "app_id": app_id,
                "installed": True,
                "classification": STATUS["ALREADY_INSTALLED"],
                "message": "Already installed",
                "binary_path": pre.get("binary_path", ""),
                "version": pre.get("version", ""),
                "startable": True,
            })
            continue

        if install_type == "manual":
            results.append({
                "app_id": app_id,
                "installed": False,
                "classification": STATUS["MANUAL_DOWNLOAD_REQUIRED"],
                "message": "Manual installation required",
                "resolved_url": app.get("homepage_url", ""),
                "startable": False,
            })
            continue

        if install_type == "pip":
            package_name = (app.get("release_discovery_strategy") or {}).get("package") or app.get("binary_name") or app_id
            run = await _run([sys.executable, "-m", "pip", "install", "-U", package_name])
            if run.returncode != 0:
                results.append({
                    "app_id": app_id,
                    "installed": False,
                    "classification": STATUS["INSTALLER_FAILED"],
                    "message": "pip install failed",
                    "startable": False,
                })
                continue

            validated = await validate_install(app)
            results.append({
                "app_id": app_id,
                "installed": True,
                "classification": STATUS["INSTALLED_OK"],
                "message": "Installed successfully",
                "resolved_url": f"pip://{package_name}",
                "binary_path": validated.get("binary_path", ""),
                "version": validated.get("version", ""),
                "startable": validated.get("ok", False),
            })
            continue

        dl = downloads.get(app_id, {})
        resolved = resolution.get(app_id, {})
        if not dl.get("ok"):
            results.append({
                "app_id": app_id,
                "installed": False,
                "classification": dl.get("classification") or resolved.get("classification", STATUS["URL_INVALID_OR_STALE"]),
                "message": "Download/resolve failed",
                "resolved_url": resolved.get("resolved_url", ""),
                "startable": False,
            })
            continue

        ok, installed_path = await _install_artifact(dl["path"], dl["fmt"], app, emit)
        if not ok:
            results.append({
                "app_id": app_id,
                "installed": False,
                "classification": STATUS["INSTALLER_FAILED"],
                "message": "Installer execution failed",
                "resolved_url": resolved.get("resolved_url", ""),
                "startable": False,
            })
            continue

        validated = await validate_install(app)
        results.append({
            "app_id": app_id,
            "installed": True,
            "classification": STATUS["INSTALLED_OK"],
            "message": "Installed successfully",
            "resolved_url": resolved.get("resolved_url", ""),
            "installed_path": installed_path,
            "binary_path": validated.get("binary_path", ""),
            "version": validated.get("version", ""),
            "startable": validated.get("ok", False),
        })

    await emit("INFO", "INSTALLER", f"{label}: group install complete")
    return results
