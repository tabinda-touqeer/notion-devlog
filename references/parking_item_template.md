# Parking Item Reference Template (Zero-Memory Deferred Implementation Plan)

Use this template whenever engineering work, architectural refactors, or non-urgent guardrails are intentionally **parked for future implementation**.

---

## Mandatory Notion Hierarchy & Index Flow

Apply this exact two-level structure **separately** in both the **Personal hub page** (`parent_page_id`) and the **Shared Team hub page** (`shared_parent_page_id`):

```text
<Personal Hub Page> (e.g. Projects)
└── 🅿️ Parking items                        <-- ONLY entry directly on hub page
    ├── 💡 Parked engineering items — click any item below to open its full implementation plan.
    ├── 🛡️ <Parked Item 1 Title>            <-- Clickable child subpage (full plan inside)
    └── 🛡️ <Parked Item 2 Title>            <-- Clickable child subpage (full plan inside)

<Shared Team Hub Page> (e.g. ROHATECH AI Team)
└── 🅿️ Parking items                        <-- Separate team index on Shared hub page
    ├── 💡 Parked engineering items — click any item below to open its full implementation plan.
    ├── 🛡️ <Parked Item 1 Title>            <-- Full plan + Engineer/Project header attribution
    └── 🛡️ <Parked Item 2 Title>
```

### Strict Rules for the Index & Hierarchy
1. **Single Hub Entry**: Never create standalone plan pages directly under the Personal or Shared hub page. Keep them exclusively as child subpages inside `Parking items`.
2. **Clean Index Page**: `Parking items` must contain **only** one short intro callout (`🅿️`) plus the clickable child subpage titles. Do **not** put multi-paragraph summaries or duplicate specs on the index page.
3. **Zero-Memory Completeness**: Every clickable child subpage must be self-contained so an engineer or AI agent opening it months later with zero memory has exact file paths, complete audits, copy-paste-ready code, test assertions, and rollout steps.
4. **No Commit SHA Required (Yet)**: Because parked items are deferred work, they do not require a Git commit hash. Still enforce **Zero Chat Leakage** (never copy developer-to-AI chat prompts into Notion).
5. **Personal-Only by Default (Explicit Opt-In for Shared)**: Parking items default strictly to `--target personal`. **Never** mirror or publish a parking item into the Shared Team page unless the user explicitly asks to publish it to Shared (`--target shared` or `--target both`). Personal and Shared `Parking items` hubs remain completely independent.

---

## Standard 5-Section Structure Inside Each Parked Item Page

### Callout (`📌`, `blue_background`)
> **Status:** Parked for future implementation (`YYYY-MM-DD`)  
> **Engineer / Project:** `[Name] ([Project])` *(included automatically on Shared workspace pages)*  
> **Target Branch:** `<branch>` (and sync branch if applicable)  
> **Owner / Trigger:** Exact product bug, payload, or engineering need that triggered parking.

---

### Heading 2: 1. Problem & Exact Root Cause
- Plain-English explanation of what happened in production/testing.
- Exact sample payload / request / error output in a formatted code block (`json` / `text`).
- **Heading 3: Why existing safeguards missed this** — numbered layers with exact file paths, line ranges, class/function names, and missing checks.

---

### Heading 2: 2. Complete Component / Flow Audit (Critical Constraints Before Editing)
- Amber **Callout (`⚠️`, `yellow_background`)** highlighting edge cases, valid empty fields, or invariants that must **not** be broken.
- **Notion Table**: Comprehensive component/flow matrix covering every variant, inputs, outputs, required invariants, and intentionally valid exceptions.

---

### Heading 2: 3. Exact Step-by-Step Implementation Instructions
- Organized into clear subsections (**Heading 3: Step 1: ...**, **Step 2: ...**, **Step 3: ...**).
- Exact target file path before each step.
- Numbered steps with **copy-paste-ready code blocks**, exact signatures/imports, log event schemas, and exact call-site placement (before/after hooks).

---

### Heading 2: 4. Verification Plan
- Exact test runner command (`py -3.11`, `pytest`, `.venv\Scripts\python.exe`, etc.).
- Numbered test scenarios with bulleted setup, invocation, and exact pass/block assertions (covering positive flow, failure guard, and regression checks).

---

### Heading 2: 5. Rollout Checklist
- Notion `to_do` checkboxes covering implementation, unit/regression tests, primary branch push, and sync/cherry-pick branches.

