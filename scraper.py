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
from pathlib import Path
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
_OCR_TIMEOUT_S = 60

logger = logging.getLogger(__name__)

DEFAULT_REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def _header_get(response: requests.Response, key: str) -> str:
    """Return a response header value safely even for malformed clients."""
    headers = getattr(response, "headers", None)
    if hasattr(headers, "get"):
        value = headers.get(key)
        return str(value) if value is not None else ""
    return ""


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
            response = requests.get(safe_url, timeout=30, headers=DEFAULT_REQUEST_HEADERS)
            if response.status_code in {429, 503} and attempt < attempts - 1:
                base = 2 ** (attempt + 1)
                sleep_s = base + random.uniform(0, 1)
                retry_after = _header_get(response, "Retry-After")
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


def _extract_content_zone(html: str) -> str:
    """Extract main content text, stripping nav, header, footer, and cookie banners.

    Falls back to full-page _clean_html_text if no semantic content zone is found.
    This reduces false-positive change detection from cosmetic page elements.
    """
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    _NOISE_TAGS = ["nav", "header", "footer"]
    _NOISE_ROLES = {"navigation", "banner", "contentinfo"}
    _NOISE_IDS = {"cookie", "consent", "gdpr", "banner", "nav", "footer", "header"}
    _NOISE_CLASSES = {"cookie", "consent", "gdpr", "banner", "nav-", "navbar",
                      "footer", "header", "site-header", "site-footer",
                      "skip-nav", "breadcrumb"}

    for tag in soup.find_all(_NOISE_TAGS):
        tag.decompose()

    for tag in soup.find_all(attrs={"role": True}):
        if tag.get("role", "").lower() in _NOISE_ROLES:
            tag.decompose()

    for tag in soup.find_all(True):
        tag_id = str(tag.get("id", "")).lower()
        if any(noise in tag_id for noise in _NOISE_IDS):
            tag.decompose()
            continue
        tag_classes = " ".join(str(c).lower() for c in (tag.get("class") or []))
        if any(noise in tag_classes for noise in _NOISE_CLASSES):
            tag.decompose()

    main = soup.find("main") or soup.find(attrs={"role": "main"})
    if main:
        text = main.get_text(separator="\n")
    else:
        article = soup.find("article")
        if article:
            text = article.get_text(separator="\n")
        else:
            text = soup.get_text(separator="\n")

    lines = (line.strip() for line in text.splitlines())
    result = "\n".join(line for line in lines if line)

    if not result:
        return _clean_html_text(html)

    return result


def _extract_pdf_text_with_pypdf(pdf_bytes: bytes) -> tuple[str, int]:
    """Extract PDF text with pypdf and return (text, page_count)."""
    pdf_module = import_module("pypdf")
    PdfReader = pdf_module.PdfReader
    reader = PdfReader(BytesIO(pdf_bytes))
    chunks: list[str] = []
    pages = len(reader.pages)
    for page in reader.pages:
        chunks.append(page.extract_text() or "")
    text = "\n".join(chunk.strip() for chunk in chunks if chunk.strip())
    return text, pages


def _extract_pdf_text_with_pymupdf(pdf_bytes: bytes) -> tuple[str, int]:
    """Extract PDF text with PyMuPDF and return (text, page_count)."""
    fitz = import_module("fitz")
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    chunks: list[str] = []
    pages = len(doc)
    for page in doc:
        chunks.append(page.get_text("text") or "")
    text = "\n".join(chunk.strip() for chunk in chunks if chunk.strip())
    return text, pages


def _extract_pdf_text_with_ocr(
    pdf_bytes: bytes,
    *,
    endpoint: str,
    api_key: str,
) -> str:
    """Extract PDF text using an external OCR endpoint."""
    files = {
        "file": ("document.pdf", pdf_bytes, "application/pdf"),
    }
    headers = {"Authorization": f"Bearer {api_key}"}
    response = requests.post(
        endpoint,
        files=files,
        headers=headers,
        timeout=_OCR_TIMEOUT_S,
    )
    response.raise_for_status()
    payload = response.json()
    text = str(payload.get("text", "")).strip()
    if not text:
        raise RuntimeError("OCR endpoint returned no text.")
    return text


def _extract_pdf_payload(pdf_bytes: bytes, safe_url: str) -> dict:
    """Extract PDF text via pypdf, then PyMuPDF fallback, then optional OCR."""
    last_error: Exception | None = None
    extraction_method = ""
    page_count: int | None = None
    text = ""

    try:
        text, page_count = _extract_pdf_text_with_pypdf(pdf_bytes)
        extraction_method = "pypdf"
    except Exception as exc:
        last_error = exc
        logger.warning("source=%s pdf_extract_failed method=pypdf error=%s", safe_url, exc)

    if not text:
        try:
            text, page_count = _extract_pdf_text_with_pymupdf(pdf_bytes)
            extraction_method = "pymupdf"
        except Exception as exc:
            last_error = exc
            logger.warning("source=%s pdf_extract_failed method=pymupdf error=%s", safe_url, exc)

    if not text:
        endpoint = os.getenv("OCR_ENDPOINT", "").strip()
        api_key = os.getenv("OCR_API_KEY", "").strip()
        if endpoint and api_key:
            try:
                text = _extract_pdf_text_with_ocr(
                    pdf_bytes,
                    endpoint=endpoint,
                    api_key=api_key,
                )
                extraction_method = "ocr"
            except Exception as exc:
                last_error = exc
                logger.warning("source=%s pdf_extract_failed method=ocr error=%s", safe_url, exc)

    if not text:
        detail = f" Last error: {last_error}" if last_error else ""
        raise RuntimeError(
            "Unable to extract PDF text via pypdf, pymupdf, or OCR."
            + detail
        )

    return {
        "text": text,
        "metadata": {
            "url": safe_url,
            "extraction_method": extraction_method,
            "character_count": len(text),
            "page_count": page_count,
            "content_type": "application/pdf",
        },
    }


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


