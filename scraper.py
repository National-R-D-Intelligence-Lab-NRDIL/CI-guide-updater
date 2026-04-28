"""Scraper and State Tracker module.

Fetches government grant web pages, extracts clean text, detects content
changes via SHA-256 hashing, and persists state between runs.
"""

import hashlib
import json
import logging
import os
import random
import re
import time
from datetime import datetime, timezone
from importlib import import_module
from typing import TextIO

import requests
from bs4 import BeautifulSoup
from io import BytesIO

from src.utils.source_policy import normalize_and_validate_public_url

if os.name == "nt":
    import msvcrt
else:
    import fcntl

STATE_FILE = "state.json"
DATA_DIR = "data"
_MAX_FALLBACK_DOC_LINKS = 3

logger = logging.getLogger(__name__)


def _lock_file_path(state_file: str) -> str:
    """Return the lock-file path associated with a state file."""
    return f"{state_file}.lock"


def _acquire_file_lock(fh: TextIO) -> None:
    """Acquire an exclusive lock for a lock-file handle."""
    if os.name == "nt":
        fh.seek(0)
        msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1)
    else:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)


def _release_file_lock(fh: TextIO) -> None:
    """Release an exclusive lock for a lock-file handle."""
    if os.name == "nt":
        fh.seek(0)
        msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def _fetch_with_retries(safe_url: str) -> requests.Response:
    """Fetch URL with retry handling for transient failures."""
    attempts = 4
    last_connection_error: requests.ConnectionError | None = None

    for attempt in range(attempts):
        try:
            response = requests.get(safe_url, timeout=30)
            if response.status_code in {429, 503} and attempt < attempts - 1:
                base = 2 ** (attempt + 1)
                sleep_s = base + random.uniform(0, 1)
                retry_after = response.headers.get("Retry-After")
                if retry_after is not None:
                    try:
                        retry_after_s = float(retry_after)
                        sleep_s = min(60.0, max(sleep_s, retry_after_s))
                    except ValueError:
                        pass
                time.sleep(sleep_s)
                continue
            response.raise_for_status()
            return response
        except requests.ConnectionError as exc:
            last_connection_error = exc
            if attempt >= attempts - 1:
                raise
            base = 2 ** (attempt + 1)
            sleep_s = base + random.uniform(0, 1)
            time.sleep(sleep_s)

    if last_connection_error is not None:
        raise last_connection_error
    raise RuntimeError(f"Failed to fetch {safe_url} after {attempts} attempts.")


def _clean_html_text(html: str) -> str:
    """Extract visible text from HTML while removing noisy tags."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    text = soup.get_text(separator="\n")
    lines = (line.strip() for line in text.splitlines())
    return "\n".join(line for line in lines if line)


def _extract_pdf_text(pdf_bytes: bytes) -> str:
    """Extract text content from a PDF byte stream."""
    try:
        pdf_module = import_module("pypdf")
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "PDF support requires the optional dependency 'pypdf'. "
            "Install it with: pip install 'pypdf>=4,<6'"
        ) from exc

    PdfReader = pdf_module.PdfReader
    reader = PdfReader(BytesIO(pdf_bytes))
    chunks: list[str] = []
    for page in reader.pages:
        chunks.append(page.extract_text() or "")
    text = "\n".join(chunk.strip() for chunk in chunks if chunk.strip())
    if not text:
        return "[PDF parsed but no extractable text was found.]"
    return text


def _looks_like_document_link(href: str) -> bool:
    lowered = href.lower()
    return lowered.endswith((".pdf", ".doc", ".docx", ".txt", ".rtf"))


def _extract_fallback_text(html: str, base_url: str) -> str:
    """Extract metadata and linked-doc hints when visible page text is sparse."""
    soup = BeautifulSoup(html, "html.parser")
    lines: list[str] = []

    if soup.title and soup.title.string:
        lines.append(f"Title: {soup.title.string.strip()}")

    for key in ("description", "og:description", "twitter:description"):
        tag = soup.find("meta", attrs={"name": key}) or soup.find("meta", attrs={"property": key})
        if tag and tag.get("content"):
            lines.append(f"{key}: {tag['content'].strip()}")

    link_lines: list[str] = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if _looks_like_document_link(href):
            label = a.get_text(" ", strip=True) or href
            link_lines.append(f"{label}: {href}")
        if len(link_lines) >= _MAX_FALLBACK_DOC_LINKS:
            break

    if link_lines:
        lines.append("Possible document links:")
        lines.extend(link_lines)

    if not lines:
        lines.append(f"Unable to extract meaningful text from {base_url}.")
        lines.append("The page may require JavaScript rendering or anti-bot challenges.")

    return "\n".join(lines)


def _is_likely_unscrapable_page(raw_html: str) -> bool:
    """Heuristic for JS-gated / anti-bot pages with poor extractable text."""
    lowered = raw_html.lower()
    markers = (
        "enable javascript",
        "access denied",
        "checking your browser",
        "cf-browser-verification",
        "captcha",
        "are you human",
        "please turn javascript on",
    )
    return any(marker in lowered for marker in markers)


# Retries on ConnectionError and on HTTP 429/503. Backoff is jittered
# exponential: ~2s, ~4s, ~8s (plus 0–1s jitter), capped by any Retry-After
# header up to 60s. Final attempt does not sleep.
def fetch_and_clean_text(url: str) -> str:
    """Fetch a web source and return readable text.

    Supports HTML pages and direct PDF links. For difficult pages where visible
    HTML text is very sparse, falls back to metadata/doc-link extraction.

    Args:
        url: The source URL to ingest.

    Returns:
        Cleaned, human-readable text extracted from the source.

    Raises:
        requests.HTTPError: If the server returns a non-retryable non-2xx status code.
        requests.ConnectionError: If all retry attempts fail due to connectivity issues.
    """
    safe_url = normalize_and_validate_public_url(url, context="scraper")
    response = _fetch_with_retries(safe_url)
    content_type = (response.headers.get("Content-Type") or "").lower()

    is_pdf = safe_url.lower().endswith(".pdf") or "application/pdf" in content_type
    if is_pdf:
        content_bytes = getattr(response, "content", None)
        if content_bytes is None:
            content_bytes = response.text.encode("utf-8", errors="ignore")
        return _extract_pdf_text(content_bytes)

    html_text = _clean_html_text(response.text)
    if html_text and not _is_likely_unscrapable_page(response.text):
        return html_text

    fallback_text = _extract_fallback_text(response.text, safe_url)
    if html_text:
        return f"{html_text}\n\n{fallback_text}"
    return fallback_text


def generate_hash(text: str) -> str:
    """Return the SHA-256 hex digest of *text*.

    Args:
        text: Arbitrary string to hash.

    Returns:
        64-character lowercase hex string.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _load_state(state_file: str) -> dict:
    """Read and return the persisted state dict, or an empty dict."""
    os.makedirs(os.path.dirname(state_file) or ".", exist_ok=True)
    lock_path = _lock_file_path(state_file)
    with open(lock_path, "a+", encoding="utf-8") as lock_fh:
        _acquire_file_lock(lock_fh)
        try:
            if not os.path.exists(state_file):
                return {}
            with open(state_file, "r", encoding="utf-8") as state_fh:
                raw = state_fh.read().strip()
                if not raw:
                    return {}
                return json.loads(raw)
        finally:
            _release_file_lock(lock_fh)


