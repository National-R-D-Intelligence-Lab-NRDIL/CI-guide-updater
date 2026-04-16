"""Scraper and State Tracker module.

Fetches government grant web pages, extracts clean text, detects content
changes via SHA-256 hashing, and persists state between runs.
"""

import hashlib
import json
import os
import re
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

from src.utils.source_policy import normalize_and_validate_public_url

STATE_FILE = "state.json"
DATA_DIR = "data"


def fetch_and_clean_text(url: str) -> str:
    """Fetch a web page and return its visible text with scripts/styles removed.

    Args:
        url: The page URL to scrape.

    Returns:
        Cleaned, human-readable text extracted from the page.

    Raises:
        requests.HTTPError: If the server returns a non-2xx status code.
    """
    safe_url = normalize_and_validate_public_url(url, context="scraper")
    response = requests.get(safe_url, timeout=30)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    text = soup.get_text(separator="\n")
    lines = (line.strip() for line in text.splitlines())
    return "\n".join(line for line in lines if line)


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
    if os.path.exists(state_file):
        with open(state_file, "r", encoding="utf-8") as fh:
            return json.load(fh)
    return {}


def _save_state(state: dict, state_file: str) -> None:
    """Atomically write *state* to the state file."""
    os.makedirs(os.path.dirname(state_file) or ".", exist_ok=True)
    with open(state_file, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2)


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
        print(f"[{now}] {name}: no changes detected.")
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
    print(f"[{now}] {name}: {label} — saved to {data_path}")
    return True


if __name__ == "__main__":
    TARGET_URL = "https://grants.nih.gov/grants/funding/r15.htm"
    changed = check_for_updates(TARGET_URL, "NIH_R15")
    print(f"Content changed: {changed}")
