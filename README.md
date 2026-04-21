# CI Sponsor Guide Tool

CI Sponsor Guide Tool helps teams discover, review, and keep grant sponsor guides current. It monitors official funding websites, detects changes, and regenerates guide output with citation support using Google Gemini.

It is designed for non-developers to use in day-to-day work, while still staying fully scriptable from the command line.

## What It Does

1. Finds official source pages for a grant program.
2. Helps reviewers approve, reject, or add links.
3. Generates a first draft with citations and produces output files immediately.
4. Exports `.md`, `.docx`, and `.pdf` files ready for download.
5. Runs weekly updates to detect website changes and refresh the guide over time.
6. Optionally runs an Alternative Funding Intelligence Monitor for foundation, corporate, international, and pharma partnership opportunities.

## Workflow

```text
One-time setup per program
  1. Create Program   → discover candidate source pages
  2. Review & Generate → approve sources, generate first draft with citations, get outputs
  3. View Outputs      → preview and download .md / .docx / .pdf right away

Ongoing maintenance
  4. Weekly Update     → re-scrape sources, diff, update guide, refresh outputs
  5. Audit Evidence    → trace citations and diffs back to source pages
```

## Architecture

- See [Architecture](docs/ARCHITECTURE.md) for module flow, trust boundaries, and deployment/storage design.

Output files (markdown, Word, PDF) are available immediately after generating the first draft. You do not need to run the weekly update before you can see results.

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

## Authentication

By default, authentication is **off** — the app runs without any login check when there is no `[auth]` section in Streamlit secrets. This is the right behaviour for local development and CLI usage.

When you deploy to Streamlit Cloud and want to restrict access to a named list of institutional email addresses, follow these steps. The app uses **Microsoft Azure AD** as the sign-in provider, which works with any institution that uses Microsoft 365 / Outlook / Teams for email.

### 1. Register an app in Azure Active Directory

