#!/usr/bin/env python3
"""GitHub Release Downloader Py - interactive GitHub release asset downloader."""
from __future__ import annotations

import concurrent.futures as futures
import ctypes
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# All runtime functionality uses Python's standard library only.

APP_NAME = "GitHub-Release-Downloader-Py"
API = "https://api.github.com"
USER_AGENT = f"{APP_NAME}/1.3.4"
CHUNK_SIZE = 1024 * 1024

# ---------------------------------------------------------------------------
# USER CONFIGURATION: sources and default download behavior.
# Edit this repository list and the USER SETTINGS block immediately below.
# channel: "Stable" or "Pre-release"
# ---------------------------------------------------------------------------
REPOSITORIES = [
    {"owner": "ggml-org", "name": "llama.cpp", "channel": "Pre-release"},
    {"owner": "earendil-works", "name": "pi", "channel": "Stable"},
    {"owner": "anomalyco", "name": "opencode", "channel": "Stable"},
    {"owner": "can1357", "name": "oh-my-pi", "channel": "Stable"},
    {"owner": "storytold", "name": "photocraft", "channel": "Stable"},
    {"owner": "storytold", "name": "lightcraft", "channel": "Stable"},
    {"owner": "storytold", "name": "filmcraft", "channel": "Stable"},
    {"owner": "storytold", "name": "effectcraft", "channel": "Stable"},
    {"owner": "storytold", "name": "soundcraft", "channel": "Stable"},
    {"owner": "storytold", "name": "designcraft", "channel": "Stable"},
    {"owner": "storytold", "name": "vectorcraft", "channel": "Stable"},
    {"owner": "storytold", "name": "pdfcraft", "channel": "Stable"},
    {"owner": "storytold", "name": "wordcraft", "channel": "Stable"},
    {"owner": "storytold", "name": "gridcraft", "channel": "Stable"},
    {"owner": "storytold", "name": "deckcraft", "channel": "Stable"},
    {"owner": "storytold", "name": "cadcraft", "channel": "Stable"},
    {"owner": "Comfy-Org", "name": "ComfyUI", "channel": "Stable"},
]

# ---------------------------------------------------------------------------
# USER SETTINGS — edit this block to change the default behavior.
# True/False values control download options; the exclusion list can be toggled at startup.
# ---------------------------------------------------------------------------
DEFAULT_EXCLUSIONS = ["arm64", "aarch64", "riscv", "darwin", ".dmg"]
DEFAULT_INCLUDES: list[str] = []       # [] = do not restrict by include keywords
APPLY_DEFAULT_EXCLUSIONS = True
DOWNLOAD_MSI = True
DOWNLOAD_SOURCE_ZIP = True
DOWNLOAD_README = True
DEFAULT_MAX_WORKERS = 2                 # simultaneous files per repository
DEFAULT_THREADS_PER_FILE = 2            # parallel HTTP ranges for each file
DEFAULT_RETRIES = 2                     # total attempts for each file/part
DEFAULT_ERROR_MODE = 3                  # 1=skip; 2=ask; 3=retry then skip
DEFAULT_CONNECTION_TIMEOUT = 30

# ANSI colors are enabled automatically in interactive terminals. Set NO_COLOR=1
# in the environment to disable them.
USE_ANSI_COLORS = True

# Change REPOSITORIES above to configure the sources and release channels.

_console_lock = threading.RLock()


def say(message: str = "") -> None:
    with _console_lock:
        print(message, flush=True)


def prompt_int(message: str, default: int, minimum: int = 1, maximum: int = 64) -> int:
    while True:
        raw = input(f"{message} [{default}]: ").strip()
        if not raw:
            return default
        try:
            value = int(raw)
            if minimum <= value <= maximum:
                return value
        except ValueError:
            pass
        say(f"Enter a whole number from {minimum} to {maximum}.")


def get_token() -> str | None:
    token = os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN")
    if token and token.strip():
        return token.strip()
    gh = shutil.which("gh")
    if gh:
        try:
            result = subprocess.run([gh, "auth", "token", "--hostname", "github.com"],
                                    capture_output=True, text=True, timeout=10, check=True)
            if result.stdout.strip():
                return result.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            pass
    return None


TOKEN = get_token()
API_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}
if TOKEN:
    API_HEADERS["Authorization"] = f"Bearer {TOKEN}"


