---
name: engineering-reporting
description: >-
  Use this skill when logging software engineering tasks, reporting bug fixes,
  documenting architectural decisions, or writing Daily Manager Briefings (End of Day reports)
  in Notion or markdown. Enforces reader-friendly, professional language while strictly
  preserving product triggers, error payloads, root-cause analysis, code guardrails,
  architectural justifications, realistic effort tracking, test verification, and git traceability.
---

# Engineering Reporting & Notion Activity Logging Skill

This skill defines a project-agnostic engineering reporting standard for documenting software engineering progress, technical bug investigations, architectural decisions, effort estimates, and daily management briefings.

Its primary goal is twofold:
1. **Management Transparency**: Show team leads and managers the technical effort, root-cause diligence, and delivery impact behind every ticket in clear, reader-friendly language.
2. **Permanent Future Reference**: Serve as a technical knowledge base that engineers can consult months later to understand **what changed, why it changed, and why a specific design decision was chosen**.

> [!CAUTION]
> ### 🚨 STRICT PRIVACY & AUDIENCE RULE: ZERO CHAT LEAKAGE
> Notion activity logs and daily briefings are shared team and management documents.
> **NEVER expose or copy internal developer-to-agent pair-programming chat, instructions, or prompts into Notion.**
> - **"User Query" / "Customer Input"** strictly and exclusively means the **end-user / product input triggering a bug or workflow** (e.g., an API request, CLI input, UI submission, or customer phrase such as `"checkout fails on empty coupon"` or `"CSV export omits UTC offset"`).
> - It **NEVER** means the developer or engineer instructing an AI coding assistant (e.g., *"please check why X is broken"*, *"what did you do?"*, *"commit and push"*).
> - When documenting architectural tasks, refactors, or performance initiatives without an end-user prompt, formulate them as **Product Requirements**, **Engineering Initiatives**, or **Performance Benchmarks** (e.g., *"Product Requirement: Standardize API validation errors"*, *"Performance Initiative: Unified single-pass catalog lookup"*).

---

> [!IMPORTANT]
> ### Mandatory Pre-Notion Rule: Commit First, Real Commit Hash Only
> **NEVER update Notion before committing the code, and NEVER write `"Pending commit"`, `"uncommitted"`, or `"TBD"` in the Notion `Git Commits` column.**
> 1. Always stage and commit completed, tested code to Git first on the active branch (`main`, `dev`, release branches, etc.).
> 2. Record the actual commit hash (`git rev-parse --short HEAD`, e.g. `a1b2c3d`) in every task entry and Notion `Git Commits` property. `notion_logger.py` enforces this programmatically.

> [!IMPORTANT]
> ### Ultra-Realistic Senior Engineer Time Estimation (`Time Spent (hrs)`)
> Every task logged to `daily_buffer.jsonl` and Notion MUST include `time_spent_hours` (written to the numeric Notion column **`Time Spent (hrs)`** and rolled up into **`Total Time Spent (hrs)`** on the daily EOD report).
> - **Benchmark Persona**: Estimate how long a **highly senior software engineer who already works full-time on the codebase and knows its architecture intimately** would realistically take to complete the task end-to-end — **never AI execution speed**.
> - **What the Estimate Must Cover**: Reading and tracing root causes across callers, designing the fix or schema/config changes, implementing code and edge-case guardrails, resolving any branch conflicts, writing/running targeted verification and regression suites, and committing/syncing.
> - **Granularity**: Use clean decimal hours in realistic `0.25`-hour increments (e.g., `0.5` = 30m, `0.75` = 45m, `1.5` = 1h 30m, `3.5` = 3h 30m). Small scoped fixes should not be undercounted (typically at least `0.25`–`0.5` hrs once verification and commit sync are included); multi-module features or deep audits should reflect realistic multi-hour human effort.
> - **Daily 12-Hour Cap & Proportional Rebalancing**: No single calendar day may report more than **`12.0` total hours** (`max_daily_hours` in `config.json`). `notion_logger.py` preserves each task's unscaled complexity weight (`raw_estimated_hours`) in `daily_buffer.jsonl`; whenever tasks logged on the same date exceed `12.0` hours, `rebalance_date_tasks()` automatically rescales that day's `Time Spent (hrs)` proportionally to each task's complexity weight (preserving a `0.25h` minimum floor) across `daily_buffer.jsonl`, Notion Tasks, and EOD totals so the day never exceeds `12.0` hrs. Days already `<= 12.0` hrs are never altered.

---

## The 9 Golden Rules of Engineering Reporting

Whenever you document a task or write an EOD report, follow these core principles:

### 1. Reader-Friendly & Zero-Prior-Context Clarity (No Insider Jargon)
- Write as if the reader is a senior software engineer who **knows nothing about this specific repository** and was not involved in building it, reviewing the ticket cold or using it as a future technical reference.
- Always open with **System Context**: briefly explain what the touched API endpoint, background worker, cache, or table does in plain English before citing internal class/function/table names.
- Avoid cryptic one-liners or unexplained internal acronyms; spell out both **what was done** and **how the component fits into the system**.

