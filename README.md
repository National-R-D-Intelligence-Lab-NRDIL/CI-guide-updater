# CI Sponsor Guide Tool

CI Sponsor Guide Tool helps teams discover, review, and keep grant sponsor guides current. It monitors official funding websites, detects changes, and regenerates guide output with citation support using Google Gemini.

It is designed for non-developers to use in day-to-day work, while still staying fully scriptable from the command line.

## What It Does

1. Finds official source pages for a grant program.
2. Helps reviewers approve, reject, or add links.
3. Builds a baseline sponsor guide.
4. Runs weekly updates to detect website changes.
5. Exports updated `.md`, `.docx`, and `.pdf` files.

## Workflow

```text
One-time setup per program
  Discover -> Generate draft -> Review sources -> Finalize baseline

Weekly update
  Scrape -> Diff -> Update guide -> Export outputs
```

You do not need to manually map links to guide sections. The tool reads the source content and guide headings, then auto-detects the best section matches.

## Quick Start

### 1. Install dependencies

```bash
pip3 install -r requirements.txt
```

On macOS, use `python3` and `pip3`. A bare `python` command is often not available unless you are inside a virtual environment.

### 2. Add your Gemini API key

```bash
cp .env.example .env
```

Then edit `.env` and add:

```env
GEMINI_API_KEY=your-gemini-api-key-here
```

