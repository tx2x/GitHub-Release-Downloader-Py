#!/usr/bin/env python3
"""GitHub Release Downloader Py - interactive GitHub release asset downloader."""
from __future__ import annotations

import concurrent.futures as futures
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

APP_NAME = "GitHub-Release-Downloader-Py"
API = "https://api.github.com"
USER_AGENT = f"{APP_NAME}/1.0"
CHUNK_SIZE = 1024 * 1024

# Edit this list to add, remove, or change repositories.
# channel: "Stable" or "Pre-release"
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

# Literal, case-insensitive substrings applied to release asset names only.
DEFAULT_EXCLUSIONS = ["arm64", "aarch64", "riscv", "darwin", ".dmg"]
DEFAULT_MAX_WORKERS = 2
DEFAULT_RETRIES = 2  # number of attempts in automatic mode 3
DEFAULT_ERROR_MODE = 3  # 1=skip, 2=ask, 3=retry once then skip
DEFAULT_CONNECTION_TIMEOUT = 30

_console_lock = threading.Lock()


def say(message: str = "") -> None:
    with _console_lock:
        print(message, flush=True)


def prompt_yes_no(message: str, default: bool = False) -> bool:
    hint = "Y/n" if default else "y/N"
    while True:
        answer = input(f"{message} [{hint}]: ").strip().lower()
        if not answer:
            return default
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no"):
            return False
        say("Enter Y or N.")


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

    @property
    def destination(self) -> Path:
        return self.folder / self.filename


def download_file(task: DownloadTask, max_attempts: int = 2) -> tuple[bool, str, int]:
    """Stream to .part, resume with HTTP Range, then atomically rename."""
    dest = task.destination
    part = dest.with_name(dest.name + ".part")
    headers = {"User-Agent": USER_AGENT}
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    for attempt in range(1, max_attempts + 1):
        try:
            offset = part.stat().st_size if part.exists() else 0
            if offset:
                headers["Range"] = f"bytes={offset}-"
            request = urllib.request.Request(task.url, headers=headers)
            with urllib.request.urlopen(request, timeout=DEFAULT_CONNECTION_TIMEOUT) as response:
                status = getattr(response, "status", response.getcode())
                if offset and status != 206:
                    # Server ignored Range; restart instead of corrupting the file.
                    offset = 0
                    part.unlink(missing_ok=True)
                mode = "ab" if offset else "wb"
                with part.open(mode) as output:
                    while True:
                        block = response.read(CHUNK_SIZE)
                        if not block:
                            break
                        output.write(block)
                    output.flush()
                    os.fsync(output.fileno())
            if not part.exists() or part.stat().st_size == 0:
                raise RuntimeError("Downloaded file is empty.")
            if task.digest and task.digest.startswith("sha256:"):
                expected = task.digest.split(":", 1)[1].lower()
                hasher = hashlib.sha256()
                with part.open("rb") as stream:
                    for block in iter(lambda: stream.read(CHUNK_SIZE), b""):
                        hasher.update(block)
                if hasher.hexdigest().lower() != expected:
                    part.unlink(missing_ok=True)
                    raise RuntimeError("SHA-256 checksum mismatch; partial file removed.")
            part.replace(dest)
            return True, f"Downloaded {task.repository} / {task.filename}", attempt
        except Exception as exc:
            detail = f"{task.repository} / {task.filename}: attempt {attempt}/{DEFAULT_RETRIES}: {exc}"
            log("ERROR", detail)
            if attempt < max_attempts:
                say(f"[DOWNLOAD ERROR] {detail}\n  Retrying in {attempt * 2}s...")
                time.sleep(attempt * 2)
            else:
                say(f"[DOWNLOAD ERROR] {detail}\n  Details saved to {LOG_PATH}")
                # Keep .part so a later run can resume it.
                return False, detail, max_attempts
    return False, "Unknown download failure", max_attempts


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
                say(f"  Excluded by filename pattern: {name}")
                continue
            if not options["include_msi"] and low.endswith(".msi"):
                continue
            if options["includes"] and not any(p.casefold() in low for p in options["includes"]):
                continue
            tasks.append(DownloadTask(full_name, folder, asset.get("browser_download_url", ""),
                                      unique_filename(name, used), "Asset", asset.get("digest")))
        if options["source_zip"] and release.get("zipball_url"):
            tasks.append(DownloadTask(full_name, folder, release["zipball_url"],
                                      unique_filename("source-code.zip", used), "Source ZIP"))
    if options["readme"]:
        try:
            info = request_json(f"{API}/repos/{repo['owner']}/{repo['name']}/readme")
            if info.get("download_url"):
                tasks.append(DownloadTask(full_name, folder, info["download_url"],
                                          unique_filename("README.md", used), "README"))
            else:
                say("  README endpoint returned no download URL.")
        except Exception as exc:
            say(f"  README.md unavailable: {exc}")
            log("WARNING", f"{full_name} README: {exc}")
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


