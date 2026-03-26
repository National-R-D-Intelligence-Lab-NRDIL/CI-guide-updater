# CI Sponsor Guide Updater

Automated Python tool that monitors government grant websites, detects policy changes, and keeps your Sponsor Guides up to date using **Google Gemini**.

Built for research development teams — no coding experience required to run the day-to-day workflow.

---

## Table of Contents

1. [How It Works](#how-it-works)
2. [Quick Start](#quick-start)
3. [Onboard a New Grant Program](#onboard-a-new-grant-program)
4. [Run the Weekly Update](#run-the-weekly-update)
5. [Human Review (Interactive)](#human-review-interactive)
6. [Adding a New Link During Review](#adding-a-new-link-during-review)
7. [Project Layout](#project-layout)
8. [Sources Format](#sources-format)
9. [Modules Reference](#modules-reference)
10. [Troubleshooting](#troubleshooting)
11. [Git / GitHub Notes](#git--github-notes)

---

## How It Works

```
┌──────────────────────────────────────────────────────────────┐
│                  One-time setup (per program)                │
│                                                              │
│  1. DISCOVER  — Gemini searches the web for official pages   │
│  2. GENERATE  — Scrape those pages → draft a Sponsor Guide   │
│  3. REVIEW    — Human expert approves/edits/adds sources     │
└──────────────────────────────────────────────────────────────┘
                            ▼
┌──────────────────────────────────────────────────────────────┐
│              Weekly update (automated / scheduled)            │
│                                                              │
│  4. SCRAPE    — Re-fetch every approved source page          │
│  5. DIFF      — Compare against the last snapshot            │
│  6. UPDATE    — Gemini rewrites only the changed sections    │
│  7. OUTPUT    — Save updated guide as .md and .docx          │
└──────────────────────────────────────────────────────────────┘
```

**Key feature:** You never need to manually specify which guide sections a link relates to. Gemini reads the page content and the guide headings, then figures out the mapping automatically.

---

## Quick Start

### 1. Install Python dependencies

```bash
pip3 install -r requirements.txt
```

> **macOS note:** Use `python3` / `pip3`. There is usually no bare `python` command unless you are inside a virtual environment.

### 2. Set up your Gemini API key

```bash
cp .env.example .env
```

Open `.env` and paste your key:

```
GEMINI_API_KEY=your-gemini-api-key-here
```

You can get a free API key at [https://aistudio.google.com/apikey](https://aistudio.google.com/apikey).

### 3. You're ready!

Continue to the next section to onboard your first grant program.

---

## Onboard a New Grant Program

Use this whenever you want to start tracking a new funding program (e.g. NIH R01, NSF CAREER, NIH R15).

### Step 1 — Run the bootstrap command

```bash
python3 bootstrap.py "NSF CAREER award"
```

The tool will:
1. Search the web for official program pages
2. Validate every URL it finds
3. Scrape the valid pages and draft a Sponsor Guide
4. Walk you through an interactive review (see [Human Review](#human-review-interactive))

Everything is saved into a single program folder under `programs/`:

```
programs/nsf_career_award/
├── sources.json                ← approved source links
├── guide.md                    ← baseline Sponsor Guide
└── review/                     ← (git-ignored) review artifacts
    ├── sources_pending.json
    └── draft_guide.md
```

The folder name is derived automatically from the program name you provide (lowercased, spaces/special characters become underscores).

### Step 2 — Review the draft guide

Open `programs/<slug>/guide.md` in any text editor and make corrections if needed. This becomes your baseline.

### Step 3 — Run the first weekly update

```bash
python3 pipeline.py programs/nsf_career_award/guide.md \
    --sources programs/nsf_career_award/sources.json
```

From now on, re-run this command at any time (or schedule it weekly) to keep the guide current.

---

## Run the Weekly Update

This is the core command you will use regularly:

```bash
python3 pipeline.py programs/<slug>/guide.md \
    --sources programs/<slug>/sources.json
```

**Examples:**

```bash
# NSF CAREER
python3 pipeline.py programs/nsf_career/guide.md \
    --sources programs/nsf_career/sources.json

# NIH R15 (guide is a .docx file)
python3 pipeline.py programs/nih_r15/NIH_R15_Sponsor_Guide_0325.docx \
    --sources programs/nih_r15/sources.json
```

**What happens:**

| Step | What the tool does |
|------|--------------------|
| 1 | Re-scrape every URL in `sources.json` |
| 2 | Compare each page against its last snapshot |
| 3 | If anything changed, send the diff to Gemini |
| 4 | Gemini rewrites only the affected sections |
| 5 | Save the result to `output/sponsor_guide_updated.md` and `.docx` |

If no changes are found, the tool prints "All sources unchanged" and exits — nothing is overwritten.

Runtime files (`state.json`, `data/`) are stored inside the program folder and are git-ignored.

---

## Human Review (Interactive)

During bootstrap, the tool presents each discovered source one at a time with a numbered menu:

```
  [1/5]  NSF_CAREER_award_CAREER_Program_Overview
           URL:      https://www.nsf.gov/funding/...
           Sections: 2. Program Overview, 3. Key Dates

    1  Approve this source
    2  Reject this source
    3  Edit the URL for this source
    4  Add a new link (not in the list)
    5  Show approved sources so far
    6  Done — finish review

  Your choice (1-6):
```

Just type a number and press Enter. No coding or JSON editing required.

| Choice | What it does |
|--------|-------------|
| **1** | Keep this source as-is |
| **2** | Remove this source from the list |
| **3** | Replace the URL (the tool re-validates and re-detects sections automatically) |
| **4** | Add a brand-new link you found yourself (see below) |
| **5** | Print a summary of everything you've approved so far |
| **6** | Stop reviewing early and keep what you've approved |

After all sources are reviewed, you get one more prompt:

```
  Add another link before finishing? (y/n):
```

---

## Adding a New Link During Review

Choose option **4** at any time during the review. The tool will ask:

```
  Paste the URL: https://grants.nih.gov/grants/guide/notice-files/NOT-OD-25-001.html
  Checking URL ...
  ✓ Reachable
  Short label (e.g. 'Program FAQ'): Budget Policy Update
  Detecting relevant guide sections ...
  Auto-detected sections: 7. Budget, 8. Allowable Costs
  ✓ Added: NIH_R01_Budget_Policy_Update
```

**What happens behind the scenes:**

1. The tool checks the URL is reachable
2. You give it a short label (just a few words — used for filenames)
3. The tool scrapes the page and asks Gemini which guide sections it relates to
4. The new link is added to the review queue

You **do not** need to know the guide section names or edit any JSON files. Gemini figures out the section mapping automatically.

> **Tip:** If Gemini can't detect sections (e.g. the page is sparse), that's fine. The weekly pipeline will re-attempt auto-detection when it runs.

---

## Project Layout

```
CI-sponsor-guide-updater/
├── bootstrap.py         ← Onboard a new program (discover → generate → review)
├── pipeline.py          ← Weekly update runner (scrape → diff → update)
├── scraper.py           ← Fetch + clean web pages, manage snapshots
├── differ.py            ← Extract meaningful text changes
├── updater.py           ← LLM-powered guide rewriting + section classification
├── discover.py          ← Find candidate source URLs via Gemini + Google Search
├── generator.py         ← Generate a first-draft guide from scraped sources
├── review.py            ← Interactive human review CLI
├── requirements.txt     ← Python dependencies
├── .env.example         ← Template for API key
├── .env                 ← Your actual API key (git-ignored)
└── programs/            ← One folder per grant program
    ├── nih_r15/
    │   ├── sources.json
    │   ├── guide.md or *.docx     (baseline guide)
    │   ├── state.json             (git-ignored, runtime)
    │   └── data/                  (git-ignored, runtime)
    └── nsf_career/
        ├── sources.json
        ├── guide.md
        ├── state.json             (git-ignored, runtime)
        ├── data/                  (git-ignored, runtime)
        └── review/                (git-ignored, review artifacts)
            ├── sources_pending.json
            └── draft_guide.md
```

Every program's files live together in one folder. Nothing is written to the project root.

**Git-ignored files** (not uploaded to the repository):
- `.env` — API key
- `programs/**/state.json` and `programs/**/data/` — runtime snapshots
- `programs/**/review/` — review artifacts
- `output/` — generated guides
- `*.docx`, `*.doc` — Word files

---

## Sources Format

Each program's `sources.json` is a simple list:

```json
[
  {
    "name": "NIH_R15_Main_Page",
    "url": "https://grants.nih.gov/grants/funding/r15.htm",
    "sections": ["2. Program Overview", "4. Eligibility"]
  },
  {
    "name": "NIH_R15_Due_Dates",
    "url": "https://grants.nih.gov/grants/how-to-apply-application-guide/due-dates.htm",
    "sections": []
  }
]
```

| Field | Required | Description |
|-------|----------|-------------|
| `name` | Yes | Unique ID used for snapshot filenames |
| `url` | Yes | The web page to scrape (HTML only, no PDFs) |
| `sections` | No | Guide sections this source maps to. **Leave empty** — Gemini detects them automatically |

---

## Modules Reference

| Module | Purpose |
|--------|---------|
| `scraper.py` | Fetch web pages, strip HTML, generate content hashes, manage `state.json` snapshots |
| `differ.py` | Compare old vs new text and produce a structured summary of additions/removals |
| `updater.py` | Send guide + diff to Gemini, get back the updated guide. Also provides `classify_sections()` for auto-detecting which guide sections a page relates to |
| `pipeline.py` | Orchestrate the weekly workflow: load sources → scrape → diff → LLM update → save output |
| `discover.py` | Use Gemini + Google Search grounding to find candidate source URLs for a program |
| `generator.py` | Scrape discovered pages and ask Gemini to draft a first Sponsor Guide |
| `review.py` | Menu-driven CLI for human experts to approve, reject, edit, and add source links |
| `bootstrap.py` | End-to-end orchestrator: discover → validate → generate → review → finalize |

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `zsh: command not found: python` | Use `python3` instead (macOS default) |
| `GEMINI_API_KEY is not set` | Make sure `.env` exists in the project root and contains `GEMINI_API_KEY=...` |
| `.env` file exists but key not loaded | Confirm the file is not empty (`cat .env`). Re-copy from `.env.example` if needed |
| `ModuleNotFoundError` | Run `pip3 install -r requirements.txt` |
| URL marked "not reachable" during review | The page may be temporarily down or require special access. You can still add it — the pipeline will retry later |
| Gemini can't detect sections | That's OK. The pipeline will try again on the next weekly run, or you can manually add `sections` to `sources.json` |
| `404 NOT_FOUND` for model | The default model may have changed. Check `updater.py` for `DEFAULT_MODEL` and update if needed |

---

## Git / GitHub Notes

Files that are **not** committed (by `.gitignore`):
- `.env` — API key
- `programs/**/state.json`, `programs/**/data/`, `programs/**/review/` — runtime artifacts
- `output/` — generated guides
- `*.docx`, `*.doc` — Word files

To publish:

```bash
git status          # confirm sensitive files are not listed
git add -A
git commit -m "your commit message"
git push origin main
```