### 2. Granular Developer Work Logs (Audit Separate From Individual Fixes)
- Record daily work the way mature engineering teams track tickets in Jira/Linear — **never** bundle an entire day or multi-module remediation into one mega summary ("Fix 8 vulnerabilities...") or write marketing prose.
- Always log **a dedicated task for investigation, profiling, or security audit work** (`audit(...)`, `perf(audit)`, `investigation(...)`) because analysis and design take separate engineering time.
- Log **individual, single-focus tasks** for each concrete bug fix, performance improvement, feature, or documentation deliverable.

### 3. Explicit Behavioral Impact (Before vs. After Behavior)
- Every bug fix, optimization, or behavioral change MUST clearly explain:
  - **Before (Behavior When Issue Existed):** How the system actually behaved when the issue was present (exact failure mode, HTTP response, excessive DB round-trips, race condition, or unintended access) so a reviewer sees the concrete risk/symptom.
  - **After (Behavior After Fix):** How the system behaves now under normal inputs, invalid/malicious inputs, and boundary conditions.

### 4. Product Input & Output Fidelity (Strict Scope)
- Document the relevant **exact product input or trigger** (preserving verbatim input/payloads where applicable).
- **Zero Chat Leakage**: Never quote or leak the developer's chat instructions to the AI assistant. Developer-AI chat is strictly private working dialogue.
- Document concrete wrong behavior or dispatched payloads when applicable.

### 5. Layered Root Cause Analysis (Why did it happen?)
- Never settle for "there was a bug in the code".
- Break down the underlying reasons into specific, numbered layers (e.g., Layer 1: Missing schema validation; Layer 2: Cache invalidation race condition).

### 6. Concrete Code Evidence & Implementation Details
- Show the actual code logic, configuration values, limits/TTLs, or regex pattern implemented.
- Specify exact file paths modified (e.g., `src/services/billing/validator.py`).
- Detail the guardrails introduced (input bounds, fallback policies, HTTP status codes).

### 7. Explicit Architectural Justification ("Why this decision?")
- Explain why a specific solution was chosen over alternative approaches.
- Address performance, latency, security, and cost considerations (e.g., *Why use an in-memory trie lookup? Because it runs in <2ms vs 1200ms external RPC latency*).
- Detail data model decisions (e.g., *Why store both `raw_input` and `normalized_input`? To protect downstream analytics while preserving user display fidelity*).

### 8. Rigorous QA & Verification Proof
- List unit tests created, edge cases tested, and pass rates.
- Mention end-to-end integration simulations or API verification scripts with exact observed HTTP codes / query counts / assertions.

### 9. Git & Environment Traceability (Committed SHAs Required)
- Always commit code cleanly first and record the real commit hash (e.g., `91663ba`, `5802077`) — **never** `"Pending commit"`.
- Document relevant branches (`main`, release/feature branches) and remotes (`origin`, etc.).

---

## Standard Task Page Structure (Notion / Markdown)

When logging an individual task into the **Tasks & Engineering Activity Log**, use this structure:

```markdown
📌 Callout: Quick Summary / Objective of the task

## 1. System Context & Problem (or Requirement)
- Plain-English explanation of what this part of the system does (for readers new to the project)
- Exact end-user/product trigger verbatim (if user-facing) or concrete engineering/security requirement
- User / system impact

---
## 2. Behavioral Impact (Before vs. After)
- Before (System Behavior With Issue): Exact symptom, failure response, DB load, or exposure
- After (System Behavior Now): Exact new behavior for valid, invalid, and edge cases

---
## 3. Why Did This Happen? (Root Cause Analysis)
- Root Cause 1: [Validation / Parsing / Mapping gap]
- Root Cause 2: [State / Concurrency / Lifecycle gap]

---
## 4. What Was Fixed & How It Was Implemented
- Layer 1: [Data / Schema change]
- Layer 2: [Algorithm / Guardrail implementation with exact limits/code]
- Layer 3: [Fallback / Policy / Audit logging updates]

---
## 5. Why This Architectural Decision?
- Why Option A was chosen over Option B
- Latency, scalability, security, or data integrity justification

---
## 6. Verification & Testing
- Tests executed and exact observed results
- Edge cases covered

---
## 7. Git & Effort Traceability
- Real Commit Hash (never 'Pending commit') & Branch
- Modified / Added Files
- Estimated Senior Engineer Effort (`Time Spent (hrs)` numeric hours & `Xh Ym` breakdown)
```

---

## Daily Manager Briefing (EOD Report) Structure

When compiling an **End of Day (EOD) Manager Briefing**, use this structure:

1. **Header Callout**: Date, Active Project(s), Total Time Spent (`<= 12.0 hrs`).
2. **Today's Engineering Summary**: A concise, friendly paragraph summarizing the key wins, total effort, and technical milestones of the day.
3. **Detailed Work Breakdown**:
   - Dedicated subsection for each task worked on today.
   - Summarizes: System context, problem/trigger, before vs. after behavior, root cause, fix, time spent (`Time Spent (hrs)`), and commit hashes.
