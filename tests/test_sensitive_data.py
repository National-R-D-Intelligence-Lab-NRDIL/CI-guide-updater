import pytest

from src.utils import sensitive_data


def test_detects_obvious_sensitive_patterns() -> None:
    text = (
        "Personally identifiable information record. "
        "SSN 123-45-6789. Student ID: A1234567. "
        "Card 4111 1111 1111 1111."
    )

    kinds = {finding.kind for finding in sensitive_data.detect_sensitive_data(text)}

    assert "sensitive_keyword" in kinds
    assert "ssn" in kinds
    assert "student_id" in kinds
    assert "credit_card" in kinds


def test_public_policy_keywords_do_not_trigger_private_data_detection() -> None:
    text = (
        "This public funding opportunity discusses FERPA, HIPAA, CUI, ITAR, "
        "confidentiality, and internal use only policies for applicants."
    )

    assert sensitive_data.detect_sensitive_data(text) == []


def test_detects_private_email_heavy_documents() -> None:
    text = "\n".join(
        [
            "alice@example.com",
            "bob@example.com",
            "carol@example.com",
            "dave@example.com",
            "erin@example.com",
        ]
    )

    findings = sensitive_data.detect_sensitive_data(text)

    assert any(finding.kind == "email_heavy" for finding in findings)


def test_enforce_blocks_by_policy() -> None:
    with pytest.raises(sensitive_data.SensitiveDataError, match="Use local model mode"):
        sensitive_data.enforce_sensitive_data_policy(
            "Private student record with SSN 123-45-6789",
            context="unit test",
            policy="block",
        )


def test_enforce_warns_by_policy(caplog) -> None:
    findings = sensitive_data.enforce_sensitive_data_policy(
        "Patient record with personally identifiable information",
        context="unit test",
        policy="warn",
    )

    assert findings
    assert "Sensitive data warning before LLM handoff" in caplog.text