def _save_state(state: dict, state_file: str) -> None:
    """Atomically write *state* to the state file."""
    os.makedirs(os.path.dirname(state_file) or ".", exist_ok=True)
    lock_path = _lock_file_path(state_file)
    with open(lock_path, "a+", encoding="utf-8") as lock_fh:
        _acquire_file_lock(lock_fh)
        try:
            with open(state_file, "w", encoding="utf-8") as state_fh:
                json.dump(state, state_fh, indent=2)
                state_fh.flush()
                os.fsync(state_fh.fileno())
        finally:
            _release_file_lock(lock_fh)


def check_for_updates(
    url: str,
    name: str,
    state_file: str = STATE_FILE,
    data_dir: str = DATA_DIR,
) -> bool:
    """Scrape *url*, compare against the last-known hash, and persist changes.

    The function stores per-entry metadata in a state file::

        {
          "<name>": {
            "url": "...",
            "hash": "...",
            "last_checked": "..."
          }
        }

    When a change (or a brand-new entry) is detected the full scraped text is
    saved to ``<data_dir>/<name>_latest.txt`` and the state file is updated.

    Args:
        url:  Target page URL.
        name: Short identifier for this source (e.g. ``"NIH_R15"``).
        state_file: Path to the JSON state file.
        data_dir: Directory where latest snapshots are written.

    Returns:
        ``True`` if the content changed (or is new), ``False`` otherwise.
    """
    text = fetch_and_clean_text(url)
    new_hash = generate_hash(text)
    now = datetime.now(timezone.utc).isoformat()

    state = _load_state(state_file)
    entry = state.get(name)

    if entry and entry.get("hash") == new_hash:
        logger.info("source=%s status=no_change checked_at=%s", name, now)
        state[name]["last_checked"] = now
        _save_state(state, state_file)
        return False

    os.makedirs(data_dir, exist_ok=True)
    safe_name = re.sub(r"[^A-Za-z0-9_-]", "_", name)
    data_path = os.path.join(data_dir, f"{safe_name}_latest.txt")
    with open(data_path, "w", encoding="utf-8") as fh:
        fh.write(text)

    label = "updated" if entry else "new entry"
    state[name] = {
        "url": url,
        "hash": new_hash,
        "last_checked": now,
    }
    _save_state(state, state_file)
    logger.info(
        "source=%s status=%s checked_at=%s snapshot_path=%s",
        name,
        label.replace(" ", "_"),
        now,
        data_path,
    )
    return True


if __name__ == "__main__":
    TARGET_URL = "https://grants.nih.gov/grants/funding/r15.htm"
    changed = check_for_updates(TARGET_URL, "NIH_R15")
    logger.info("content_changed=%s", changed)
