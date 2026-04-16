# Program directories

Each subfolder here is **one grant program** (a filesystem-safe slug, e.g. `nih_r15`, `nsf_career_award`).

## What belongs where

| Path | Role |
|------|------|
| `sources.json` | Approved URLs, labels, `data_class`, and optional `sections` — **commit this** (your source of truth). |
| `guide.md` **or** `*.docx` | Baseline sponsor guide before automation. Word files are git-ignored by repo policy. |
| `output/` | Pipeline output: `sponsor_guide_updated.md`, `.docx`, `.pdf`, `sponsor_guide_evidence.json` — **git-ignored** (regenerate with `pipeline.py`). |
| `state.json` | Per-URL content hashes for change detection — **git-ignored**. |
| `data/` | Cached scraped text (`*_latest.txt`) — **git-ignored**. |
| `review/` | Bootstrap / interactive review staging (`draft_guide.md`, `sources_pending.json`) — **git-ignored**. |
| `review_packages/` | Local copies of async shared-folder review packages — **git-ignored**; safe to delete when a review is collected. |
| `internal_sources.json` | Optional internal-only source list for local workflows — **never commit**; hard-blocked by root `.gitignore`. |

## Tidiness

- Do not commit runtime folders (`output/`, `data/`, `state.json`, `review/`, `review_packages/`); they are listed in the root `.gitignore`.
- Treat `internal_sources.json` as internal-only data. Keep it local and out of PRs.
- After you finalize a program, you may delete `review/` and `review_packages/` locally if you no longer need them; the pipeline will recreate `review/` on the next bootstrap if needed.
- Avoid dropping loose test PDFs or scratch files under `output/` — use a temp directory outside the repo for experiments.

## Adding a program

Use `bootstrap.py` (see the main project `README.md`) so the slug, paths, and review layout stay consistent.
