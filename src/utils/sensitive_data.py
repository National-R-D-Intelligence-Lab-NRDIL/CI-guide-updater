"""Sensitive-data detection before external LLM handoffs."""

from __future__ import annotations

from dataclasses import dataclass
import logging
import re
from urllib.parse import urlsplit

from src.utils.secrets import get_secret


SENSITIVE_DATA_MESSAGE = (
    "This source may contain private data. Use local model mode or remove it."
)
VALID_POLICIES = {"block", "warn", "off"}

logger = logging.getLogger(__name__)
CONTEXTUAL_PUBLIC_FINDING_KINDS = {"email_heavy", "sensitive_keyword"}

_SSN_RE = re.compile(
    r"(?<!\d)(?:\d{3}[-\s]\d{2}[-\s]\d{4}|(?:ssn|social security number)\s*[:#-]?\s*\d{9})(?!\d)",
    re.IGNORECASE,
)
_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@([A-Z0-9.-]+\.[A-Z]{2,})\b", re.IGNORECASE)
_STUDENT_ID_RE = re.compile(
    r"\b(?:student|sid|university|campus)\s*(?:id|number|no\.?|#)\s*[:#-]?\s*"
    r"([A-Z]?\d{6,10}|\d{3,4}[-\s]\d{3,6})\b",
    re.IGNORECASE,
)
_CREDIT_CARD_RE = re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")
_PRIVATE_KEYWORD_RE = re.compile(
    r"\b(private student record|protected health information|patient record|"
    r"medical record|personally identifiable information|PII)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SensitiveDataFinding:
    """A redacted finding category from a sensitive-data scan."""

    kind: str
    label: str
    count: int


class SensitiveDataError(ValueError):
    """Raised when sensitive data policy blocks an LLM handoff."""

    def __init__(self, context: str, findings: list[SensitiveDataFinding]) -> None:
        self.context = context
        self.findings = findings
        summary = format_sensitive_data_summary(findings)
        detail = f" {summary}" if summary else ""
        super().__init__(f"{context}: {SENSITIVE_DATA_MESSAGE}{detail}")


def _luhn_valid(value: str) -> bool:
    digits = [int(ch) for ch in re.sub(r"\D", "", value)]
    if len(digits) < 13 or len(digits) > 19:
        return False
    checksum = 0
    parity = len(digits) % 2
    for idx, digit in enumerate(digits):
        if idx % 2 == parity:
            digit *= 2
            if digit > 9:
                digit -= 9
        checksum += digit
    return checksum % 10 == 0


def _private_email_count(text: str) -> int:
    domains = [match.group(1).lower() for match in _EMAIL_RE.finditer(text)]
    private_domains = [
        domain
        for domain in domains
        if not (
            domain.endswith(".gov")
            or domain.endswith(".edu")
            or domain.endswith(".mil")
        )
    ]
    if len(domains) >= 12:
        return len(domains)
    if len(private_domains) >= 5:
        return len(private_domains)
    return 0


def detect_sensitive_data(text: str) -> list[SensitiveDataFinding]:
    """Return redacted sensitive-data findings for obvious risky patterns."""
    content = str(text or "")
    findings: list[SensitiveDataFinding] = []

    ssns = _SSN_RE.findall(content)
    if ssns:
        findings.append(SensitiveDataFinding("ssn", "SSN-like number", len(ssns)))

    student_ids = _STUDENT_ID_RE.findall(content)
    if student_ids:
        findings.append(
            SensitiveDataFinding("student_id", "student ID-like number", len(student_ids))
        )

    credit_cards = [
        candidate
        for candidate in _CREDIT_CARD_RE.findall(content)
        if _luhn_valid(candidate)
    ]
    if credit_cards:
        findings.append(
            SensitiveDataFinding(
                "credit_card",
                "credit card-like number",
                len(credit_cards),
            )
        )

    private_emails = _private_email_count(content)
    if private_emails:
        findings.append(
            SensitiveDataFinding(
                "email_heavy",
                "private email-heavy document",
                private_emails,
            )
        )

    keywords = _PRIVATE_KEYWORD_RE.findall(content)
    if keywords:
        findings.append(
            SensitiveDataFinding(
                "sensitive_keyword",
                "private-data keyword",
                len(keywords),
            )
        )

    return findings


def format_sensitive_data_summary(findings: list[SensitiveDataFinding]) -> str:
    """Return a redacted human-readable summary of finding categories."""
    if not findings:
        return ""
    labels = ", ".join(f"{finding.label} ({finding.count})" for finding in findings)
    return f"Detected: {labels}."


def format_sensitive_data_error(exc: SensitiveDataError) -> tuple[str, str]:
    """Return UI-safe message/detail for a blocked sensitive-data handoff."""
    summary = format_sensitive_data_summary(exc.findings)
    detail_parts = []
    if exc.context:
        detail_parts.append(f"Blocked source/context: {exc.context}.")
    if summary:
        detail_parts.append(summary)
    return SENSITIVE_DATA_MESSAGE, " ".join(detail_parts)


def _is_local_model_mode() -> bool:
    provider = get_secret("LLM_PROVIDER").strip().lower()
    local_mode = get_secret("LLM_LOCAL_MODE").strip().lower()
    base_url = get_secret("LLM_BASE_URL").strip()
    if provider in {"local", "ollama", "lmstudio", "llama.cpp"}:
        return True
    if local_mode in {"1", "true", "yes", "on"}:
        return True
    if base_url:
        host = (urlsplit(base_url).hostname or "").lower()
        return host in {"localhost", "127.0.0.1", "::1"}
    return False


def get_sensitive_data_policy() -> str:
    """Return configured policy: block, warn, or off."""
    configured = get_secret("SENSITIVE_DATA_POLICY").strip().lower()
    if configured:
        if configured not in VALID_POLICIES:
            raise ValueError(
                "Invalid SENSITIVE_DATA_POLICY. Use one of: block, warn, off."
            )
        return configured
    return "warn" if _is_local_model_mode() else "block"


def enforce_sensitive_data_policy(
    text: str,
    *,
    context: str,
    policy: str | None = None,
    allow_public_contextual_findings: bool = False,
) -> list[SensitiveDataFinding]:
    """Scan text and either block or warn according to configuration."""
    active_policy = (policy or get_sensitive_data_policy()).strip().lower()
    if active_policy not in VALID_POLICIES:
        raise ValueError("Sensitive data policy must be one of: block, warn, off.")
    if active_policy == "off":
        return []

    findings = detect_sensitive_data(text)
    if not findings:
        return []

    summary = format_sensitive_data_summary(findings)
    contextual_only = all(
        finding.kind in CONTEXTUAL_PUBLIC_FINDING_KINDS
        for finding in findings
    )
    should_warn_for_public_context = (
        active_policy == "block"
        and allow_public_contextual_findings
        and contextual_only
    )
    if active_policy == "block" and not should_warn_for_public_context:
        raise SensitiveDataError(context, findings)

    logger.warning(
        "Sensitive data warning before LLM handoff. context=%s message=%s summary=%s",
        context,
        SENSITIVE_DATA_MESSAGE,
        summary,
    )
    return findings