def redact(value: str) -> str:
    value = re.sub(r"(?i)(https?://[^\s?]+)\?[^\s]+", r"\1?[query redacted]", value)
    value = re.sub(r"(?i)(Authorization\s*:\s*Bearer\s+)\S+", r"\1[redacted]", value)
    return value


ROOT = Path(__file__).resolve().parent
LOG_PATH = ROOT / "GitHub-Release-Downloader.log"
logging.basicConfig(filename=LOG_PATH, level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s", encoding="utf-8")


def log(level: str, message: str) -> None:
    safe = redact(message)
    getattr(logging, level.lower())(safe)


def request_json(url: str) -> Any:
    request = urllib.request.Request(url, headers=API_HEADERS)
    try:
        with urllib.request.urlopen(request, timeout=DEFAULT_CONNECTION_TIMEOUT) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            payload = json.loads(exc.read().decode("utf-8", "replace"))
            body = payload.get("message", "")
        except Exception:
            pass
        remaining = exc.headers.get("X-RateLimit-Remaining")
        reset = exc.headers.get("X-RateLimit-Reset")
        detail = f"HTTP {exc.code} {exc.reason}: {body}".strip()
        if remaining == "0" and reset:
            detail += f"; rate limit reset epoch: {reset}"
        raise RuntimeError(f"GitHub API request failed: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"GitHub API request failed: {exc}") from exc


def get_release(owner: str, repo: str, channel: str, tag: str | None = None) -> dict | None:
    base = f"{API}/repos/{urllib.parse.quote(owner)}/{urllib.parse.quote(repo)}"
    if tag is not None:
        encoded = urllib.parse.quote(tag, safe="")
        release = request_json(f"{base}/releases/tags/{encoded}")
        if release.get("draft"):
            raise RuntimeError("The requested release is a draft and cannot be downloaded.")
        return release
    if channel == "Stable":
        try:
            release = request_json(f"{base}/releases/latest")
            return release if not release.get("draft") and not release.get("prerelease") else None
        except RuntimeError as exc:
            if "HTTP 404" in str(exc):
                return None
            raise
    for page in range(1, 11):
        releases = request_json(f"{base}/releases?per_page=100&page={page}")
        if not releases:
            break
        for item in releases:
            if item.get("draft") is False and item.get("prerelease") is True and item.get("tag_name"):
                return item
    return None


def parse_release_url(url: str) -> tuple[str, str, str]:
    parsed = urllib.parse.urlparse(url.strip())
    if parsed.scheme != "https" or parsed.hostname not in ("github.com", "www.github.com"):
        raise ValueError("Only https://github.com/OWNER/REPOSITORY/releases/tag/TAG URLs are supported.")
    match = re.fullmatch(r"/([^/]+)/([^/]+)/releases/tag/(.+?)/?", urllib.parse.unquote(parsed.path))
    if not match:
        raise ValueError("Expected: https://github.com/OWNER/REPOSITORY/releases/tag/TAG")
    owner, repo, tag = match.groups()
    return owner, repo.removesuffix(".git"), tag


def select_repositories() -> list[dict] | None:
    selected: set[int] = set()
    while True:
        say("\n========== Select GitHub repositories ==========")
        for i, repo in enumerate(REPOSITORIES, 1):
            mark = "x" if i - 1 in selected else " "
            say(f" [{mark}] {i}. {repo['owner']}/{repo['name']} ({repo['channel']})")
        say("Enter numbers/ranges (1, 2, 5-8); prefix with - to remove (-3). A=all, N=clear, Enter=confirm, Q=quit.")
        raw = input("Selection: ").strip()
        if raw.lower() in ("q", "quit"):
            return None
        if raw.lower() in ("a", "all"):
            selected = set(range(len(REPOSITORIES)))
            continue
        if raw.lower() in ("n", "none", "clear"):
            selected.clear()
            continue
        if not raw:
            if selected:
                return [REPOSITORIES[i] for i in sorted(selected)]
            say("Nothing selected.")
            continue
        tokens = re.split(r"[,;\s]+", raw)
        parsed: list[tuple[bool, list[int]]] = []
        valid = True
        for token in filter(None, tokens):
            m = re.fullmatch(r"([-!]?)((?:\d+))(?:-(\d+))?", token)
            if not m:
                valid = False
                break
            start, end = int(m.group(2)), int(m.group(3) or m.group(2))
            if start < 1 or end > len(REPOSITORIES) or start > end:
                valid = False
                break
            parsed.append((bool(m.group(1)), list(range(start - 1, end))))
        if not valid:
            say("Invalid selection; check the available numbers and ranges.")
            continue
        inclusions = [i for excluded, ids in parsed if not excluded for i in ids]
        if inclusions:
            selected = set(inclusions)
        for excluded, ids in parsed:
            if excluded:
                selected.difference_update(ids)


def unique_filename(name: str, used: set[str]) -> str:
    # Never allow remote names to escape the selected output directory.
    name = Path(name.replace("\\", "/")).name
    name = re.sub(r"[\x00-\x1f\r\n]", "_", name).strip(" .") or "download.bin"
    candidate = name
    stem, suffix = Path(name).stem, Path(name).suffix
    n = 2
    while candidate.casefold() in used:
        candidate = f"{stem}-{n}{suffix}"
        n += 1
    used.add(candidate.casefold())
    return candidate


@dataclass
class DownloadTask:
    repository: str
    folder: Path
    url: str
    filename: str
    kind: str
    digest: str | None = None
    size_bytes: int | None = None

    @property
    def destination(self) -> Path:
        return self.folder / self.filename


class RangeNotSupported(Exception):
    pass


class TerminalProgress:
    """Compact, colorized ANSI progress renderer using only the standard library."""
    COLORS = {
        "reset": "\x1b[0m", "bold": "\x1b[1m", "dim": "\x1b[2m",
        "red": "\x1b[31m", "green": "\x1b[32m", "yellow": "\x1b[33m",
        "blue": "\x1b[34m", "magenta": "\x1b[35m", "cyan": "\x1b[36m",
        "white": "\x1b[37m", "gray": "\x1b[90m",
    }

    def __init__(self, tasks: list[DownloadTask], overall_total: int, overall_done: int = 0):
        self.lock = threading.RLock()
        self.tasks = {id(t): {"name": t.filename, "done": 0, "total": t.size_bytes,
                              "status": "Queued", "started": time.monotonic(),
                              "final_speed": None}
                      for t in tasks}
        self.overall_total = overall_total
        self.overall_done = overall_done
        self.tty = sys.stdout.isatty()
        self.cursor_enabled = self.tty and self._enable_virtual_terminal()
        self.colors_enabled = (self.cursor_enabled and USE_ANSI_COLORS
                               and "NO_COLOR" not in os.environ)
        self.last_render = 0.0
        self.render_lines = 0

    @staticmethod
    def _enable_virtual_terminal() -> bool:
        """Enable ANSI/VT processing on Windows consoles when possible."""
        if os.name != "nt":
            return True
        try:
            kernel32 = ctypes.windll.kernel32
            kernel32.GetStdHandle.argtypes = [ctypes.c_uint32]
            kernel32.GetStdHandle.restype = ctypes.c_void_p
            kernel32.GetConsoleMode.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
            kernel32.GetConsoleMode.restype = ctypes.c_int
            kernel32.SetConsoleMode.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
            kernel32.SetConsoleMode.restype = ctypes.c_int
            stdout_handle = kernel32.GetStdHandle(ctypes.c_uint32(-11).value)
            if not stdout_handle or stdout_handle == ctypes.c_void_p(-1).value:
                return False
            mode = ctypes.c_uint32()
            if not kernel32.GetConsoleMode(stdout_handle, ctypes.byref(mode)):
                return False
            enable_vt = 0x0004  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
            if mode.value & enable_vt:
                return True
            return bool(kernel32.SetConsoleMode(stdout_handle, mode.value | enable_vt))
        except (AttributeError, OSError, ValueError):
            return False

    def color(self, value: str, shade: str, *, bold: bool = False) -> str:
        if not self.colors_enabled:
            return value
        prefix = self.COLORS.get(shade, "")
        if bold:
            prefix = self.COLORS["bold"] + prefix
        return f"{prefix}{value}{self.COLORS['reset']}" if prefix else value

    @staticmethod
    def _size(n: int) -> str:
        value = float(n)
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if value < 1024 or unit == "TB":
                return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
            value /= 1024
        return f"{n} B"

    def _bar(self, filled: int, width: int, shade: str) -> str:
        full = "#" * filled
        empty = "-" * (width - filled)
        return "[" + self.color(full, shade, bold=True) + self.color(empty, "gray") + "]"

    def update(self, task_id: int, done: int | None = None, advance: int = 0,
               total: int | None = None, status: str | None = None, force: bool = False):
        with self.lock:
            item = self.tasks.get(task_id)
            if not item:
                return
            if done is not None:
                item["done"] = max(0, done)
            if advance:
                item["done"] += advance
            if total is not None:
                item["total"] = total
            if status:
                if status == "Downloading" and item["status"] == "Queued":
                    item["started"] = time.monotonic()
                item["status"] = status
            now = time.monotonic()
            if force or now - self.last_render >= (0.2 if self.tty else 2.0):
                self.render()

    def complete_file(self, task_id: int, success: bool, status: str):
        with self.lock:
            item = self.tasks.get(task_id)
            if item:
                if success:
                    if item["total"]:
                        item["done"] = item["total"]
                    elapsed = max(0.1, time.monotonic() - item["started"])
                    item["final_speed"] = item["done"] / elapsed
                item["status"] = status
            self.overall_done += 1
            self.render(force=True)

    def render(self, force: bool = False):
        now = time.monotonic()
        lines = []
        overall_pct = (self.overall_done / self.overall_total * 100) if self.overall_total else 100
        try:
            terminal_width = shutil.get_terminal_size((100, 24)).columns
        except OSError:
            terminal_width = 100
        compact = terminal_width < 130
        overall_width = max(8, min(24, terminal_width - 55))
        overall_filled = min(overall_width, int(overall_width * overall_pct / 100))
        overall_bar = self._bar(overall_filled, overall_width, "cyan")
        overall_label = self.color("Overall", "bold", bold=True)
        overall_count = self.color(f"{self.overall_done}/{self.overall_total} files", "white")
        overall_percent = self.color(f"{overall_pct:5.1f}%", "cyan", bold=True)
        lines.append(f"{overall_label} {overall_bar} {overall_count} ({overall_percent})")

        active_count = sum(1 for item in self.tasks.values()
                           if item["status"] in {"Downloading", "Retrying"})
        if active_count:
            spinner = ".oO@"[int(now * 5) % 4]
            working = self.color(f"Working {spinner}", "cyan", bold=True)
            active_label = "download" if active_count == 1 else "downloads"
            lines.append(f"{working} — {active_count} active {active_label}")

        for item in self.tasks.values():
            total, done = item["total"], item["done"]
            if total:
                pct = min(100.0, done / total * 100)
                width = max(8, min(22, terminal_width - (76 if not compact else 58)))
                filled = min(width, int(width * pct / 100))
                bar = self._bar(filled, width, "green")
                elapsed = max(0.1, now - item["started"])
                speed = item["final_speed"] if item["final_speed"] is not None else done / elapsed
                eta = (total - done) / speed if speed > 0 and done < total else 0
                size_text = self.color(f"{self._size(done)}/{self._size(total)}", "white")
                pct_text = self.color(f"{pct:5.1f}%", "cyan", bold=True)
                speed_text = self.color(f"{self._size(int(speed))}/s", "yellow", bold=True)
                eta_text = self.color(f"ETA {int(eta)}s", "magenta")
                if compact:
                    detail = f"{pct_text} {speed_text}"
                else:
                    detail = f"{size_text}  {pct_text}  {speed_text}  {eta_text}"
            else:
                # Unknown-size files still get a stable row; activity is shown
                # once in the dedicated Working line above, not over filenames.
                bar = self._bar(0, max(8, min(22, terminal_width - 58)), "gray")
                detail = self.color(f"{self._size(done)} transferred", "white")
            name = item["name"]
            name_width = 34 if not compact else max(12, min(24, terminal_width - 62))
            if len(name) > name_width:
                name = name[:max(1, name_width - 3)] + "..."
            name_text = self.color(f"{name:<{name_width}}", "white")
            status = item["status"]
            status_color = {
                "Downloaded": "green", "Downloading": "cyan", "Retrying": "yellow",
                "Not downloaded": "red", "Stopped": "red", "Queued": "gray",
            }.get(status, "white")
            status_text = self.color(status, status_color, bold=True)
            lines.append(f"{bar} {name_text} {detail}  {status_text}")
        if self.cursor_enabled:
            if self.render_lines:
                sys.stdout.write(f"\x1b[{self.render_lines}A")
            for line in lines:
                sys.stdout.write("\x1b[2K" + line + "\n")
            self.render_lines = len(lines)
            sys.stdout.flush()
        else:
            # Without VT support (or when redirected), avoid cursor/ANSI control
            # sequences and emit occasional plain-text snapshots instead.
            if force or now - self.last_render >= 10:
                for line in lines:
                    say(line)
        self.last_render = now


def _request_headers(offset: int | None = None, end: int | None = None) -> dict[str, str]:
    headers = {"User-Agent": USER_AGENT}
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    if offset is not None:
        headers["Range"] = f"bytes={offset}-{'' if end is None else end}"
    return headers


def _download_range(task: DownloadTask, start: int, end: int, chunk_path: Path,
                    progress: TerminalProgress, progress_id: int, max_attempts: int) -> None:
    expected = end - start + 1
    for attempt in range(1, max_attempts + 1):
        try:
            existing = chunk_path.stat().st_size if chunk_path.exists() else 0
            if existing == expected:
                return
            if existing > expected:
                chunk_path.unlink()
                existing = 0
            request = urllib.request.Request(task.url, headers=_request_headers(start + existing, end))
            with urllib.request.urlopen(request, timeout=DEFAULT_CONNECTION_TIMEOUT) as response:
                status = getattr(response, "status", response.getcode())
                if status != 206:
                    raise RangeNotSupported("The download server does not support HTTP Range requests")
                content_range = response.headers.get("Content-Range", "")
                match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+|\*)", content_range.strip())
                requested_start = start + existing
                if not match or int(match.group(1)) != requested_start or int(match.group(2)) != end:
                    raise RangeNotSupported("The server returned an invalid Content-Range response")
                if task.size_bytes and match.group(3) != "*" and int(match.group(3)) != task.size_bytes:
                    raise RangeNotSupported("The server's reported file size differs from GitHub metadata")
                mode = "ab" if existing else "wb"
                with chunk_path.open(mode) as output:
                    while True:
                        block = response.read(CHUNK_SIZE)
                        if not block:
                            break
                        output.write(block)
                        progress.update(progress_id, advance=len(block))
                    output.flush()
                    os.fsync(output.fileno())
            if chunk_path.stat().st_size != expected:
                raise RuntimeError(f"Incomplete range: {chunk_path.stat().st_size}/{expected} bytes")
            return
        except RangeNotSupported:
            raise
        except Exception as exc:
            log("ERROR", f"{task.repository}/{task.filename} range {start}-{end}, attempt {attempt}: {exc}")
            if attempt >= max_attempts:
                raise
            time.sleep(attempt * 2)


def _download_single(task: DownloadTask, max_attempts: int, progress: TerminalProgress,
                     progress_id: int) -> None:
    dest = task.destination
    part = dest.with_name(dest.name + ".part")
    for attempt in range(1, max_attempts + 1):
        try:
            offset = part.stat().st_size if part.exists() else 0
            request = urllib.request.Request(task.url, headers=_request_headers(offset if offset else None))
            with urllib.request.urlopen(request, timeout=DEFAULT_CONNECTION_TIMEOUT) as response:
                status = getattr(response, "status", response.getcode())
                if offset and status != 206:
                    offset = 0
                    part.unlink(missing_ok=True)
                    progress.update(progress_id, done=0, force=True)
                with part.open("ab" if offset else "wb") as output:
                    while True:
                        block = response.read(CHUNK_SIZE)
                        if not block:
                            break
                        output.write(block)
                        progress.update(progress_id, advance=len(block))
                    output.flush()
                    os.fsync(output.fileno())
            if not part.exists() or part.stat().st_size == 0:
                raise RuntimeError("Downloaded file is empty.")
            if task.size_bytes and part.stat().st_size != task.size_bytes:
                raise RuntimeError(f"File size mismatch: {part.stat().st_size}/{task.size_bytes} bytes")
            return
        except Exception as exc:
            log("ERROR", f"{task.repository}/{task.filename}: attempt {attempt}/{max_attempts}: {exc}")
            if attempt >= max_attempts:
                raise
            time.sleep(attempt * 2)


def download_file(task: DownloadTask, max_attempts: int, progress: TerminalProgress,
                  progress_id: int, threads_per_file: int) -> tuple[bool, str]:
    """Download a file using parallel byte ranges when its size is known."""
    dest = task.destination
    part = dest.with_name(dest.name + ".part")
    chunk_paths: list[Path] = []
    try:
        if task.size_bytes and threads_per_file > 1 and task.size_bytes > CHUNK_SIZE:
            size = task.size_bytes
            workers = min(threads_per_file, size)
            chunk_size = (size + workers - 1) // workers
            ranges = []
            for index in range(workers):
                begin = index * chunk_size
                finish = min(size - 1, begin + chunk_size - 1)
                if begin <= finish:
                    chunk = dest.with_name(f"{dest.name}.part{index}")
                    chunk_paths.append(chunk)
                    ranges.append((begin, finish, chunk))
            resumed_bytes = sum(chunk.stat().st_size for _, _, chunk in ranges if chunk.exists())
            if resumed_bytes:
                progress.update(progress_id, done=resumed_bytes, status="Resuming parts", force=True)
            try:
                with futures.ThreadPoolExecutor(max_workers=workers) as pool:
                    jobs = [pool.submit(_download_range, task, a, b, c, progress, progress_id, max_attempts)
                            for a, b, c in ranges]
                    for job in jobs:
                        job.result()
                with part.open("wb") as output:
                    for _, _, chunk in ranges:
                        with chunk.open("rb") as source:
                            shutil.copyfileobj(source, output, CHUNK_SIZE)
                    output.flush()
                    os.fsync(output.fileno())
            except RangeNotSupported:
                for chunk in chunk_paths:
                    chunk.unlink(missing_ok=True)
                chunk_paths.clear()
                progress.update(progress_id, done=0, status="Single-stream fallback", force=True)
                _download_single(task, max_attempts, progress, progress_id)
        else:
            _download_single(task, max_attempts, progress, progress_id)

        if task.digest and task.digest.startswith("sha256:"):
            expected = task.digest.split(":", 1)[1].lower()
            hasher = hashlib.sha256()
            with part.open("rb") as stream:
                for block in iter(lambda: stream.read(CHUNK_SIZE), b""):
                    hasher.update(block)
            if hasher.hexdigest().lower() != expected:
                part.unlink(missing_ok=True)
                for chunk in chunk_paths:
                    chunk.unlink(missing_ok=True)
                raise RuntimeError("SHA-256 checksum mismatch; partial file removed.")
        part.replace(dest)
        for chunk in chunk_paths:
            chunk.unlink(missing_ok=True)
        return True, f"Downloaded {task.repository} / {task.filename}"
    except Exception as exc:
        detail = f"{task.repository} / {task.filename}: {exc}"
        log("ERROR", detail)
        return False, detail



def build_tasks(repo: dict, release: dict | None, folder: Path, options: dict) -> list[DownloadTask]:
    tasks: list[DownloadTask] = []
    used: set[str] = set()
    full_name = f"{repo['owner']}/{repo['name']}"
    if release:
        for asset in release.get("assets", []):
            name = asset.get("name", "")
            low = name.casefold()
            if not name:
                continue
            if any(p.casefold() in low for p in options["exclusions"]):
                continue
            if not options["include_msi"] and low.endswith(".msi"):
                continue
            if options["includes"] and not any(p.casefold() in low for p in options["includes"]):
                continue
            tasks.append(DownloadTask(full_name, folder, asset.get("browser_download_url", ""),
                                      unique_filename(name, used), "Asset", asset.get("digest"), asset.get("size")))
        if options["source_zip"] and release.get("zipball_url"):
            tasks.append(DownloadTask(full_name, folder, release["zipball_url"],
                                      unique_filename("source-code.zip", used), "Source ZIP"))
    if options["readme"]:
        try:
            info = request_json(f"{API}/repos/{repo['owner']}/{repo['name']}/readme")
            if info.get("download_url"):
                tasks.append(DownloadTask(full_name, folder, info["download_url"],
                                          unique_filename("README.md", used), "README"))
        except Exception as exc:
            message = f"{full_name} README.md unavailable: {exc}"
            say(f"  [NOTICE] {message}")
            options.setdefault("issues", []).append((full_name, message))
            log("WARNING", message)
    return tasks


def ask_error_action(task: DownloadTask) -> str:
    say(f"\nA download failed: {task.repository} / {task.filename}")
    say("R = retry; S = skip and continue; Q = stop remaining downloads.")
    while True:
        choice = input("Action [R/S/Q]: ").strip().lower()
        if choice in ("r", "retry"):
            return "retry"
        if choice in ("s", "skip"):
            return "skip"
        if choice in ("q", "quit", "stop"):
            return "stop"


def ask_yes_no(message: str, default: bool = True) -> bool:
    hint = "Y/n" if default else "y/N"
    while True:
        answer = input(f"{message} [{hint}]: ").strip().casefold()
        if not answer:
            return default
        if answer in ("y", "yes", "да", "д"):
            return True
        if answer in ("n", "no", "нет", "н"):
            return False
        say("Please answer Y or N.")


def run_download_session(selected: list[dict]) -> int:
    say("\n========== Download options ==========")
    workers = prompt_int("Maximum simultaneous file downloads", DEFAULT_MAX_WORKERS)
    threads_per_file = prompt_int("Parallel threads per file", DEFAULT_THREADS_PER_FILE, 1, 32)
    apply_exclusions = ask_yes_no(
        "Apply filename exclusion filters?",
        APPLY_DEFAULT_EXCLUSIONS,
    ) if DEFAULT_EXCLUSIONS else False
    options = {
        "exclusions": DEFAULT_EXCLUSIONS[:] if apply_exclusions else [],
        "includes": DEFAULT_INCLUDES[:], "include_msi": DOWNLOAD_MSI,
        "source_zip": DOWNLOAD_SOURCE_ZIP, "readme": DOWNLOAD_README, "issues": [],
    }
    say(f"Filename exclusion filters: {'Enabled' if apply_exclusions else 'Disabled'}")

    # Show the exact filename rules that will affect release assets in this run.
    active_filters: list[tuple[str, list[str]]] = []
    if apply_exclusions and DEFAULT_EXCLUSIONS:
        active_filters.append(("Exclude filenames containing any of", DEFAULT_EXCLUSIONS))
    if DEFAULT_INCLUDES:
        active_filters.append(("Include only filenames containing at least one of", DEFAULT_INCLUDES))
    if not DOWNLOAD_MSI:
        active_filters.append(("Exclude file extension", [".msi"]))

    if active_filters:
        say("Applied filename filters (release assets only):")
        for label, patterns in active_filters:
            say(f"  - {label}: {', '.join(repr(item) for item in patterns)}")
    else:
        say("Applied filename filters: none (all release asset filenames are eligible).")

    say("Starting downloads immediately.")
    error_modes = {1: "skip and continue", 2: "ask after an error", 3: "retry, then skip"}
    error_label = error_modes.get(DEFAULT_ERROR_MODE, "retry, then skip")
    say(f"File workers: {workers}; threads per file: {threads_per_file}")
    say(f"Error handling: {error_label} (change DEFAULT_ERROR_MODE in the source to modify)")
    say(f"Log file: {LOG_PATH}")

    plans: list[tuple[dict, str, Path, list[DownloadTask]]] = []
    not_downloaded: list[tuple[str, str]] = []
    for repo in selected:
        full = f"{repo['owner']}/{repo['name']}"
        channel = repo["channel"]
        say(f"\n[{full}] Retrieving {channel} release information...")
        try:
            release = get_release(repo["owner"], repo["name"], channel, repo.get("tag"))
            if not release:
                message = f"{full}: no published {channel} release found"
                say(f"  [NOTICE] {message}")
                not_downloaded.append((full, message))
                continue
            tag = str(release.get("tag_name", ""))
            if not tag or re.search(r"\s", tag):
                message = f"{full}: invalid release tag"
                say(f"  [NOTICE] {message}")
                not_downloaded.append((full, message))
                continue
            safe_tag = re.sub(r'[\\/:*?"<>|]', "_", tag)
            folder = ROOT / f"{repo['name']}-{safe_tag}"
            folder.mkdir(parents=True, exist_ok=True)
            tasks = build_tasks(repo, release, folder, options)
            not_downloaded.extend(options.get("issues", []))
            options["issues"] = []
            pending = []
            for task in tasks:
                if task.destination.is_file() and task.destination.stat().st_size > 0:
                    continue
                if task.url:
                    pending.append(task)
                else:
                    not_downloaded.append((full, f"{task.filename}: download URL is missing"))
            plans.append((repo, tag, folder, pending))
            say(f"  {tag}: {len(pending)} file(s) queued")
        except Exception as exc:
            message = f"{full}: could not prepare release: {exc}"
            say(f"  [ERROR] {message}")
            log("ERROR", message)
            not_downloaded.append((full, message))

    total = sum(len(plan[3]) for plan in plans)
    say(f"\nFiles queued: {total}")
    if not total:
        say("No files are queued (files may already exist or be excluded by the configured filters).")
    success = download_errors = 0
    stopped = False
    overall_completed = 0
    for plan_index, (repo, tag, folder, tasks) in enumerate(plans):
        if stopped or not tasks:
            continue
        say(f"\n========== Downloading {repo['owner']}/{repo['name']} [{tag}] ==========")
        progress = TerminalProgress(tasks, total, overall_completed)
        progress.render(force=True)
        pending = list(tasks)
        ids = {id(task): id(task) for task in tasks}
        while pending and not stopped:
            batch, pending = pending[:workers], pending[workers:]
            for task in batch:
                progress.update(ids[id(task)], done=(task.destination.with_name(task.filename + ".part").stat().st_size
                                                     if task.destination.with_name(task.filename + ".part").exists() else 0),
                                status="Downloading", force=True)
            with futures.ThreadPoolExecutor(max_workers=workers) as pool:
                jobs = [(task, pool.submit(download_file, task,
                                           DEFAULT_RETRIES if DEFAULT_ERROR_MODE == 3 else 1,
                                           progress, ids[id(task)], threads_per_file)) for task in batch]
                results = [(task, job.result()) for task, job in jobs]
            result_by_id = {id(task): result for task, result in results}
            for task in batch:
                ok, detail = result_by_id[id(task)]
                if ok:
                    success += 1
                    progress.complete_file(ids[id(task)], True, "Downloaded")
                    log("INFO", detail)
                    continue
                download_errors += 1
                if DEFAULT_ERROR_MODE == 2:
                    action = ask_error_action(task)
                    if action == "retry":
                        pending.insert(0, task)
                        progress.update(ids[id(task)], status="Retrying", force=True)
                        continue
                    if action == "stop":
                        stopped = True
                        progress.complete_file(ids[id(task)], False, "Stopped")
                        not_downloaded.append((task.repository, detail))
                        continue
                progress.complete_file(ids[id(task)], False, "Not downloaded")
                not_downloaded.append((task.repository, detail))
                log("WARNING", f"Not downloaded: {detail}")
            overall_completed = progress.overall_done
        if stopped:
            for task in pending:
                not_downloaded.append((task.repository, f"{task.filename}: not started because the run was stopped"))
            for later_repo, later_tag, later_folder, later_tasks in plans[plan_index + 1:]:
                for task in later_tasks:
                    not_downloaded.append((task.repository, f"{task.filename}: not started because the run was stopped"))
        say(f"Finished {repo['owner']}/{repo['name']}.")
        if stopped:
            break

    say("\n========== Download summary ==========")
    say(f"Successfully downloaded: {success}")
    say(f"Not downloaded: {len(not_downloaded)}")
    say(f"Download errors (including retries): {download_errors}")
    if not_downloaded:
        say("\nThe following items were not downloaded or could not be prepared:")
        for repository, detail in not_downloaded:
            say(f" - {repository}: {detail}")
    if stopped:
        say("Stopped at user request; remaining queued files were not started.")
    say(f"Log: {LOG_PATH}")
    return 1 if not_downloaded or stopped else 0


def main_menu() -> str:
    say(f"\n========== {APP_NAME} ==========")
    say("1. Download newest releases from configured repositories")
    say("2. Download a specific release using its GitHub URL")
    say("Q. Quit")
    return input("Choose an option: ").strip().lower()


def run() -> int:
    while True:
        choice = main_menu()
        if choice in ("q", "quit"):
            return 0
        selected: list[dict] | None = None
        if choice in ("1", "latest"):
            selected = select_repositories()
            if selected is None:
                continue
        elif choice in ("2", "url", "specific"):
            while True:
                url = input("Paste GitHub release URL (or Q to return): ").strip()
                if url.lower() in ("q", "quit"):
                    break
                try:
                    owner, name, tag = parse_release_url(url)
                    selected = [{"owner": owner, "name": name, "channel": "Specific", "tag": tag}]
                    break
                except ValueError as exc:
                    say(str(exc))
            if selected is None:
                continue
        else:
            say("Invalid menu selection.")
            continue
        run_download_session(selected)
        say("\n1. Return to start menu")
        say("Q. Exit")
        after = input("Choose an option: ").strip().lower()
        if after in ("q", "quit"):
            return 0


if __name__ == "__main__":
    try:
        sys.exit(run())
    except KeyboardInterrupt:
        say("\nInterrupted by user. Partial download data is kept where possible for a later run.")
        log("WARNING", "Run interrupted by user.")
        sys.exit(130)
    except Exception as exc:
        say(f"Fatal error: {exc}")
        log("ERROR", f"Fatal error: {exc}")
        sys.exit(1)