def fetch_source_payload(url: str) -> dict:
    """Fetch source content and return text plus extraction metadata."""
    safe_url = normalize_and_validate_public_url(url, context="scraper")
    response = _fetch_with_retries(safe_url)
    content_type = _header_get(response, "Content-Type").lower()

    is_pdf = safe_url.lower().endswith(".pdf") or "application/pdf" in content_type
    if is_pdf:
        content_bytes = getattr(response, "content", None)
        if content_bytes is None:
            content_bytes = response.text.encode("utf-8", errors="ignore")
        return _extract_pdf_payload(content_bytes, safe_url)

    html_text = _clean_html_text(response.text)
    content_zone_text = _extract_content_zone(response.text)
    extraction_method = "html"
    final_text = html_text
    if not (html_text and not _is_likely_unscrapable_page(response.text)):
        fallback_text = _extract_fallback_text(response.text, safe_url)
        if html_text:
            final_text = f"{html_text}\n\n{fallback_text}"
        else:
            final_text = fallback_text
        content_zone_text = final_text

    return {
        "text": final_text,
        "metadata": {
            "url": safe_url,
            "extraction_method": extraction_method,
            "character_count": len(final_text),
            "page_count": None,
            "content_type": content_type or "text/html",
        },
        "content_zone_text": content_zone_text,
    }


def _resolve_local_source_path(file_path: str) -> Path:
    """Resolve and validate a local source path."""
    raw = str(file_path or "").strip()
    if not raw:
        raise ValueError("Local source path is required.")
    candidate = Path(raw).expanduser()
    if candidate.is_absolute():
        resolved = candidate.resolve()
    else:
        # Streamlit Cloud can launch from a nested working directory (for
        # example `app/`), so resolve relative source paths from both the
        # active cwd and the repository root that contains this module.
        search_roots = [Path.cwd(), Path(__file__).resolve().parent]
        resolved = None
        for root in search_roots:
            root_candidate = (root / candidate).resolve()
            if root_candidate.exists():
                resolved = root_candidate
                break
        if resolved is None:
            resolved = (Path.cwd() / candidate).resolve()
    if not resolved.exists():
        raise FileNotFoundError(f"Local source file not found: {resolved}")
    if resolved.suffix.lower() != ".pdf":
        raise ValueError("Only PDF uploads are currently supported as local sources.")
    return resolved


def fetch_source_payload_from_source(source: dict) -> dict:
    """Fetch source payload from either URL-based or local-file-based source dict."""
    local_path = str(source.get("file_path", "")).strip() if isinstance(source, dict) else ""
    if local_path:
        path = _resolve_local_source_path(local_path)
        pdf_bytes = path.read_bytes()
        payload = _extract_pdf_payload(pdf_bytes, str(path))
        payload["metadata"]["file_path"] = str(path)
        payload["content_zone_text"] = payload["text"]
        return payload

    url = str(source.get("url", "")).strip() if isinstance(source, dict) else ""
    if not url:
        raise ValueError("Source must include either 'url' or 'file_path'.")
    return fetch_source_payload(url)


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
    return fetch_source_payload(url)["text"]


def check_for_updates_from_source(
    source: dict,
    name: str,
    state_file: str = STATE_FILE,
    data_dir: str = DATA_DIR,
) -> bool:
    """Scrape one source dict, compare hash, and persist snapshots and metadata."""
    payload = fetch_source_payload_from_source(source)
    text = payload["text"]
    metadata = payload.get("metadata", {})
    content_zone = payload.get("content_zone_text", text)
    new_hash = generate_hash(content_zone)
    now = datetime.now(timezone.utc).isoformat()

    state = _load_state(state_file)
    entry = state.get(name)

    if entry and entry.get("hash") == new_hash:
        logger.info("source=%s status=no_change checked_at=%s", name, now)
        state[name]["last_checked"] = now
        state[name]["extraction"] = metadata
        _save_state(state, state_file)
        return False

    os.makedirs(data_dir, exist_ok=True)
    safe_name = re.sub(r"[^A-Za-z0-9_-]", "_", name)
    data_path = os.path.join(data_dir, f"{safe_name}_latest.txt")
    with open(data_path, "w", encoding="utf-8") as fh:
        fh.write(text)
    metadata_path = os.path.join(data_dir, f"{safe_name}_latest.meta.json")
    with open(metadata_path, "w", encoding="utf-8") as meta_fh:
        json.dump(metadata, meta_fh, indent=2)

    label = "updated" if entry else "new entry"
    state[name] = {
        "url": source.get("url", ""),
        "file_path": source.get("file_path", ""),
        "hash": new_hash,
        "last_checked": now,
        "extraction": metadata,
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
    return check_for_updates_from_source(
        {"url": url},
        name,
        state_file=state_file,
        data_dir=data_dir,
    )


if __name__ == "__main__":
    TARGET_URL = "https://grants.nih.gov/grants/funding/r15.htm"
    changed = check_for_updates(TARGET_URL, "NIH_R15")
    logger.info("content_changed=%s", changed)