4. **Key Architectural Decisions (Future Reference Guide)**:
   - Bulleted summary of major design trade-offs made today.
5. **Current Status & Tomorrow's Priorities**:
   - Code status (commits, remotes, branches).
   - Daily effort summary (`Total Time Spent (hrs)`).
   - Infrastructure/testing state and next steps.

---

## Notion Integration & Fast-Path Workflow

The skill bundles an automated configuration and execution engine in `scripts/notion_logger.py` backed by a local `config.json` (copied from `config.example.json` or configured via environment variables) and a persistent local activity journal `daily_buffer.jsonl`.

### 1. Project Configuration (`config.json`) & Dual-Write Team Mirroring
Copy `config.example.json` to `config.json` (gitignored) or run `--setup-member`. Configure `NOTION_TOKEN`, `NOTION_TASKS_DB_ID`, and `NOTION_EOD_DB_ID` for your personal workspace. To automatically mirror every task, daily rebalance, and EOD briefing into a central manager-facing Shared Team table (without needing paid Notion team seats for every developer), also set `engineer_name`, `shared_tasks_database_id`, and optionally `shared_eod_database_id` (plus `SHARED_NOTION_TOKEN` if the shared table is in a separate workspace):
```json
{
  "engineer_name": "Your Name",
  "tasks_database_id": "<YOUR_PERSONAL_TASKS_DATABASE_ID>",
  "eod_database_id": "<YOUR_PERSONAL_EOD_DATABASE_ID>",
  "shared_tasks_database_id": "<OPTIONAL_SHARED_TEAM_TASKS_DATABASE_ID>",
  "shared_eod_database_id": "<OPTIONAL_SHARED_TEAM_EOD_DATABASE_ID>",
  "default_project": "My Project",
  "default_branch": "main",
  "default_remotes": ["origin"],
  "default_sprint": "Sprint 1",
  "eod_title_suffix": "Engineering Development",
  "max_daily_hours": 12.0
}
```
When shared database IDs are omitted/blank, `notion_logger.py` writes only to your personal databases. When configured, shared queries and upserts filter strictly by `Date` and `Engineer` so teammates never overwrite each other's rows or daily EOD briefings.

### 2. Built-in Zero Chat-Leakage Validator
`notion_logger.py` enforces programmatic validation on all user input fields. If developer-to-AI chat phrasing (e.g., *"please check..."*, *"what did you do"*, *"commit and push"*) is accidentally supplied in `customer_queries`, the script raises an immediate validation error to prevent exposure.

### 3. Persistent Local Journal (`daily_buffer.jsonl`)
Whenever conversation context is compacted or restarted, reading `daily_buffer.jsonl` recovers the exact record of tasks logged for the day without duplicating or hallucinating entries.

### 4. Fast-Path CLI Commands
Whenever onboarding a workspace, logging tasks, or compiling EOD reports, use these commands:

```bash
# 0a. Auto-create Notion databases (tables + all columns) inside a blank Notion page & save IDs to config.json:
python .agents/skills/engineering-reporting/scripts/notion_logger.py --init-dbs --parent-page "<NOTION_PAGE_URL_OR_ID>"
python .agents/skills/engineering-reporting/scripts/notion_logger.py --init-shared-dbs --shared-parent-page "<SHARED_PAGE_URL_OR_ID>"

# 0b. Or onboard a team member in one step (optionally auto-creating personal DBs from --parent-page):
python .agents/skills/engineering-reporting/scripts/notion_logger.py --setup-member --name "Jane Doe" --parent-page "<NOTION_PAGE_URL_OR_ID>" --shared-tasks-db <id> --shared-eod-db <id>
python .agents/skills/engineering-reporting/scripts/notion_logger.py --test-connection
python .agents/skills/engineering-reporting/scripts/notion_logger.py --ensure-schema

# 1. Inspect existing tasks & time estimates in the local buffer:
python .agents/skills/engineering-reporting/scripts/notion_logger.py --list-buffer

# 2. Publish a task to Notion (dual-writes to Personal + Shared DBs, auto-rebalances day if > 12h):
python .agents/skills/engineering-reporting/scripts/notion_logger.py --log-task task_spec.json

# 3. Rebalance a date (or all dates) against the 12.0h daily cap across Personal & Shared DBs:
python .agents/skills/engineering-reporting/scripts/notion_logger.py --rebalance --date all

# 4. Automatically compile buffered tasks into Personal & Shared EOD Briefings:
python .agents/skills/engineering-reporting/scripts/notion_logger.py --sync-eod

# 5. Backfill or repair buffered tasks & EODs in the Shared Team DB (idempotent):
python .agents/skills/engineering-reporting/scripts/notion_logger.py --sync-shared --date all
```

---

## Bundled Files & Templates
- Config Example: [config.example.json](./config.example.json)
- Automation CLI: [scripts/notion_logger.py](./scripts/notion_logger.py)
- Task Template: [references/task_template.md](./references/task_template.md)
- EOD Report Template: [references/eod_template.md](./references/eod_template.md)
- Notion Block Guide: [references/notion_blocks_guide.md](./references/notion_blocks_guide.md)
