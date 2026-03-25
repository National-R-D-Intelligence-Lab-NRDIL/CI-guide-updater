# CI Sponsor Guide Updater

Automated Python workflow that monitors approved government grant pages, detects meaningful policy changes, and updates a Sponsor Guide with **Google Gemini**.

Built for research development teams that need current deadlines, eligibility rules, and submission requirements without manually re-reading every source page.

## What This Project Does

- **Monitors approved sources** from `sources.json` (e.g. NIH, NSF HTML pages).
- **Tracks content over time** with hash-based snapshots under `data/`.
- **Extracts focused diffs** (added/removed lines) to reduce noise.
- **Updates the guide via Gemini** while preserving markdown structure.
- **Writes outputs** as `output/sponsor_guide_updated.md` and `.docx`.

## Architecture

1. **`scraper.py`** — Fetch URLs, strip scripts/styles, hash text, persist `state.json` and `data/<name>_latest.txt`.
2. **`differ.py`** — Compare old vs new snapshot; emit LLM-friendly deltas.
3. **`updater.py`** — Call Gemini (OpenAI-compatible API) with the current guide + combined diff.
4. **`pipeline.py`** — Orchestrates scrape → diff → update; optional `sections` per source target guide headings for the LLM.

## Project layout

```text
CI-sponsor-guide-updater/
├── pipeline.py
├── scraper.py
├── differ.py
├── updater.py
├── sources.json
├── guides/
│   └── sample_guide.md
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

**Git-ignored (not uploaded):** `.env`, `state.json`, `data/`, `output/`, and `*.docx` / `*.doc` (local guides).

## Quick start

### 1) Install dependencies

```bash
cd CI-sponsor-guide-updater
pip3 install -r requirements.txt
```

On macOS, use `python3` and `pip3` (there is often no `python` command unless you use a venv or install Python from python.org).

### 2) Gemini API key

```bash
cp .env.example .env
```

Edit `.env` in the **project root** (same directory as `pipeline.py`):

```env
GEMINI_API_KEY=your-gemini-api-key
```

The app loads `.env` from that folder even if you run commands from another directory.

Defaults in code:

- Base URL: `https://generativelanguage.googleapis.com/v1beta/openai/`
- Model: `gemini-2.0-flash` (override with `--model`)

### 3) Configure sources

Each entry in `sources.json` supports:

| Field | Meaning |
| --- | --- |
| `name` | Short ID; snapshots go to `data/<name>_latest.txt`. |
| `url` | HTML page to scrape (PDFs are not scraped yet). |
| `sections` | Optional list of guide section titles; included in the diff so Gemini knows where to edit. |

Example:

```json
[
  {
    "name": "NIH_R15_Main",
    "url": "https://grants.nih.gov/funding/activity-codes/R15",
    "sections": ["The R15 Programs", "R15 Resources"]
  }
]
```

The repository includes a fuller NIH R15–oriented `sources.json`; customize for your program.

## Run the pipeline

```bash
python3 pipeline.py guides/sample_guide.md
```

Word guide:

```bash
python3 pipeline.py "guides/Your Sponsor Guide.docx"
```

Options:

```bash
python3 pipeline.py guide.docx \
  --sources sources.json \
  --output output \
  --model gemini-2.0-flash
```

**Behavior:** If no monitored source changes since the last run, the guide is not rewritten.

## Outputs

When changes are detected:

- `output/sponsor_guide_updated.md`
- `output/sponsor_guide_updated.docx`

## Run modules alone

```bash
python3 scraper.py
python3 differ.py
python3 updater.py
```

## Dependencies

See `requirements.txt`. Main pieces: `requests`, `beautifulsoup4`, `openai` (Gemini-compatible client), `mammoth`, `python-docx`, `python-dotenv`.

## Troubleshooting

| Issue | What to do |
| --- | --- |
| `command not found: python` | Use `python3`. |
| Missing packages | `pip3 install -r requirements.txt` in the project folder. |
| `GEMINI_API_KEY` missing | Ensure `.env` exists and contains `GEMINI_API_KEY=...` (not an empty file). |

## Publish to GitHub

From the project root, after reviewing `git status`:

```bash
git add -A
git status   # confirm .env, data/, *.docx are not listed
git commit -m "Describe your changes (e.g. Gemini pipeline, README, sources)"
git push origin main
```

Create the repo on GitHub first if needed, then:

```bash
git remote add origin https://github.com/<your-username>/<your-repo>.git
git branch -M main
git push -u origin main
```

Never commit `.env` or API keys; they stay in `.gitignore`.