def run() -> int:
    say(f"\n========== {APP_NAME} ==========")
    say("1. Download newest releases from configured repositories")
    say("2. Download a specific release using its GitHub URL")
    say("Q. Quit")
    choice = input("Choose an option: ").strip().lower()
    if choice in ("q", "quit"):
        return 0
    if choice in ("1", "latest"):
        selected = select_repositories()
        if selected is None:
            return 0
    elif choice in ("2", "url", "specific"):
        while True:
            url = input("Paste GitHub release URL (or Q to cancel): ").strip()
            if url.lower() in ("q", "quit"):
                return 0
            try:
                owner, name, tag = parse_release_url(url)
                selected = [{"owner": owner, "name": name, "channel": "Specific", "tag": tag}]
                break
            except ValueError as exc:
                say(str(exc))
    else:
        say("Invalid menu selection.")
        return 1

    say("\n========== Download options ==========")
    advanced = prompt_yes_no("Apply filename filters and optional download restrictions?", False)
    options = {"exclusions": [], "includes": [], "include_msi": True, "source_zip": True, "readme": True}
    if advanced:
        if prompt_yes_no(f"Apply configured exclusions ({', '.join(DEFAULT_EXCLUSIONS)})?", True):
            options["exclusions"].extend(DEFAULT_EXCLUSIONS)
        if prompt_yes_no("Add extra exclusion keywords?", False):
            options["exclusions"].extend(x.strip() for x in input("Keywords (comma-separated): ").split(",") if x.strip())
        if prompt_yes_no("Download only assets matching specified keywords?", False):
            while not options["includes"]:
                options["includes"] = [x.strip() for x in input("Include keywords (comma-separated): ").split(",") if x.strip()]
        options["include_msi"] = prompt_yes_no("Download .msi files?", True)
        options["source_zip"] = prompt_yes_no("Download release source ZIP?", True)
        options["readme"] = prompt_yes_no("Download repository README.md?", True)
    workers = prompt_int("Maximum simultaneous file downloads per repository", DEFAULT_MAX_WORKERS)
    mode = prompt_int("Error handling mode (1=skip, 2=ask, 3=retry once then skip)", DEFAULT_ERROR_MODE, 1, 3)

    plans: list[tuple[dict, str, Path, list[DownloadTask]]] = []
    for repo in selected:
        full = f"{repo['owner']}/{repo['name']}"
        channel = repo["channel"]
        say(f"\n[{full}] Retrieving {channel} release information...")
        try:
            release = get_release(repo["owner"], repo["name"], channel, repo.get("tag"))
            if not release:
                say(f"  No published {channel} release found.")
                continue
            tag = str(release.get("tag_name", ""))
            if not tag or re.search(r"\s", tag):
                say(f"  Invalid release tag; skipping {full}.")
                continue
            safe_tag = re.sub(r'[\\/:*?"<>|]', "_", tag)
            folder = ROOT / f"{repo['name']}-{safe_tag}"
            folder.mkdir(parents=True, exist_ok=True)
            tasks = build_tasks(repo, release, folder, options)
            pending = []
            for task in tasks:
                if task.destination.is_file() and task.destination.stat().st_size > 0:
                    say(f"  Already exists, skipping: {task.filename}")
                elif task.url:
                    pending.append(task)
            plans.append((repo, tag, folder, pending))
            say(f"  {tag}: {len(pending)} file(s) queued")
        except Exception as exc:
            say(f"  Could not prepare {full}: {exc}")
            log("ERROR", f"{full}: {exc}")

    total = sum(len(p[3]) for p in plans)
    say(f"\nFiles queued: {total}")
    say(f"Parallel downloads per repository: {workers}; error mode: {mode}")
    say(f"Log file: {LOG_PATH}")
    if not total:
        say("No files are queued.")
        return 0
    if not prompt_yes_no("Start downloading now?", True):
        say("Download cancelled.")
        return 0

    success = skipped = failed_attempts = 0
    stopped = False
    for repo, tag, folder, tasks in plans:
        if stopped:
            break
        say(f"\n========== Downloading {repo['owner']}/{repo['name']} [{tag}] ==========")
        pending = list(tasks)
        while pending and not stopped:
            batch, pending = pending[:workers], pending[workers:]
            with futures.ThreadPoolExecutor(max_workers=workers) as pool:
                max_attempts = 2 if mode == 3 else 1
                results = list(pool.map(lambda task: download_file(task, max_attempts), batch))
            for task, (ok, detail, attempts_used) in zip(batch, results):
                if ok:
                    success += 1
                    say(f"[OK] {detail}")
                    log("INFO", detail)
                    continue
                failed_attempts += attempts_used
                if mode == 1:
                    skipped += 1
                    log("WARNING", f"Skipped after error: {detail}")
                elif mode == 2:
                    action = ask_error_action(task)
                    if action == "retry":
                        pending.insert(0, task)
                    elif action == "skip":
                        skipped += 1
                        log("WARNING", f"User skipped: {detail}")
                    else:
                        stopped = True
                        log("WARNING", "User stopped the run after a download error.")
                else:
                    # Automatic mode already performed its one retry.
                    skipped += 1
                    log("WARNING", f"Skipped after automatic retries: {detail}")
        say(f"Finished {repo['owner']}/{repo['name']}.")

    say("\n========== Download summary ==========")
    say(f"Successfully downloaded: {success}")
    say(f"Skipped after errors: {skipped}")
    say(f"Failed download attempts (including retries): {failed_attempts}")
    say(f"Log: {LOG_PATH}")
    if stopped:
        say("Stopped at user request; remaining tasks were not started.")
    return 1 if skipped or stopped else 0


if __name__ == "__main__":
    try:
        sys.exit(run())
    except KeyboardInterrupt:
        say("\nInterrupted by user. Partial .part files are kept for resuming on the next run.")
        log("WARNING", "Run interrupted by user.")
        sys.exit(130)
    except Exception as exc:
        say(f"Fatal error: {exc}")
        log("ERROR", f"Fatal error: {exc}")
        sys.exit(1)