1. Go to [portal.azure.com](https://portal.azure.com) and sign in with an admin account (or ask your IT team to do this step).
2. Navigate to **Azure Active Directory > App registrations > New registration**.
3. Give it a name (e.g. `CI Sponsor Guide Tool`).
4. Under **Supported account types**, choose:
   - *Accounts in this organizational directory only* — recommended; restricts sign-in to your institution only.
5. Under **Redirect URI**, choose **Web** and add both:
   - Local dev: `http://localhost:8501/oauth2callback`
   - Production: `https://<your-app>.streamlit.app/oauth2callback`
6. Click **Register**. Copy the **Application (client) ID** and the **Directory (tenant) ID** shown on the overview page.
7. Go to **Certificates & secrets > New client secret**, set an expiry, and copy the secret **Value** (not the ID).

### 2. Configure secrets

Copy the template and fill in your values:

```bash
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
```

Edit `.streamlit/secrets.toml`:

```toml
[auth]
redirect_uri        = "http://localhost:8501/oauth2callback"
cookie_secret       = "a-long-random-string"   # python3 -c "import secrets; print(secrets.token_hex(32))"
client_id           = "YOUR_AZURE_APPLICATION_CLIENT_ID"
client_secret       = "YOUR_AZURE_CLIENT_SECRET_VALUE"
server_metadata_url = "https://login.microsoftonline.com/YOUR_TENANT_ID/v2.0/.well-known/openid-configuration"

[allowed_users]
emails = [
    "alice@yourinstitution.edu",
    "bob@yourinstitution.edu",
]
```

`secrets.toml` is listed in `.gitignore` and must never be committed.

### 3. On Streamlit Cloud

Paste the same key/value pairs into **App settings > Secrets** in the Streamlit Cloud dashboard. Change `redirect_uri` to your production URL:

```toml
redirect_uri = "https://<your-app>.streamlit.app/oauth2callback"
```

### Behaviour at runtime

| Situation | What the user sees |
| --- | --- |
| No `[auth]` in secrets | App loads normally, no login required (dev mode) |
| `[auth]` present, not signed in | Sign-in page with Microsoft button |
| Signed in, email on allowlist | App loads normally |
| Signed in, email NOT on allowlist | Access-denied message with sign-out button |
| `[allowed_users]` section absent | Any authenticated account in your Azure AD tenant is allowed |

Users see a **Sign out** button at the bottom of the sidebar when they are signed in.

### Note on client secret expiry

Azure client secrets expire (1 or 2 years is typical). Set a calendar reminder to rotate the secret before it expires — an expired secret will break sign-in for all users. Rotate by creating a new secret in Azure, updating `client_secret` in Streamlit Cloud Secrets, and deleting the old secret.

## Streamlit App

The Streamlit app gives you a guided workflow over the same files used by the CLI.

Available pages:

| Step | Page | What it does |
| --- | --- | --- |
| 1 | Create New Program | Discover candidate source pages for a new grant program or funding topic |
| 2 | Review & Generate | Approve sources, generate the first draft with citations, and get output files |
| 3 | View Outputs | Preview the guide and download `.md` / `.docx` / `.pdf` immediately |
| 4 | Weekly Update | Refresh an existing guide when sponsor pages change (optional until needed) |
| 5 | Audit Evidence | Trace diffs, citations, and evidence back to source pages |

After Step 2, output files are ready. You do not need to run Weekly Update before viewing results.

Use the UI if you want a more visual, step-by-step experience. It reads and writes the same artifacts under `programs/<slug>/`, so the CLI and UI stay in sync.

### Alternative Funding Intelligence Monitor (UI)

In **Step 1 (Create New Program)**, enable **Alternative Funding Intelligence Monitor** to pivot from federal program discovery to non-federal opportunity scanning.

When enabled, fill the form like this:

- **Funding topic**: describe what you want funding for (not a federal program name)
  - Example: `Alternative funding opportunities for translational oncology research`
- **Alternative monitor focus areas**: comma-separated domains
  - Example: `oncology, translational research, biomarkers`
- **Alternative monitor geographies**: comma-separated regions/countries
  - Example: `US, UK, EU, global`

What this mode does:

1. Seeds known alternative funders (for example Wellcome, Gates, Bloomberg, pharma partnering pages).
2. Discovers additional relevant pages.
3. Classifies and scores opportunities.
4. Saves a ranked watchlist for review and weekly monitoring.

Files created when enabled:

- `programs/<slug>/review/sources_pending.json` (review queue with monitor metadata)
- `programs/<slug>/review/alternative_funding_watchlist.json` (ranked candidate watchlist)

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
├── output/
│   ├── sponsor_guide_updated.md
│   ├── sponsor_guide_updated.docx
│   ├── sponsor_guide_updated.pdf
│   └── sponsor_guide_evidence.json
└── review/
    ├── sources_pending.json
    └── draft_guide.md
```

The `output/` directory is populated as soon as you generate the first draft.

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

Use this command to refresh an existing guide after sponsor pages have changed. This is not needed for the initial draft — output files are already produced during generation.

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

Citations are added during both the first draft generation and weekly updates. They are enabled by default. Useful CLI flags for the weekly pipeline:

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

## Unit Tests

Run the full test suite:

```bash
python3 -m pytest tests/
```

Run focused guardrail suites:

```bash
python3 -m pytest tests/test_cite.py
python3 -m pytest tests/test_differ.py
python3 -m pytest tests/test_scraper.py
```

These tests protect key hallucination and regression boundaries:

- `tests/test_cite.py` validates citation guardrails, including lexical-overlap threshold behavior.
- `tests/test_differ.py` validates diff edge cases and normal change extraction.
- `tests/test_scraper.py` validates first-stage scraping behavior, state persistence, hash comparisons, and snapshot filename sanitization.

Automated CI runs `python -m pytest tests/` on every push to `main` and on pull requests targeting `main` via `.github/workflows/ci.yml`.

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
    "sections": [],
    "data_class": "public"
  },
  {
    "name": "NIH_R15_Due_Dates",
    "url": "https://grants.nih.gov/grants/how-to-apply-application-guide/due-dates.htm",
    "sections": [],
    "data_class": "public"
  }
]
```

Field summary:

| Field | Required | Purpose |
| --- | --- | --- |
| `name` | Yes | Stable ID used for snapshot filenames |
| `url` | Yes | The source page to scrape |
| `data_class` | Yes | Set to `public` for any source that may be sent to the LLM |
| `sections` | No | Leave empty unless you want to specify guide sections manually |

When the Alternative Funding Intelligence Monitor is enabled, entries in `sources.json` may also include optional metadata fields:

- `funding_type` (`foundation`, `corporate`, `international`, `pharma_partnership`)
- `funder_name`
- `opportunity_title`
- `focus_areas`
- `geography`
- `deadline`
- `typical_award_size`
- `eligibility_summary`
- `confidence_score`
- `priority_score`

## Outputs

Output files are written to `programs/<slug>/output/` during both the first draft generation (Step 2) and the weekly update pipeline.

Common artifacts include:

- `sponsor_guide_updated.md`
- `sponsor_guide_updated.docx`
- `sponsor_guide_updated.pdf`
- `sponsor_guide_evidence.json` (citation evidence, only when citations are enabled)

The Streamlit Outputs page reads from this directory and lets you preview or download the available files. If no output directory exists yet, it falls back to showing the draft or baseline guide.

## Troubleshooting

| Problem | Fix |
| --- | --- |
| `zsh: command not found: python` | Use `python3` instead |
| `GEMINI_API_KEY is not set` | Confirm `.env` exists in the project root and contains the key |
| `.env` exists but the key is not loading | Re-copy from `.env.example` and check that the file is not empty |
| `ModuleNotFoundError` | Make sure you installed `requirements.txt` and kept `setup.py` plus `-e .` in place |
| `No module named 'app'` on Streamlit Cloud | Set the app entrypoint to `app/main.py` and redeploy after installing dependencies |
| `GEMINI_API_KEY is not set` in Streamlit Cloud | Add the key under **App settings > Secrets** so the deployed app can read it |
| Remote persistence says sync failed | Check `RUNTIME_STORAGE_*` secrets, token scopes, repository name, and repository write access |
| `Unable to read repository metadata: 404` | The runtime repo name is wrong or the token cannot access that repo |
| Files disappear after Cloud restart | Enable GitHub runtime persistence or move artifacts to durable external storage |
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
