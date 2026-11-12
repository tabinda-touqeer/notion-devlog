# Notion DevLog (`engineering-reporting`)

**Turn your AI coding sessions into clean Notion engineering logs, technical documentation, and daily manager briefings — automatically.**

---

## Why Use This Skill?

When you build software with an AI coding assistant, code moves fast — commits pile up, multiple fixes ship in a day, and architectural decisions happen on the fly. Writing clean Notion tickets, estimating hours, and compiling End-of-Day (EOD) updates afterward usually becomes a slow, repetitive chore.

**Notion DevLog** bridges that gap automatically:

- **For Developers:** Stay focused on shipping code. Whenever you finish a task or wrap up your day, your assistant turns your commits, test results, and code changes into structured Notion pages in seconds.
- **For Engineering Managers & Leads:** Get clear, consistent daily visibility into what was delivered, why an issue happened, what changed, and realistic engineering hours — without chasing teammates for updates.
- **For Future Teammates:** Every logged task reads like real technical documentation (`Before vs. After` behavior, root cause, architectural rationale, and modified files), building a searchable engineering knowledge base as you ship.

---

## Key Features

- **Zero-Effort Notion Setup** — Paste a link to one blank Notion page and your assistant automatically creates both the **Tasks** and **Daily EOD Briefings** tables with all required columns.
- **Rich, Structured Task Pages** — Each task page isn't just a short title; it documents:
  - Plain-English **System Context** (helpful for reviewers unfamiliar with the module)
  - **Before vs. After** behavioral impact
  - **Layered Root Cause Analysis** and exact code/file changes
  - **Architectural Rationale** explaining *why* that design decision was chosen
  - **QA & Verification Results** from your actual test runs
- **Granular Work Breakdown** — Separates investigation/audit work from individual fixes and features so engineering logs read like a clean Jira/Linear board.
- **Git Commit & Branch Traceability** — Automatically links every Notion entry to its Git commit SHA, active branch, and touched files.
- **Realistic Time Tracking** — Estimates senior-engineer effort hours per task (`Time Spent (hrs)`) with a configurable daily limit (`max_daily_hours`) to keep daily timesheets realistic.
- **One-Prompt Daily EOD Briefings** — Aggregates the day's tasks, total hours, key architectural decisions, and repository status into a ready-to-share manager summary.
- **Solo & Free-Plan Team Support** — Every engineer keeps their own personal Notion page while updates can mirror automatically to a central **Shared Team Table** tagged by `Engineer` — giving managers one unified team view without needing paid workspace seats for everyone.

---

## Quick Setup

### 1. Install the Skill

Clone this repository into your project's skills directory (or your global skills directory to use it across all projects):

```bash
# Project-level install:
git clone https://github.com/tabinda-touqeer/notion-devlog.git .agents/skills/engineering-reporting

# Or global install across all projects:
git clone https://github.com/tabinda-touqeer/notion-devlog.git ~/.agents/skills/engineering-reporting
```

Install the dependency:

```bash
pip install -r .agents/skills/engineering-reporting/requirements.txt
```

### 2. Create a Notion Integration & Save Your Token