You can get a key from [Google AI Studio](https://aistudio.google.com/apikey).

### 3. Launch the UI or use the CLI

To open the Streamlit app:

```bash
streamlit run app/main.py
```

## Streamlit App

The Streamlit app gives you a guided workflow over the same files used by the CLI.

Available pages:

- Create New Program
- Review Sources
- Run Weekly Update
- Outputs
- Audit / Evidence

Use the UI if you want a more visual, step-by-step experience. It reads and writes the same artifacts under `programs/<slug>/`, so the CLI and UI stay in sync.

## Common Tasks

### Create a new grant program

Use this when onboarding a new funding opportunity such as NIH R01, NIH R15, or NSF CAREER.

```bash
python3 bootstrap.py "NSF CAREER award"
```

This will:

1. Search for official source pages.
2. Validate the URLs it finds.
3. Scrape the pages and draft a sponsor guide.
4. Start the review flow so an expert can approve the source list.

The result is stored in a program folder like:

```text
programs/nsf_career_award/
├── sources.json
├── guide.md
└── review/
    ├── sources_pending.json
    └── draft_guide.md
```

### Review sources interactively

Bootstrap uses a simple menu so reviewers can approve, reject, edit, or add links without touching JSON by hand.

Typical choices include:

- Approve a source
- Reject a source
- Edit the URL
- Add a new link
- Finish review early

If you add a new link during review, the tool checks the URL, scrapes the page, and auto-detects the guide sections it belongs to.

### Use async shared-folder review

Use this path when your team reviews sources in OneDrive, Teams, or another shared folder.

```bash
python3 bootstrap.py "NSF Faculty Early Career Development (CAREER) Program" \
  --async-review \
  --shared-review-dir "/Users/<you>/OneDrive - <Org>/Grant-Review"
```

This creates a review package containing:

- `sources_pending.json`
- `draft_guide.md`
- `manifest.json`

You can optionally notify reviewers with a webhook:

```bash
python3 bootstrap.py "NSF Faculty Early Career Development (CAREER) Program" \
  --async-review \
  --shared-review-dir "/Users/<you>/OneDrive - <Org>/Grant-Review" \
  --notify-webhook-url "https://<your-webhook-url>"
```

Or store the webhook in `.env`:

```env
REVIEW_NOTIFY_WEBHOOK_URL=https://<your-webhook-url>
```

After the shared files are approved, collect them locally:

```bash
python3 collect_review.py "NSF Faculty Early Career Development (CAREER) Program" \
  --shared-review-dir "/Users/<you>/OneDrive - <Org>/Grant-Review"
```

To watch for approval automatically:

```bash
python3 collect_review.py "NSF Faculty Early Career Development (CAREER) Program" \
  --shared-review-dir "/Users/<you>/OneDrive - <Org>/Grant-Review" \
  --watch --interval-seconds 300
```

### Run the weekly update

This is the command you will use most often once a program has a baseline guide:

```bash
python3 pipeline.py programs/<slug>/guide.md \
  --sources programs/<slug>/sources.json
```

Example:

```bash
python3 pipeline.py programs/nsf_career/guide.md \
  --sources programs/nsf_career/sources.json
```

What happens during a run:

1. Every source URL is scraped again.
2. The new content is compared with the last snapshot.
3. If anything changed, the diff is sent to Gemini.
4. Gemini rewrites only the affected sections.
5. Updated artifacts are written to `programs/<slug>/output/`.

The pipeline can also write an evidence file at `programs/<slug>/output/sponsor_guide_evidence.json`.

### Citation options

Citations are enabled by default. Useful flags:

```bash
python3 pipeline.py programs/<slug>/guide.md \
  --sources programs/<slug>/sources.json \
  --no-citations
```

```bash
python3 pipeline.py programs/<slug>/guide.md \
  --sources programs/<slug>/sources.json \
  --refresh-citations
```

```bash
python3 pipeline.py programs/<slug>/guide.md \
  --sources programs/<slug>/sources.json \
  --refresh-citations-only
```

The citation layer is guarded so it only uses approved source names and checks the generated references against the scraped text. If no website changes are found, the pipeline exits without overwriting the guide.

## Project Structure

```text
CI-sponsor-guide-updater/
├── bootstrap.py
├── pipeline.py
├── cite.py
├── scraper.py
├── differ.py
├── updater.py
├── discover.py
├── generator.py
├── review.py
├── review_async.py
├── collect_review.py
├── notify_review.py
├── program_utils.py
├── requirements.txt
├── .env.example
└── programs/
    └── <program-slug>/
        ├── sources.json
        ├── guide.md or *.docx
        ├── output/
        ├── state.json
        ├── data/
        ├── review/
        └── review_packages/
```

`programs/README.md` explains which files are committed and which ones are runtime-only.

## Source Format

Each program has a `sources.json` file with a list of approved source pages:

```json
[
  {
    "name": "NIH_R15_Main_Page",
    "url": "https://grants.nih.gov/grants/funding/r15.htm",
    "sections": []
  },
  {
    "name": "NIH_R15_Due_Dates",
    "url": "https://grants.nih.gov/grants/how-to-apply-application-guide/due-dates.htm",
    "sections": []
  }
]
```

Field summary:

| Field | Required | Purpose |
| --- | --- | --- |
| `name` | Yes | Stable ID used for snapshot filenames |
| `url` | Yes | The source page to scrape |
| `sections` | No | Leave empty unless you want to specify guide sections manually |

## Outputs

The pipeline writes generated files into `programs/<slug>/output/` by default.

Common artifacts include:

- `sponsor_guide_updated.md`
- `sponsor_guide_updated.docx`
- `sponsor_guide_updated.pdf`
- `sponsor_guide_evidence.json`

If you use the Streamlit Outputs page, it reads the same directory and lets you preview or download the available files.

## Troubleshooting

| Problem | Fix |
| --- | --- |
| `zsh: command not found: python` | Use `python3` instead |
| `GEMINI_API_KEY is not set` | Confirm `.env` exists in the project root and contains the key |
| `.env` exists but the key is not loading | Re-copy from `.env.example` and check that the file is not empty |
| `ModuleNotFoundError` | Run `pip3 install -r requirements.txt` again |
| A URL is marked unreachable | The page may be down or protected; you can still review it later |
| Gemini cannot detect sections | Leave `sections` empty and let the weekly pipeline try again |
| `404 NOT_FOUND` for a model | Check `updater.py` for the current default model name |
| `collect_review.py` says review is not approved | Ask the reviewer to set `manifest.json` to `approved` |
| Shared-folder path breaks on spaces | Wrap the path in quotes |
| Webhook notification fails | Verify the webhook URL is valid and reachable |
| No changes were generated | The site may not have changed; try `--refresh-citations` if you only need citation updates |

## Git Notes

Do not commit runtime artifacts such as:

- `.env`
- `programs/**/state.json`
- `programs/**/data/`
- `programs/**/review/`
- `programs/**/review_packages/`
- `output/`
- `*.docx`
- `*.doc`
- `*.pdf`

To publish your changes:

```bash
git status
git add -A
git commit -m "your commit message"
git push origin main
```
