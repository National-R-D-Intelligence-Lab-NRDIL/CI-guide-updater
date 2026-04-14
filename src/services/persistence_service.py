"""Runtime persistence helpers for Streamlit Cloud workflows.

Local filesystem writes are always supported. When configured, this module also
syncs `programs/<slug>/` to a GitHub repository path so workflow artifacts can
be restored in future sessions.
"""

from __future__ import annotations

import base64
import os
import time
from pathlib import Path
from typing import Any

import requests

from src.utils.secrets import get_secret


_API_BASE = "https://api.github.com"
_DEFAULT_BRANCH = "runtime-data"
_DEFAULT_PREFIX = "runtime/programs"
_SYNC_INTERVAL_SECONDS = 20
_CACHE: dict[str, Any] = {
    "slug_list_at": 0.0,
    "slug_list": [],
    "hydrated_at": {},
}


def _backend() -> str:
    return str(os.getenv("RUNTIME_STORAGE_BACKEND", "local")).strip().lower() or "local"


def _config() -> dict[str, str]:
    return {
        "repo": str(os.getenv("RUNTIME_STORAGE_GITHUB_REPO", "")).strip(),
        "token": get_secret("RUNTIME_STORAGE_GITHUB_TOKEN"),
        "branch": str(os.getenv("RUNTIME_STORAGE_GITHUB_BRANCH", _DEFAULT_BRANCH)).strip() or _DEFAULT_BRANCH,
        "prefix": str(os.getenv("RUNTIME_STORAGE_GITHUB_PREFIX", _DEFAULT_PREFIX)).strip("/"),
    }


def is_remote_enabled() -> bool:
    cfg = _config()
    return _backend() == "github" and bool(cfg["repo"] and cfg["token"])


def storage_summary() -> dict[str, Any]:
    cfg = _config()
    return {
        "backend": _backend(),
        "remote_enabled": is_remote_enabled(),
        "repo": cfg["repo"],
        "branch": cfg["branch"],
        "prefix": cfg["prefix"],
    }