1. Visit [Notion My Integrations](https://www.notion.so/profile/integrations) and click **New integration**.
2. Name it (for example, `Engineering Reporter`), choose your personal Notion workspace, and copy the **Internal Integration Secret**.
3. Save the token so it works permanently across terminal sessions on Windows, macOS, and Linux:
   - **Recommended:** Ask your assistant to save it in Step 3, or save it in `~/.config/engineering-reporting/.notion_token` (no quotes or extra spaces).
   - **Alternative:** Set the `NOTION_TOKEN` environment variable in your shell/profile.

### 3. Connect One Blank Notion Page

1. Create a blank page in your Notion workspace (for example, **Engineering DevLog**).
2. Open the **`...`** menu in the top-right corner of the page -> **Connections** -> select your integration.
3. Copy and paste this into your coding assistant (replace the placeholders):

```text
Set up my engineering reporting skill:
1. Save my Notion token "<PASTE_YOUR_NOTION_TOKEN>" to ~/.config/engineering-reporting/.notion_token.
2. Create my personal Notion Tasks & EOD databases on this page: <PASTE_YOUR_NOTION_PAGE_LINK>
3. Set my default_project to "<YOUR_PROJECT_NAME>" and verify the connection.
```

Your assistant will create two clickable sub-page tables (**📋 Tasks & Engineering Activity Log** and **📰 Daily Manager Briefings (EOD Reports)**) inside that page and save their database IDs into your local `config.json`.

---

## Team Setup (Optional Shared Manager Table)

Want one central Notion hub where a manager can view progress across the whole team, even when teammates only have **Guest** access to the shared page or work in separate free Notion workspaces?

### 1. Team Lead / Workspace Owner (Once)

1. Go to [Notion My Integrations](https://www.notion.so/profile/integrations) in the **shared workspace** and create a **separate, dedicated integration** (for example, `Team DevLog Sync`).
   - *Keep your own personal integration token private — only connect this dedicated integration to the shared team page so teammates cannot access anything else in your workspace.*
2. Create one blank page for the team, connect **`Team DevLog Sync`** to it (`...` -> **Connections**), and paste this into your coding assistant:

```text
Set up the shared team Notion databases on this page: <PASTE_SHARED_PAGE_LINK>
```

3. Share the Notion page link with your manager (they can open **Shared Team Engineering Tasks** or **Shared Team Daily EOD Briefings** and filter/group by `Engineer` and `Date`).
4. Send your teammates via **private DM**:
   - The **`Team DevLog Sync`** integration secret (`SHARED_NOTION_TOKEN`)
   - The created **Shared Tasks DB ID** and **Shared EOD DB ID**

### 2. Each Team Member (Once)

Each teammate uses **their own** `NOTION_TOKEN` for their personal Notion page and the lead's DM'd token as `SHARED_NOTION_TOKEN` for the shared table (this works even if they are only Guests on the shared Notion page).

Copy and paste this all-in-one setup prompt into your coding assistant:

```text
Set up the engineering reporting skill from https://github.com/tabinda-touqeer/notion-devlog.git:
1. Clone it into my skills folder (.agents/skills/engineering-reporting) if not already installed, and install requirements.txt.
2. Save my personal Notion token "<PASTE_YOUR_PERSONAL_NOTION_TOKEN>" to ~/.config/engineering-reporting/.notion_token and the shared team token "<PASTE_SHARED_TEAM_TOKEN>" to ~/.config/engineering-reporting/.shared_notion_token.
3. Create my personal Notion Tasks & EOD databases on this page: <PASTE_YOUR_PERSONAL_NOTION_PAGE_LINK>
4. Set my engineer_name to "<YOUR_FULL_NAME>" and default_project to "<YOUR_PROJECT_NAME>"
5. Mirror my logs to the shared team tables:
   - shared_tasks_database_id: <SHARED_TASKS_DB_ID>
   - shared_eod_database_id: <SHARED_EOD_DB_ID>
6. Run --test-connection and --ensure-schema to confirm both workspaces are [OK].
```

Every logged task and EOD briefing is tagged with your `Engineer` name, keeping every team member's entries neatly separated for manager review.

---

## Configuration (`config.json`)

If you prefer configuring settings manually, copy `config.example.json` to `config.json`:

```bash
cp config.example.json config.json
```

```json
{
  "engineer_name": "Your Name",
  "tasks_database_id": "<PERSONAL_TASKS_DATABASE_ID>",
  "eod_database_id": "<PERSONAL_EOD_DATABASE_ID>",
  "shared_tasks_database_id": "",
  "shared_eod_database_id": "",
  "default_project": "My Project",
  "default_branch": "main",
  "default_remotes": ["origin"],
  "default_sprint": "Sprint 1",
  "eod_title_suffix": "Engineering Development",
  "max_daily_hours": 12.0
}
```

| Field | Env Variable | Description |
|---|---|---|
| `engineer_name` | `ENGINEERING_ENGINEER_NAME` | Your display name tagged in the `Engineer` column on shared team tables. |
| `tasks_database_id` | `NOTION_TASKS_DB_ID` | Your personal Tasks database ID (auto-filled during setup). |
| `eod_database_id` | `NOTION_EOD_DB_ID` | Your personal EOD Briefings database ID (auto-filled during setup). |
| `shared_tasks_database_id` | `NOTION_SHARED_TASKS_DB_ID` | *(Optional)* Shared team Tasks database ID. |
| `shared_eod_database_id` | `NOTION_SHARED_EOD_DB_ID` | *(Optional)* Shared team EOD Briefings database ID. |
| `default_project` | — | Project name applied to logged tasks and EOD summaries. |
| `default_branch` | — | Default Git branch name for your project. |
| `default_remotes` | — | Git remote names referenced in EOD summaries (e.g., `["origin"]`). |
| `default_sprint` | — | Active sprint or cycle label. |
| `eod_title_suffix` | — | Title label appended to daily EOD pages. |
| `max_daily_hours` | — | Maximum total hours logged per day (default `12.0`). |

> **Tip:** To store `config.json` outside the skill folder, set `ENGINEERING_REPORTING_CONFIG` to your preferred file path.

---

## How to Use

Copy and paste any of these prompts into your coding assistant during your normal workday:

**Log a finished task:**

```text
Commit my changes and log this task to Notion.
```

**Generate today's EOD report:**

```text
Create today's EOD report in Notion.
```

**Verify your setup:**

```text
Check my Notion reporting setup.
```

---

## License

[MIT](./LICENSE)
