from pathlib import Path
import json
import re

import pytest

from src.utils import source_policy


def _write_config(path: Path, domains: list[object]) -> None:
    path.write_text(json.dumps({"foundation_domains": domains}), encoding="utf-8")


def test_load_foundation_allowlist_happy_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = tmp_path / "trusted_domains.json"
    _write_config(config_path, ["gatesfoundation.org", "wellcome.org"])

    monkeypatch.setattr(source_policy, "_TRUSTED_DOMAINS_PATH", config_path)
    source_policy._load_foundation_allowlist.cache_clear()

    assert source_policy._load_foundation_allowlist() == frozenset({"gatesfoundation.org", "wellcome.org"})


@pytest.mark.parametrize("bad_entry", ["UpperCase.org", "example.com/path", "*.example.org"])
def test_load_foundation_allowlist_rejects_invalid_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, bad_entry: str
) -> None:
    config_path = tmp_path / "trusted_domains.json"
    _write_config(config_path, [bad_entry])

    monkeypatch.setattr(source_policy, "_TRUSTED_DOMAINS_PATH", config_path)
    source_policy._load_foundation_allowlist.cache_clear()

    escaped = re.escape(f"Invalid trusted domain entry: '{bad_entry}'")
    with pytest.raises(RuntimeError, match=escaped):
        source_policy._load_foundation_allowlist()


def test_load_foundation_allowlist_missing_file_raises_runtime_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing_path = tmp_path / "does-not-exist.json"

    monkeypatch.setattr(source_policy, "_TRUSTED_DOMAINS_PATH", missing_path)
    source_policy._load_foundation_allowlist.cache_clear()

    with pytest.raises(RuntimeError, match="Trusted domains config is missing"):
        source_policy._load_foundation_allowlist()