def _headers() -> dict[str, str]:
    cfg = _config()
    return {
        "Authorization": f"Bearer {cfg['token']}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _api_url(path: str) -> str:
    return f"{_API_BASE}{path}"


def _github_request(method: str, path: str, *, json_body: dict[str, Any] | None = None) -> requests.Response:
    response = requests.request(
        method=method,
        url=_api_url(path),
        headers=_headers(),
        json=json_body,
        timeout=30,
    )
    return response


def _repo_parts() -> tuple[str, str]:
    cfg = _config()
    if "/" not in cfg["repo"]:
        raise ValueError("RUNTIME_STORAGE_GITHUB_REPO must be in owner/repo format.")
    owner, repo = cfg["repo"].split("/", 1)
    return owner, repo


def _ensure_branch() -> None:
    owner, repo = _repo_parts()
    cfg = _config()
    branch = cfg["branch"]

    branch_resp = _github_request("GET", f"/repos/{owner}/{repo}/branches/{branch}")
    if branch_resp.status_code == 200:
        return
    if branch_resp.status_code not in {404, 422}:
        raise RuntimeError(f"Unable to check branch {branch}: {branch_resp.status_code} {branch_resp.text}")

    repo_resp = _github_request("GET", f"/repos/{owner}/{repo}")
    if repo_resp.status_code != 200:
        raise RuntimeError(f"Unable to read repository metadata: {repo_resp.status_code} {repo_resp.text}")
    default_branch = repo_resp.json().get("default_branch")
    if not default_branch:
        raise RuntimeError("Repository default branch not found.")

    default_resp = _github_request("GET", f"/repos/{owner}/{repo}/branches/{default_branch}")
    if default_resp.status_code != 200:
        raise RuntimeError(
            f"Unable to read default branch '{default_branch}': {default_resp.status_code} {default_resp.text}"
        )
    sha = default_resp.json().get("commit", {}).get("sha")
    if not sha:
        raise RuntimeError("Default branch HEAD SHA not found.")

    create_resp = _github_request(
        "POST",
        f"/repos/{owner}/{repo}/git/refs",
        json_body={"ref": f"refs/heads/{branch}", "sha": sha},
    )
    if create_resp.status_code not in {201, 422}:
        raise RuntimeError(f"Unable to create branch {branch}: {create_resp.status_code} {create_resp.text}")


def _remote_program_root(slug: str) -> str:
    cfg = _config()
    return f"{cfg['prefix']}/{slug}".strip("/")


def _remote_file_path(slug: str, rel_path: Path) -> str:
    return f"{_remote_program_root(slug)}/{rel_path.as_posix()}".strip("/")


def _github_browse_url(remote_path: str) -> str:
    cfg = _config()
    return f"https://github.com/{cfg['repo']}/blob/{cfg['branch']}/{remote_path}"


def program_remote_url(slug: str) -> str:
    if not is_remote_enabled():
        return ""
    return _github_browse_url(_remote_program_root(slug))


def _list_dir(path: str) -> list[dict[str, Any]]:
    owner, repo = _repo_parts()
    cfg = _config()
    resp = _github_request("GET", f"/repos/{owner}/{repo}/contents/{path}?ref={cfg['branch']}")
    if resp.status_code == 404:
        return []
    if resp.status_code != 200:
        raise RuntimeError(f"Unable to list {path}: {resp.status_code} {resp.text}")
    payload = resp.json()
    return payload if isinstance(payload, list) else []


def _walk_remote_files(path: str) -> list[str]:
    files: list[str] = []
    for item in _list_dir(path):
        item_type = item.get("type", "")
        item_path = item.get("path", "")
        if item_type == "file" and item_path:
            files.append(str(item_path))
        elif item_type == "dir" and item_path:
            files.extend(_walk_remote_files(str(item_path)))
    return files


def _get_file_content(remote_path: str) -> bytes:
    owner, repo = _repo_parts()
    cfg = _config()
    resp = _github_request("GET", f"/repos/{owner}/{repo}/contents/{remote_path}?ref={cfg['branch']}")
    if resp.status_code != 200:
        raise RuntimeError(f"Unable to read {remote_path}: {resp.status_code} {resp.text}")
    payload = resp.json()
    encoded = str(payload.get("content", "")).replace("\n", "")
    if not encoded:
        return b""
    return base64.b64decode(encoded)


def _upsert_file(remote_path: str, content: bytes, message: str) -> None:
    owner, repo = _repo_parts()
    cfg = _config()
    existing_sha = None
    read_resp = _github_request("GET", f"/repos/{owner}/{repo}/contents/{remote_path}?ref={cfg['branch']}")
    if read_resp.status_code == 200:
        existing_sha = read_resp.json().get("sha")
    elif read_resp.status_code != 404:
        raise RuntimeError(f"Unable to check {remote_path}: {read_resp.status_code} {read_resp.text}")

    payload: dict[str, Any] = {
        "message": message,
        "branch": cfg["branch"],
        "content": base64.b64encode(content).decode("utf-8"),
    }
    if existing_sha:
        payload["sha"] = existing_sha

    write_resp = _github_request("PUT", f"/repos/{owner}/{repo}/contents/{remote_path}", json_body=payload)
    if write_resp.status_code not in {200, 201}:
        raise RuntimeError(f"Unable to write {remote_path}: {write_resp.status_code} {write_resp.text}")


def _delete_file(remote_path: str, message: str) -> None:
    owner, repo = _repo_parts()
    cfg = _config()
    read_resp = _github_request("GET", f"/repos/{owner}/{repo}/contents/{remote_path}?ref={cfg['branch']}")
    if read_resp.status_code == 404:
        return
    if read_resp.status_code != 200:
        raise RuntimeError(f"Unable to read {remote_path}: {read_resp.status_code} {read_resp.text}")
    sha = read_resp.json().get("sha")
    if not sha:
        return
    payload = {"message": message, "sha": sha, "branch": cfg["branch"]}
    del_resp = _github_request("DELETE", f"/repos/{owner}/{repo}/contents/{remote_path}", json_body=payload)
    if del_resp.status_code not in {200, 404}:
        raise RuntimeError(f"Unable to delete {remote_path}: {del_resp.status_code} {del_resp.text}")


def list_program_slugs() -> list[str]:
    local_root = Path("programs")
    local = {p.name for p in local_root.iterdir() if p.is_dir()} if local_root.exists() else set()
    if not is_remote_enabled():
        return sorted(local)

    now = time.time()
    if now - float(_CACHE["slug_list_at"]) < _SYNC_INTERVAL_SECONDS:
        remote = set(_CACHE["slug_list"])
        return sorted(local | remote)

    try:
        _ensure_branch()
        remote = {
            str(item.get("name", ""))
            for item in _list_dir(_config()["prefix"])
            if item.get("type") == "dir" and item.get("name")
        }
        _CACHE["slug_list_at"] = now
        _CACHE["slug_list"] = sorted(remote)
        return sorted(local | remote)
    except Exception:
        return sorted(local)


def hydrate_program(slug: str, *, force: bool = False) -> dict[str, Any]:
    """Download one program directory from remote storage into local `programs/`."""
    if not slug.strip():
        return {"ok": False, "enabled": is_remote_enabled(), "message": "Missing slug."}
    if not is_remote_enabled():
        return {"ok": True, "enabled": False, "message": "Remote persistence disabled."}

    now = time.time()
    hydrated_at = float(_CACHE["hydrated_at"].get(slug, 0.0))
    if not force and now - hydrated_at < _SYNC_INTERVAL_SECONDS:
        return {"ok": True, "enabled": True, "message": "Hydration skipped (recent)."}

    try:
        _ensure_branch()
        local_program = Path("programs") / slug
        local_program.mkdir(parents=True, exist_ok=True)
        remote_root = _remote_program_root(slug)
        remote_files = _walk_remote_files(remote_root)
        if not remote_files:
            _CACHE["hydrated_at"][slug] = now
            return {
                "ok": True,
                "enabled": True,
                "message": "No remote files found for this program; local files unchanged.",
                "remote_url": program_remote_url(slug),
            }

        remote_relatives: set[str] = set()
        synced = 0
        for remote_path in remote_files:
            if not remote_path.startswith(f"{remote_root}/"):
                continue
            relative = remote_path[len(remote_root) + 1 :]
            remote_relatives.add(relative)
            local_path = local_program / Path(relative)
            local_path.parent.mkdir(parents=True, exist_ok=True)
            local_path.write_bytes(_get_file_content(remote_path))
            synced += 1

        removed_local = 0
        for local_path in local_program.rglob("*"):
            if not local_path.is_file():
                continue
            rel = local_path.relative_to(local_program).as_posix()
            if rel not in remote_relatives:
                local_path.unlink()
                removed_local += 1

        _CACHE["hydrated_at"][slug] = now
        return {
            "ok": True,
            "enabled": True,
            "message": f"Hydrated {synced} file(s) from remote storage; removed {removed_local} stale local file(s).",
            "remote_url": program_remote_url(slug),
        }
    except Exception as exc:
        return {"ok": False, "enabled": True, "message": "Hydration failed.", "detail": str(exc)}


def persist_program(slug: str) -> dict[str, Any]:
    """Upload local `programs/<slug>/` files and remove stale remote files."""
    if not slug.strip():
        return {"ok": False, "enabled": is_remote_enabled(), "message": "Missing slug."}
    if not is_remote_enabled():
        return {"ok": True, "enabled": False, "message": "Remote persistence disabled."}

    try:
        _ensure_branch()
        local_program = Path("programs") / slug
        if not local_program.exists():
            return {"ok": False, "enabled": True, "message": f"Local directory not found: {local_program}"}

        local_paths: list[Path] = []
        for path in local_program.rglob("*"):
            if path.is_file():
                local_paths.append(path)

        uploaded = 0
        local_remote_set: set[str] = set()
        for local_path in local_paths:
            rel = local_path.relative_to(local_program)
            remote_path = _remote_file_path(slug, rel)
            local_remote_set.add(remote_path)
            _upsert_file(remote_path, local_path.read_bytes(), f"Sync runtime file: {slug}/{rel.as_posix()}")
            uploaded += 1

        remote_root = _remote_program_root(slug)
        remote_paths = set(_walk_remote_files(remote_root))
        deleted = 0
        for remote_path in sorted(remote_paths - local_remote_set):
            _delete_file(remote_path, f"Remove stale runtime file: {remote_path}")
            deleted += 1

        _CACHE["hydrated_at"][slug] = time.time()
        return {
            "ok": True,
            "enabled": True,
            "message": f"Synced {uploaded} file(s) to remote storage.",
            "uploaded_count": uploaded,
            "deleted_count": deleted,
            "remote_url": program_remote_url(slug),
        }
    except Exception as exc:
        return {"ok": False, "enabled": True, "message": "Remote sync failed.", "detail": str(exc)}


def persist_paths(slug: str, relative_paths: list[str]) -> dict[str, Any]:
    """Sync only selected files for a program.

    Use this for high-frequency operations so we do not re-upload entire program
    trees after each small metadata edit.
    """
    if not slug.strip():
        return {"ok": False, "enabled": is_remote_enabled(), "message": "Missing slug."}
    if not is_remote_enabled():
        return {"ok": True, "enabled": False, "message": "Remote persistence disabled."}

    try:
        _ensure_branch()
        local_program = Path("programs") / slug
        if not local_program.exists():
            return {"ok": False, "enabled": True, "message": f"Local directory not found: {local_program}"}

        synced = 0
        deleted = 0
        for rel in relative_paths:
            rel_path = Path(rel)
            local_path = local_program / rel_path
            remote_path = _remote_file_path(slug, rel_path)
            if local_path.exists() and local_path.is_file():
                _upsert_file(remote_path, local_path.read_bytes(), f"Sync runtime file: {slug}/{rel_path.as_posix()}")
                synced += 1
            else:
                _delete_file(remote_path, f"Remove runtime file: {remote_path}")
                deleted += 1

        _CACHE["hydrated_at"][slug] = time.time()
        return {
            "ok": True,
            "enabled": True,
            "message": f"Synced {synced} file(s); deleted {deleted}.",
            "uploaded_count": synced,
            "deleted_count": deleted,
            "remote_url": program_remote_url(slug),
        }
    except Exception as exc:
        return {"ok": False, "enabled": True, "message": "Remote sync failed.", "detail": str(exc)}
