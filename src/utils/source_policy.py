"""Helpers for source classification and LLM safety checks."""

from __future__ import annotations

import functools
import json
import ipaddress
import re
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from typing import Any


PUBLIC_DATA_CLASS = "public"
_TRUSTED_DOMAINS_PATH = Path(__file__).resolve().parents[2] / "config" / "trusted_domains.json"


@functools.lru_cache(maxsize=1)
def _load_foundation_allowlist() -> frozenset[str]:
    try:
        raw = _TRUSTED_DOMAINS_PATH.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise RuntimeError(f"Trusted domains config is missing: {_TRUSTED_DOMAINS_PATH}") from exc

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid trusted domains config JSON: {exc}") from exc

    domains = payload.get("foundation_domains")
    if not isinstance(domains, list):
        raise RuntimeError("Invalid trusted domains config: 'foundation_domains' must be a list")

    validated: set[str] = set()
    for domain in domains:
        if not isinstance(domain, str):
            raise RuntimeError(f"Invalid trusted domain entry: {domain!r}")
        value = domain.strip()
        if (
            not value
            or value != domain
            or value != value.lower()
            or "*" in value
            or "/" in value
            or ":" in value
        ):
            raise RuntimeError(f"Invalid trusted domain entry: {domain!r}")
        validated.add(value)

    return frozenset(validated)


def _normalize_data_class(value: Any) -> str:
    return str(value).strip().lower()


def assert_public_sources(sources: list[dict[str, Any]], *, context: str) -> None:
    """Ensure every source is explicitly marked as public.

    The caller is expected to use this before any LLM handoff that could expose
    source contents to an external model provider.
    """
    for idx, source in enumerate(sources):
        if not isinstance(source, dict):
            raise ValueError(f"{context}: source at index {idx} must be an object")

        data_class = _normalize_data_class(source.get("data_class", ""))
        if data_class != PUBLIC_DATA_CLASS:
            name = str(source.get("name", "")).strip() or f"index {idx}"
            raise ValueError(
                f"{context}: source '{name}' at index {idx} has data_class="
                f"{source.get('data_class')!r}; only data_class='public' sources may be sent to the LLM."
            )

        source["data_class"] = PUBLIC_DATA_CLASS


def normalize_public_source(source: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of a source dict normalized for public-only workflows."""
    data = dict(source)
    data["data_class"] = PUBLIC_DATA_CLASS
    return data


def normalize_and_validate_public_url(url: str, *, context: str) -> str:
    """Return a normalized https URL if it matches our public-source allowlist.

    This is a defense-in-depth SSRF mitigation: a corrupted `sources.json` or
    user-entered URL should not be able to trick the scraper into probing
    internal network resources.
    """
    raw = str(url or "").strip()
    if not raw:
        raise ValueError(f"{context}: URL is required.")

    parts = urlsplit(raw)
    scheme = (parts.scheme or "").lower()
    if scheme != "https":
        raise ValueError(f"{context}: URL must use https://")

    if parts.username or parts.password:
        raise ValueError(f"{context}: URL must not contain user info.")

    host = (parts.hostname or "").strip().lower().rstrip(".")
    if not host:
        raise ValueError(f"{context}: URL must include a hostname.")

    # Reject literal IPs entirely (both IPv4 and IPv6) to avoid bypassing
    # hostname allowlists and to prevent obvious internal targeting.
    try:
        ip = ipaddress.ip_address(host)
        raise ValueError(f"{context}: IP address hosts are not allowed ({ip}).")
    except ValueError as exc:
        # ip_address raises ValueError for non-IPs; only re-raise for our message.
        if "IP address hosts are not allowed" in str(exc):
            raise

    # Disallow non-standard ports to reduce SSRF gadget surface.
    if parts.port not in (None, 443):
        raise ValueError(f"{context}: Non-standard ports are not allowed.")

    if not _host_is_allowlisted(host):
        raise ValueError(f"{context}: Host '{host}' is not in the trusted allowlist.")

    # Normalize: lowercase scheme/host, preserve path/query/fragment.
    netloc = host
    if parts.port and parts.port != 443:
        netloc = f"{host}:{parts.port}"
    normalized = urlunsplit(("https", netloc, parts.path or "", parts.query or "", parts.fragment or ""))
    return normalized


def _host_is_allowlisted(host: str) -> bool:
    if host.endswith(".gov") or host.endswith(".edu"):
        return True

    for root in _load_foundation_allowlist():
        if host == root or host.endswith(f".{root}"):
            return True

    return False


# Load once during import to fail closed if config is missing/invalid.
_load_foundation_allowlist()


def sanitize_program_for_prompt(program: str) -> str:
    """Sanitize user-controlled program text before prompt interpolation.

    Removes newline/control characters and common prompt-injection markers
    while preserving enough semantic detail for source discovery quality.
    """
    text = str(program or "")
    text = re.sub(r"[\r\n\t]+", " ", text)
    text = re.sub(r"[\x00-\x1f\x7f]", " ", text)

    # Strip common role/instruction markers and delimiter tokens often used
    # in prompt-injection payloads.
    text = re.sub(
        r"(?i)\b(system|assistant|developer|user)\s*:\s*",
        "",
        text,
    )
    text = re.sub(r"(?i)\b(ignore\s+previous\s+instructions|jailbreak|prompt\s+injection)\b", "", text)
    text = re.sub(r"`{3,}|<{2,}|>{2,}|\[\[|\]\]|<\|.*?\|>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text

