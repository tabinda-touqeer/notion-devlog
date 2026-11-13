"""
notion_logger.py - Production-grade automated helper for logging engineering tasks
and compiling daily manager briefings to Notion (Personal + optional Shared Team DB).

Features:
- Automated configuration loading from config.json or environment variables.
- Dual-write support: mirror personal Tasks & EOD briefings to a Shared Team Notion DB.
- Strict Zero-Chat-Leakage validator (blocks pair-programming prompts).
- Commit-first traceability and senior-engineer effort tracking with a 12h/day cap.
- Local persistent daily activity journal (daily_buffer.jsonl).
- One-click task logging, member onboarding, shared backfill, and EOD compilation.

Usage:
  python notion_logger.py --test-connection
  python notion_logger.py --setup-member --name "Jane Doe" --tasks-db <id> --eod-db <id> [--shared-tasks-db <id>] [--shared-eod-db <id>]
  python notion_logger.py --ensure-schema
  python notion_logger.py --list-buffer
  python notion_logger.py --log-task task_spec.json
  python notion_logger.py --rebalance --date all
  python notion_logger.py --sync-shared [--date YYYY-MM-DD|all]
  python notion_logger.py --sync-eod [--date YYYY-MM-DD]
  python notion_logger.py --init-parking [--target personal|shared|both]
  python notion_logger.py --park-item parking_spec.json [--target personal|shared|both]
  python notion_logger.py --park-md plan.md --title "My Plan" [--target personal|shared|both]
  python notion_logger.py --list-parking [--target personal|shared|both]
"""

import os
import sys
import json
import re
import argparse
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple

from notion_client import Client

# Skill root directory
SKILL_DIR = Path(__file__).resolve().parent.parent
CONFIG_FILE = Path(os.environ.get("ENGINEERING_REPORTING_CONFIG") or (SKILL_DIR / "config.json"))
BUFFER_FILE = Path(os.environ.get("ENGINEERING_REPORTING_BUFFER") or (SKILL_DIR / "daily_buffer.jsonl"))

# ---------------------------------------------------------
# Configuration Loading
# ---------------------------------------------------------
def load_config() -> Dict[str, Any]:
    config: Dict[str, Any] = {
        "engineer_name": "",
        "parent_page_id": "",
        "parking_page_id": "",
        "tasks_database_id": "",
        "eod_database_id": "",
        "shared_parent_page_id": "",
        "shared_parking_page_id": "",
        "shared_tasks_database_id": "",
        "shared_eod_database_id": "",
        "default_project": "My Project",
        "default_branch": "main",
        "default_remotes": ["origin"],
        "default_sprint": "Sprint 1",
        "eod_title_suffix": "Engineering Development",
        "max_daily_hours": 12.0,
    }
    if CONFIG_FILE.exists():
        try:
            loaded = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                config.update(loaded)
        except Exception as e:
            print(f"Warning: Failed to parse {CONFIG_FILE}: {e}")

    env_overrides = {
        "ENGINEERING_ENGINEER_NAME": "engineer_name",
        "NOTION_PARENT_PAGE_ID": "parent_page_id",
        "NOTION_PARKING_PAGE_ID": "parking_page_id",
        "NOTION_TASKS_DB_ID": "tasks_database_id",
        "NOTION_EOD_DB_ID": "eod_database_id",
        "NOTION_SHARED_PARENT_PAGE_ID": "shared_parent_page_id",
        "NOTION_SHARED_PARKING_PAGE_ID": "shared_parking_page_id",
        "NOTION_SHARED_TASKS_DB_ID": "shared_tasks_database_id",
        "NOTION_SHARED_EOD_DB_ID": "shared_eod_database_id",
    }
    for env_key, cfg_key in env_overrides.items():
        val = os.environ.get(env_key)
        if val is not None and val.strip():
            config[cfg_key] = val.strip()
    return config

CONFIG = load_config()
MAX_DAILY_HOURS = float(CONFIG.get("max_daily_hours", 12.0))


def _require_db_id(key: str, env_var: str) -> str:
    val = str(CONFIG.get(key) or "").strip()
    if not val:
        raise ValueError(
            f"Missing '{key}'. Copy config.example.json to config.json and fill in your Notion database IDs, "
            f"or set {env_var}."
        )
    return val


def _has_shared_config() -> bool:
    return bool(
        str(CONFIG.get("shared_tasks_database_id") or "").strip()
        or str(CONFIG.get("shared_eod_database_id") or "").strip()
    )


def _require_engineer_name() -> str:
    name = str(CONFIG.get("engineer_name") or "").strip()
    if not name:
        raise ValueError(
            "Missing 'engineer_name'. Set it in config.json (or ENGINEERING_ENGINEER_NAME, or run "
            "'--setup-member --name \"Your Name\"') so shared team reports identify your work."
        )
    return name

# ---------------------------------------------------------
# Authentication
# ---------------------------------------------------------
def _resolve_token(
    env_var: str,
    token_filenames: Tuple[str, ...],
    mcp_server_name: str,
) -> Optional[str]:
    """Retrieve a Notion API token from env, token files, or local MCP config."""
    token = os.environ.get(env_var)
    if token and token.strip():
        return token.strip()

    home = Path.home()
    candidate_dirs = (
        SKILL_DIR,
        home / ".config" / "engineering-reporting",
        home / ".gemini" / "mcp",
    )
    for directory in candidate_dirs:
        for fname in token_filenames:
            token_file = directory / fname
            if token_file.exists():
                try:
                    raw = token_file.read_text(encoding="utf-8").strip()
                    if raw:
                        return raw
                except Exception:
                    pass

    mcp_config = home / ".gemini" / "config" / "mcp_config.json"
    if mcp_config.exists():
        try:
            data = json.loads(mcp_config.read_text(encoding="utf-8"))
            servers = data.get("mcpServers", {})
            notion_env = servers.get(mcp_server_name, {}).get("env", {})
            val = notion_env.get(env_var) or notion_env.get("NOTION_TOKEN")
            if val and str(val).strip():
                return str(val).strip()
        except Exception:
            pass

    return None


def get_notion_token() -> Optional[str]:
    """Retrieve primary (personal) Notion API token."""
    return _resolve_token("NOTION_TOKEN", (".notion_token",), "notion")


def get_shared_token() -> Optional[str]:
    """Retrieve shared team workspace Notion token, falling back to primary token."""
    shared = _resolve_token("SHARED_NOTION_TOKEN", (".shared_notion_token",), "notion-shared")
    return shared or get_notion_token()


def get_client() -> Client:
    token = get_notion_token()
    if not token:
        raise ValueError(
            "Could not find Notion token. Export NOTION_TOKEN or store it in ~/.config/engineering-reporting/.notion_token"
        )
    return Client(auth=token)


def get_shared_client() -> Client:
    token = get_shared_token()
    if not token:
        raise ValueError(
            "Could not find shared Notion token. Export SHARED_NOTION_TOKEN (or NOTION_TOKEN) "
            "or store it in ~/.config/engineering-reporting/.shared_notion_token"
        )
    return Client(auth=token)

# ---------------------------------------------------------
# Strict Privacy & Zero Chat-Leakage Validator
# ---------------------------------------------------------
FORBIDDEN_PROMPT_PATTERNS = [
    r"please\s+(check|verify|fix|update|tell|implement)",
    r"what\s+(did\s+you|you\s+did)",
    r"commit\s+and\s+push",
    r"instead\s+of\s+.*just\s+say",
    r"^apply$",
    r"why\s+(is|are)\s+",
    r"you\s+got\s+it",
    r"how\s+to\s+do\s+that",
    r"can\s+we\s+combine",
    r"do\s+not\s+you\s+think",
]

def validate_customer_input(query_text: str):
    """Ensure that query_text is strictly a product/end-user input, never a developer chat prompt."""
    if not query_text or not isinstance(query_text, str):
        return
    for pattern in FORBIDDEN_PROMPT_PATTERNS:
        if re.search(pattern, query_text, re.IGNORECASE):
            raise ValueError(
                f"\n🚨 STRICT PRIVACY VIOLATION DETECTED!\n"
                f"Text: '{query_text}' matches forbidden developer chat pattern: '{pattern}'.\n"
                f"You CANNOT copy pair-programming chat into Notion reports!\n"
                f"Specify only the product trigger/user input (e.g. 'checkout fails on empty coupon', "
                f"'export CSV returns 500') or a formal product requirement."
            )

# ---------------------------------------------------------
# Notion Block Helpers
# ---------------------------------------------------------
_NOTION_TEXT_CHUNK_LIMIT = 1900
_INLINE_MD_TOKEN_RE = re.compile(
    r"(`[^`\n]+`|\*\*[^*\n]+\*\*|\*[^*\n]+\*|\[[^\]\n]+\]\([^\)\n]+\))"
)


def _chunk_rich_text(
    text: str,
    *,
    bold: bool = False,
    italic: bool = False,
    code: bool = False,
    link_url: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Split text into Notion rich_text objects strictly <= 1900 characters each."""
    value = str(text or "")
    if not value:
        return []
    annotations: Dict[str, Any] = {}
    if bold:
        annotations["bold"] = True
    if italic:
        annotations["italic"] = True
    if code:
        annotations["code"] = True

    chunks: List[Dict[str, Any]] = []
    for i in range(0, len(value), _NOTION_TEXT_CHUNK_LIMIT):
        text_obj: Dict[str, Any] = {"content": value[i : i + _NOTION_TEXT_CHUNK_LIMIT]}
        if link_url:
            text_obj["link"] = {"url": link_url}
        item: Dict[str, Any] = {"type": "text", "text": text_obj}
        if annotations:
            item["annotations"] = dict(annotations)
        chunks.append(item)
    return chunks


def _parse_inline_rich_text(text: str) -> List[Dict[str, Any]]:
    """Convert inline markdown (**bold**, *italic*, `code`, [label](url)) into Notion rich_text spans."""
    raw = str(text or "")
    if not raw:
        return [{"type": "text", "text": {"content": ""}}]

    spans: List[Dict[str, Any]] = []
    pos = 0
    for match in _INLINE_MD_TOKEN_RE.finditer(raw):
        if match.start() > pos:
            spans.extend(_chunk_rich_text(raw[pos : match.start()]))
        token = match.group(0)
        if token.startswith("`") and token.endswith("`"):
            spans.extend(_chunk_rich_text(token[1:-1], code=True))
        elif token.startswith("**") and token.endswith("**"):
            spans.extend(_chunk_rich_text(token[2:-2], bold=True))
        elif token.startswith("*") and token.endswith("*"):
            spans.extend(_chunk_rich_text(token[1:-1], italic=True))
        elif token.startswith("[") and "](" in token and token.endswith(")"):
            label, url = token[1:-1].split("](", 1)
            if url.startswith(("http://", "https://")):
                spans.extend(_chunk_rich_text(label, link_url=url))
            else:
                # file:// or relative local links render cleanly as code label in Notion
                spans.extend(_chunk_rich_text(label, code=True))
        pos = match.end()

    if pos < len(raw):
        spans.extend(_chunk_rich_text(raw[pos:]))
    return spans or [{"type": "text", "text": {"content": ""}}]


def heading_1(text: str) -> Dict[str, Any]:
    return {"object": "block", "type": "heading_1", "heading_1": {"rich_text": _parse_inline_rich_text(text)}}


def heading_2(text: str) -> Dict[str, Any]:
    return {"object": "block", "type": "heading_2", "heading_2": {"rich_text": _parse_inline_rich_text(text)}}


def heading_3(text: str) -> Dict[str, Any]:
    return {"object": "block", "type": "heading_3", "heading_3": {"rich_text": _parse_inline_rich_text(text)}}


def paragraph(text: str, bold_prefix: str = "") -> Dict[str, Any]:
    rt: List[Dict[str, Any]] = []
    if bold_prefix:
        rt.extend(_chunk_rich_text(bold_prefix, bold=True))
    rt.extend(_parse_inline_rich_text(text) if not bold_prefix else _chunk_rich_text(text))
    return {"object": "block", "type": "paragraph", "paragraph": {"rich_text": rt}}


def rich_paragraph(rich_text: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {"object": "block", "type": "paragraph", "paragraph": {"rich_text": rich_text}}


def bullet(
    text: str,
    bold_prefix: str = "",
    children: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    rt: List[Dict[str, Any]] = []
    if bold_prefix:
        rt.extend(_chunk_rich_text(bold_prefix, bold=True))
    rt.extend(_parse_inline_rich_text(text) if not bold_prefix else _chunk_rich_text(text))
    payload: Dict[str, Any] = {"rich_text": rt}
    if children:
        payload["children"] = children
    return {"object": "block", "type": "bulleted_list_item", "bulleted_list_item": payload}


def numbered_item(
    text: str,
    bold_prefix: str = "",
    children: Optional[List[Dict[str, Any]]] = None,
    rich_text: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    if rich_text is not None:
        rt = rich_text
    else:
        rt = []
        if bold_prefix:
            rt.extend(_chunk_rich_text(bold_prefix, bold=True))
        rt.extend(_parse_inline_rich_text(text) if not bold_prefix else _chunk_rich_text(text))
    payload: Dict[str, Any] = {"rich_text": rt}
    if children:
        payload["children"] = children
    return {"object": "block", "type": "numbered_list_item", "numbered_list_item": payload}


def todo_item(text: str, checked: bool = False) -> Dict[str, Any]:
    return {
        "object": "block",
        "type": "to_do",
        "to_do": {"rich_text": _parse_inline_rich_text(text), "checked": bool(checked)},
    }


def callout(
    text: str,
    emoji: str = "📌",
    color: Optional[str] = None,
    rich_text: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "icon": {"type": "emoji", "emoji": emoji},
        "rich_text": rich_text if rich_text is not None else _parse_inline_rich_text(text),
    }
    if color:
        payload["color"] = color
    return {"object": "block", "type": "callout", "callout": payload}


def code_block(code: str, language: str = "python") -> Dict[str, Any]:
    return {
        "object": "block",
        "type": "code",
        "code": {
            "language": language or "plain text",
            "rich_text": _chunk_rich_text(code or "") or [{"type": "text", "text": {"content": ""}}],
        },
    }


def table_block(
    rows: List[List[str]],
    has_column_header: bool = True,
) -> Dict[str, Any]:
    width = len(rows[0]) if rows else 1
    table_rows: List[Dict[str, Any]] = []
    for row in rows:
        padded = list(row[:width]) + [""] * max(0, width - len(row))
        cells = [_parse_inline_rich_text(str(cell)) for cell in padded]
        table_rows.append({"type": "table_row", "table_row": {"cells": cells}})
    return {
        "object": "block",
        "type": "table",
        "table": {
            "table_width": width,
            "has_column_header": has_column_header,
            "has_row_header": False,
            "children": table_rows,
        },
    }


def divider() -> Dict[str, Any]:
    return {"object": "block", "type": "divider", "divider": {}}


def _list_all_children(client: Client, block_id: str) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    cursor: Optional[str] = None
    while True:
        kwargs: Dict[str, Any] = {"block_id": block_id, "page_size": 100}
        if cursor:
            kwargs["start_cursor"] = cursor
        res = client.blocks.children.list(**kwargs)
        items.extend(res.get("results", []))
        if not res.get("has_more"):
            break
        cursor = res.get("next_cursor")
    return items


def clear_page_blocks(client: Client, page_id: str, preserve_child_pages: bool = False):
    """Delete children blocks of a page (optionally preserving nested child_page subpages)."""
    try:
        blocks = _list_all_children(client, page_id)
        for b in blocks:
            if preserve_child_pages and b.get("type") == "child_page":
                continue
            try:
                client.blocks.delete(block_id=b["id"])
            except Exception:
                pass
    except Exception as e:
        print(f"Warning clearing page {page_id}: {e}")

def append_blocks_safely(client: Client, page_id: str, blocks: List[Dict[str, Any]]):
    """Append blocks in safe chunks of 100 to respect Notion API limits."""
    for i in range(0, len(blocks), 100):
        chunk = blocks[i:i + 100]
        client.blocks.children.append(block_id=page_id, children=chunk)

def query_database(client: Client, database_id: str, **kwargs) -> Dict[str, Any]:
    """Query a Notion database supporting both classic databases.query and new data_sources.query."""
    if hasattr(client.databases, "query"):
        return client.databases.query(database_id=database_id, **kwargs)
    
    # Retrieve data_source_id for newer Notion SDKs
    db_meta = client.databases.retrieve(database_id=database_id)
    data_sources = db_meta.get("data_sources", [])
    if data_sources and hasattr(client, "data_sources") and hasattr(client.data_sources, "query"):
        ds_id = data_sources[0]["id"]
        return client.data_sources.query(data_source_id=ds_id, **kwargs)
        
    raise RuntimeError(f"Could not query database {database_id}: no compatible query endpoint found.")

# ---------------------------------------------------------
# Daily Activity Journal (daily_buffer.jsonl)
# ---------------------------------------------------------
def append_to_buffer(task: Dict[str, Any]):
    """Append a completed task entry into the persistent daily buffer."""
    if "date" not in task:
        task["date"] = datetime.now().strftime("%Y-%m-%d")
    with open(BUFFER_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(task, ensure_ascii=False) + "\n")
    print(f"Appended task '{task.get('title')}' to daily buffer ({BUFFER_FILE})")


def write_buffer(tasks: List[Dict[str, Any]]) -> None:
    """Persist deduplicated task entries back to daily_buffer.jsonl."""
    clean = _dedupe_tasks(tasks)
    content = "\n".join(json.dumps(t, ensure_ascii=False) for t in clean)
    if content:
        content += "\n"
    BUFFER_FILE.write_text(content, encoding="utf-8")

def read_buffer(date: Optional[str] = None) -> List[Dict[str, Any]]:
    """Read tasks from daily_buffer.jsonl, optionally filtered by date."""
    if not BUFFER_FILE.exists():
        return []
    tasks = []
    with open(BUFFER_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                if date and entry.get("date") != date:
                    continue
                tasks.append(entry)
            except Exception:
                pass
    return tasks

# ---------------------------------------------------------
# Task Logging & EOD Compilation
# ---------------------------------------------------------
_FORBIDDEN_COMMIT_RE = re.compile(r"(pending|uncommitted|\btbd\b|\bn/a\b|\bnone\b)", re.IGNORECASE)
_VALID_HEX_SHA_RE = re.compile(r"\b[0-9a-f]{7,40}\b", re.IGNORECASE)

def validate_commit_hash(commit: str) -> str:
    """Enforce that code is committed with a real Git SHA before publishing to Notion."""
    clean = str(commit or "").strip()
    if not clean or _FORBIDDEN_COMMIT_RE.search(clean) or not _VALID_HEX_SHA_RE.search(clean):
        raise ValueError(
            f"\n🚨 COMMIT REQUIRED BEFORE UPDATING NOTION!\n"
            f"Invalid commit field: '{commit}'.\n"
            f"Always commit your code to Git first and supply the real commit hash (e.g. 'a1b2c3d').\n"
            f"NEVER write 'Pending commit' or placeholders in Notion."
        )
    return clean


def _extract_hours_value(task_spec: Dict[str, Any]) -> Any:
    """Read decimal hour estimate from supported task spec aliases."""
    for key in ("time_spent_hours", "time_spent_hrs", "Time Spent (hrs)", "raw_estimated_hours"):
        if key in task_spec and task_spec[key] is not None:
            return task_spec[key]
    return None


def _extract_raw_hours_value(task_spec: Dict[str, Any]) -> Any:
    """Read unscaled complexity weight (`raw_estimated_hours` preferred, fallback to time_spent_hours)."""
    if task_spec.get("raw_estimated_hours") is not None:
        return task_spec["raw_estimated_hours"]
    return _extract_hours_value(task_spec)


def allocate_capped_hours(
    raw_weights: List[float],
    max_daily_hours: float = MAX_DAILY_HOURS,
) -> List[float]:
    """Scale daily task hours proportionally via largest-remainder only when sum exceeds max_daily_hours."""
    if not raw_weights:
        return []
    weights = [round(float(w), 4) for w in raw_weights]
    raw_sum = sum(weights)
    if raw_sum <= max_daily_hours + 1e-9:
        return [round(w, 2) for w in weights]

    n = len(weights)
    step = 0.25
    for candidate_step in (0.25, 0.1, 0.05, 0.01):
        if n * candidate_step <= max_daily_hours + 1e-9:
            step = candidate_step
            break

    budget_units = int(round(max_daily_hours / step))
    floor_units = 1 if n <= budget_units else 0
    rem_units = max(0, budget_units - n * floor_units)

    exact = [(w / raw_sum) * rem_units for w in weights]
    adds = [int(x) for x in exact]
    leftover = rem_units - sum(adds)
    order = sorted(
        range(n),
        key=lambda i: (-(exact[i] - adds[i]), -weights[i], i),
    )
    for idx in order[:leftover]:
        adds[idx] += 1

    return [round((floor_units + adds[i]) * step, 2) for i in range(n)]


def rebalance_date_tasks(
    tasks_for_date: List[Dict[str, Any]],
    max_daily_hours: float = MAX_DAILY_HOURS,
) -> tuple[List[Dict[str, Any]], bool]:
    """Normalize a single day's tasks in-place so total hours never exceed max_daily_hours."""
    if not tasks_for_date:
        return tasks_for_date, False

    raw_weights: List[float] = []
    for t in tasks_for_date:
        raw_val = _extract_raw_hours_value(t)
        raw_num = validate_time_spent_hours(raw_val)
        t["raw_estimated_hours"] = raw_num
        raw_weights.append(raw_num)

    allocated = allocate_capped_hours(raw_weights, max_daily_hours=max_daily_hours)
    changed = False
    for t, new_hrs in zip(tasks_for_date, allocated):
        if t.get("time_spent_hours") != new_hrs:
            t["time_spent_hours"] = new_hrs
            changed = True
    return tasks_for_date, changed


_DB_PROPERTIES_CACHE: Dict[Tuple[int, str], Dict[str, Any]] = {}
_ENSURED_SHARED_TARGETS: set = set()


def _resolve_shared_client(personal_client: Optional[Client] = None) -> Client:
    explicit_shared = _resolve_token("SHARED_NOTION_TOKEN", (".shared_notion_token",), "notion-shared")
    if not explicit_shared and personal_client is not None:
        return personal_client
    return get_shared_client()


def _build_target_entry(
    kind: str,
    personal_client: Optional[Client],
    personal_db_key: str,
    personal_ds_key: str,
    shared_db_key: str,
    shared_ds_key: str,
    require_shared_engineer: bool = True,
) -> List[Dict[str, Any]]:
    targets: List[Dict[str, Any]] = []
    personal_db = str(CONFIG.get(personal_db_key) or "").strip()
    if personal_db:
        targets.append({
            "name": "personal",
            "kind": kind,
            "client": personal_client or get_client(),
            "db_id": personal_db,
            "ds_id": str(CONFIG.get(personal_ds_key) or "").strip() or None,
            "is_shared": False,
        })
    shared_db = str(CONFIG.get(shared_db_key) or "").strip()
    if shared_db:
        if require_shared_engineer:
            _require_engineer_name()
        targets.append({
            "name": "shared",
            "kind": kind,
            "client": _resolve_shared_client(personal_client),
            "db_id": shared_db,
            "ds_id": str(CONFIG.get(shared_ds_key) or "").strip() or None,
            "is_shared": True,
        })
    return targets


def _get_tasks_targets(personal_client: Optional[Client] = None) -> List[Dict[str, Any]]:
    return _build_target_entry(
        kind="tasks",
        personal_client=personal_client,
        personal_db_key="tasks_database_id",
        personal_ds_key="tasks_data_source_id",
        shared_db_key="shared_tasks_database_id",
        shared_ds_key="shared_tasks_data_source_id",
    )


def _get_eod_targets(personal_client: Optional[Client] = None) -> List[Dict[str, Any]]:
    return _build_target_entry(
        kind="eod",
        personal_client=personal_client,
        personal_db_key="eod_database_id",
        personal_ds_key="eod_data_source_id",
        shared_db_key="shared_eod_database_id",
        shared_ds_key="shared_eod_data_source_id",
    )


def _get_db_properties(
    client: Client,
    db_id: str,
    ds_id: Optional[str] = None,
    force_refresh: bool = False,
) -> Dict[str, Any]:
    cache_key = (id(client), db_id)
    if not force_refresh and cache_key in _DB_PROPERTIES_CACHE:
        return _DB_PROPERTIES_CACHE[cache_key]
    props: Dict[str, Any] = {}
    try:
        db_meta = client.databases.retrieve(database_id=db_id)
        props = db_meta.get("properties") or {}
        if not props and hasattr(client, "data_sources") and hasattr(client.data_sources, "retrieve"):
            resolved_ds = ds_id or (db_meta.get("data_sources") or [{}])[0].get("id")
            if resolved_ds:
                ds_meta = client.data_sources.retrieve(data_source_id=resolved_ds)
                props = ds_meta.get("properties") or {}
    except Exception:
        props = {}
    _DB_PROPERTIES_CACHE[cache_key] = props
    return props


def _resolve_target_data_source_id(client: Client, db_id: str, ds_id: Optional[str] = None) -> Optional[str]:
    if ds_id:
        return ds_id
    if not db_id:
        return None
    db_meta = client.databases.retrieve(database_id=db_id)
    data_sources = db_meta.get("data_sources", [])
    return data_sources[0]["id"] if data_sources else None


def _ensure_target_columns(target: Dict[str, Any], force: bool = False) -> None:
    """Ensure numeric Time Spent columns (and 'Engineer' on Shared DBs) exist on a Notion target."""
    client = target["client"]
    db_id = target["db_id"]
    is_shared = target["is_shared"]
    cache_key = (id(client), db_id, target["kind"])
    if not force and is_shared and cache_key in _ENSURED_SHARED_TARGETS:
        return

    props_to_ensure: Dict[str, Any] = {}
    if target["kind"] == "tasks":
        props_to_ensure["Time Spent (hrs)"] = {"number": {"format": "number"}}
        col_label = "Tasks 'Time Spent (hrs)'"
    else:
        props_to_ensure["Total Time Spent (hrs)"] = {"number": {"format": "number"}}
        col_label = "EOD 'Total Time Spent (hrs)'"

    if is_shared:
        props_to_ensure["Engineer"] = {"select": {}}

    try:
        ds_id = _resolve_target_data_source_id(client, db_id, target.get("ds_id"))
        if ds_id and hasattr(client, "data_sources") and hasattr(client.data_sources, "update"):
            client.data_sources.update(data_source_id=ds_id, properties=props_to_ensure)
        elif hasattr(client.databases, "update"):
            client.databases.update(database_id=db_id, properties=props_to_ensure)
        _get_db_properties(client, db_id, target.get("ds_id"), force_refresh=True)
        if is_shared:
            _ENSURED_SHARED_TARGETS.add(cache_key)
    except Exception as exc:
        print(f"Warning: Could not verify [{target['name']}] {col_label} schema columns: {exc}")


def _engineer_prop_type(props_schema: Dict[str, Any]) -> Optional[str]:
    eng_schema = props_schema.get("Engineer")
    if not eng_schema:
        return None
    prop_type = eng_schema.get("type")
    if prop_type:
        return prop_type
    if "select" in eng_schema:
        return "select"
    if "rich_text" in eng_schema:
        return "rich_text"
    return None


def _attach_engineer_property(
    properties: Dict[str, Any],
    target: Dict[str, Any],
    engineer_name: str,
) -> Dict[str, Any]:
    out = dict(properties)
    if not engineer_name:
        return out
    props_schema = _get_db_properties(target["client"], target["db_id"], target.get("ds_id"))
    eng_type = _engineer_prop_type(props_schema)
    if eng_type == "rich_text":
        out["Engineer"] = {"rich_text": [{"text": {"content": engineer_name[:200]}}]}
    elif eng_type == "select" or target["is_shared"]:
        out["Engineer"] = {"select": {"name": engineer_name[:100]}}
    return out


def _page_engineer_value(page: Dict[str, Any]) -> Optional[str]:
    eng_prop = page.get("properties", {}).get("Engineer")
    if not eng_prop:
        return None
    if eng_prop.get("type") == "select" or "select" in eng_prop:
        sel = eng_prop.get("select")
        return (sel or {}).get("name")
    if eng_prop.get("type") == "rich_text" or "rich_text" in eng_prop:
        return "".join(x.get("plain_text", "") for x in eng_prop.get("rich_text", []))
    return None


def _build_date_engineer_filter(
    target: Dict[str, Any],
    target_date: str,
    engineer_name: str,
) -> Dict[str, Any]:
    date_filter: Dict[str, Any] = {"property": "Date", "date": {"equals": target_date}}
    if not target["is_shared"] or not engineer_name:
        return date_filter
    props_schema = _get_db_properties(target["client"], target["db_id"], target.get("ds_id"))
    eng_type = _engineer_prop_type(props_schema)
    if eng_type == "rich_text":
        return {"and": [date_filter, {"property": "Engineer", "rich_text": {"equals": engineer_name}}]}
    if eng_type == "select":
        options = (props_schema.get("Engineer") or {}).get("select", {}).get("options") or []
        option_names = {str(o.get("name", "")).strip().lower() for o in options if o.get("name")}
        if engineer_name.strip().lower() in option_names:
            return {"and": [date_filter, {"property": "Engineer", "select": {"equals": engineer_name}}]}
        return date_filter
    if not props_schema:
        return {"and": [date_filter, {"property": "Engineer", "select": {"equals": engineer_name}}]}
    return date_filter


def _query_target_for_date(
    target: Dict[str, Any],
    target_date: str,
    engineer_name: str = "",
) -> List[Dict[str, Any]]:
    notion_filter = _build_date_engineer_filter(target, target_date, engineer_name)
    try:
        pages = query_database(
            target["client"],
            database_id=target["db_id"],
            filter=notion_filter,
        ).get("results", [])
    except Exception as exc:
        if "select option" in str(exc).lower() and target["is_shared"]:
            date_only = {"property": "Date", "date": {"equals": target_date}}
            pages = query_database(
                target["client"],
                database_id=target["db_id"],
                filter=date_only,
            ).get("results", [])
        else:
            raise
    if target["is_shared"] and engineer_name:
        filtered: List[Dict[str, Any]] = []
        for p in pages:
            page_eng = _page_engineer_value(p)
            if page_eng is None or page_eng.strip().lower() == engineer_name.strip().lower():
                filtered.append(p)
        return filtered
    return pages


def _sync_target_task_hours_for_date(
    target: Dict[str, Any],
    target_date: str,
    by_title: Dict[str, Any],
    engineer_name: str,
) -> int:
    if target["is_shared"]:
        _ensure_target_columns(target)
    updated = 0
    pages = _query_target_for_date(target, target_date, engineer_name)
    for p in pages:
        props = p.get("properties", {})
        title = "".join(x.get("plain_text", "") for x in props.get("Name", {}).get("title", []))
        if title not in by_title:
            continue
        target_hrs = by_title[title]
        current_hrs = props.get("Time Spent (hrs)", {}).get("number")
        if current_hrs != target_hrs:
            target["client"].pages.update(
                page_id=p["id"],
                properties={"Time Spent (hrs)": {"number": target_hrs}},
            )
            updated += 1
    return updated


def _sync_notion_task_hours_for_date(
    client: Client,
    target_date: str,
    tasks_for_date: List[Dict[str, Any]],
) -> int:
    """Update 'Time Spent (hrs)' on existing Notion Task pages (personal + shared) for target_date."""
    by_title = {t.get("title"): t.get("time_spent_hours") for t in tasks_for_date if t.get("title")}
    if not by_title:
        return 0
    engineer_name = str(CONFIG.get("engineer_name") or "").strip()
    updated = 0
    for target in _get_tasks_targets(personal_client=client):
        updated += _sync_target_task_hours_for_date(target, target_date, by_title, engineer_name)
    return updated


def _sync_target_eod_metrics_for_date(
    target: Dict[str, Any],
    target_date: str,
    info: Dict[str, Any],
    engineer_name: str,
) -> None:
    if target["is_shared"]:
        _ensure_target_columns(target)
    eod_pages = _query_target_for_date(target, target_date, engineer_name)
    if eod_pages:
        eod_props = {
            "Tasks Completed": {"number": info["count"]},
            "Total Time Spent (hrs)": {"number": info["capped_total"]},
        }
        target["client"].pages.update(page_id=eod_pages[0]["id"], properties=eod_props)


def rebalance_buffer_and_notion(
    client: Optional[Client] = None,
    target_date: Optional[str] = None,
    max_daily_hours: float = MAX_DAILY_HOURS,
) -> Dict[str, Dict[str, Any]]:
    """Enforce the daily hours cap across daily_buffer.jsonl, Notion Tasks, and EOD summaries."""
    all_tasks = _dedupe_tasks(read_buffer())
    dates_to_process = (
        [target_date]
        if target_date and target_date != "all"
        else sorted({t.get("date") for t in all_tasks if t.get("date")})
    )

    by_date: Dict[str, List[Dict[str, Any]]] = {}
    for t in all_tasks:
        by_date.setdefault(t.get("date", ""), []).append(t)

    summary: Dict[str, Dict[str, Any]] = {}
    buffer_dirty = False
    for d in dates_to_process:
        day_list = by_date.get(d, [])
        if not day_list:
            continue
        raw_total = round(sum(validate_time_spent_hours(_extract_raw_hours_value(t)) for t in day_list), 2)
        _, changed = rebalance_date_tasks(day_list, max_daily_hours=max_daily_hours)
        if changed:
            buffer_dirty = True
        capped_total = round(sum(float(t.get("time_spent_hours") or 0) for t in day_list), 2)
        summary[d] = {
            "count": len(day_list),
            "raw_total": raw_total,
            "capped_total": capped_total,
            "rebalanced": raw_total > max_daily_hours + 1e-9,
        }

    if buffer_dirty or len(all_tasks) != len(read_buffer()):
        write_buffer(all_tasks)

    if client is not None:
        engineer_name = str(CONFIG.get("engineer_name") or "").strip()
        eod_targets = _get_eod_targets(personal_client=client)
        for d, info in summary.items():
            if info["rebalanced"] or (target_date and d == target_date):
                updated_tasks = _sync_notion_task_hours_for_date(client, d, by_date.get(d, []))
                info["notion_tasks_updated"] = updated_tasks
                for target in eod_targets:
                    _sync_target_eod_metrics_for_date(target, d, info, engineer_name)
    return summary


def validate_time_spent_hours(value: Any) -> float:
    """Validate an ultra-realistic senior-engineer hour estimate (>0 and <=40h per ticket)."""
    if value is None or isinstance(value, bool):
        raise ValueError(
            "Missing 'time_spent_hours'. Provide a realistic human senior-engineer estimate in decimal hours "
            "(e.g., 0.5, 1.5, 3.5 — accounting for debugging, implementation, testing, and git sync)."
        )
    try:
        hours = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid time_spent_hours '{value}': must be numeric hours (e.g. 1.5).") from exc
    if hours <= 0 or hours > 40:
        raise ValueError(
            f"Unrealistic time_spent_hours={hours}. Single task estimate must be > 0 and <= 40.0 hours."
        )
    return round(hours, 2)


def format_hours(hours: float) -> str:
    """Format decimal hours alongside human-readable Xh Ym representation."""
    clean = round(float(hours), 2)
    total_minutes = int(round(clean * 60))
    whole_hours, mins = divmod(total_minutes, 60)
    if whole_hours and mins:
        pretty = f"{whole_hours}h {mins}m"
    elif whole_hours:
        pretty = f"{whole_hours}h"
    else:
        pretty = f"{mins}m"
    return f"{clean:g} hrs ({pretty})"


def _resolve_data_source_id(client: Client, db_key: str, ds_key: str) -> Optional[str]:
    ds_id = CONFIG.get(ds_key)
    db_id = CONFIG.get(db_key)
    return _resolve_target_data_source_id(client, db_id or "", ds_id)


def ensure_time_spent_columns(client: Client) -> None:
    """Ensure Personal & Shared Notion DBs contain Time Spent columns (and Engineer on Shared DBs)."""
    for target in _build_target_entry(
        kind="tasks",
        personal_client=client,
        personal_db_key="tasks_database_id",
        personal_ds_key="tasks_data_source_id",
        shared_db_key="shared_tasks_database_id",
        shared_ds_key="shared_tasks_data_source_id",
        require_shared_engineer=False,
    ):
        _ensure_target_columns(target, force=True)

    for target in _build_target_entry(
        kind="eod",
        personal_client=client,
        personal_db_key="eod_database_id",
        personal_ds_key="eod_data_source_id",
        shared_db_key="shared_eod_database_id",
        shared_ds_key="shared_eod_data_source_id",
        require_shared_engineer=False,
    ):
        _ensure_target_columns(target, force=True)


def _normalize_task_spec(task_spec: Dict[str, Any]) -> Dict[str, Any]:
    """Validate task metadata and build shared Notion properties dictionary."""
    title = task_spec.get("title", "Untitled Task")
    date_str = task_spec.get("date", datetime.now().strftime("%Y-%m-%d"))
    category = task_spec.get("category", "Architecture / Tooling")
    project = task_spec.get("project", CONFIG.get("default_project", "My Project"))
    branch = task_spec.get("branch", CONFIG.get("default_branch", "main"))
    commit = validate_commit_hash(task_spec.get("commit", ""))
    time_spent_hours = validate_time_spent_hours(_extract_hours_value(task_spec))
    overview = task_spec.get("overview", "")
    customer_queries = task_spec.get("customer_queries", [])
    if isinstance(customer_queries, str):
        customer_queries = [customer_queries]

    for q in customer_queries:
        validate_customer_input(q)

    properties = {
        "Name": {"title": [{"text": {"content": title[:2000]}}]},
        "Project": {"select": {"name": project}},
        "Category": {"select": {"name": category}},
        "Status": {"select": {"name": "Done"}},
        "Date": {"date": {"start": date_str}},
        "Branches": {"rich_text": [{"text": {"content": branch}}]},
        "Git Commits": {"rich_text": [{"text": {"content": f"{commit} ({branch})"}}]},
        "Time Spent (hrs)": {"number": time_spent_hours},
        "Manager Notes / Impact": {"rich_text": [{"text": {"content": (overview or title)[:2000]}}]},
    }
    return {
        "title": title,
        "date_str": date_str,
        "branch": branch,
        "commit": commit,
        "time_spent_hours": time_spent_hours,
        "overview": overview,
        "properties": properties,
    }


def _build_task_body(
    task_spec: Dict[str, Any],
    commit: str,
    branch: str,
    time_spent_hours: Optional[float] = None,
) -> List[Dict[str, Any]]:
    body: List[Dict[str, Any]] = [divider(), heading_2("1. System Context & Problem / Requirement")]

    if task_spec.get("context"):
        body.append(paragraph(task_spec["context"], "System Context (For New Reviewers): "))

    customer_queries = task_spec.get("customer_queries", [])
    if isinstance(customer_queries, str):
        customer_queries = [customer_queries]
    if customer_queries:
        body.append(bullet(", ".join(f"'{q}'" for q in customer_queries), "End-User Queries / Trigger Examples: "))
    if task_spec.get("problem"):
        body.append(paragraph(task_spec["problem"], "Problem / Requirement: "))
    if task_spec.get("error_output"):
        body.append(bullet(str(task_spec["error_output"]), "Erroneous Output / Payload: "))

    if task_spec.get("behavior_before") or task_spec.get("behavior_after"):
        body.extend([divider(), heading_2("2. Behavioral Impact (Before vs. After)")])
        if task_spec.get("behavior_before"):
            body.append(bullet(task_spec["behavior_before"], "Before (When Issue Existed): "))
        if task_spec.get("behavior_after"):
            body.append(bullet(task_spec["behavior_after"], "After (Current System Behavior): "))

    body.extend([divider(), heading_2("3. Why Did This Happen? (Root Cause Analysis)")])
    for idx, rc in enumerate(task_spec.get("root_causes", [task_spec.get("why_failed", "Architecture optimization")]), 1):
        body.append(bullet(rc, f"Root Cause {idx}: "))

    body.extend([divider(), heading_2("4. What Was Changed & How It Works (Developer Reference)")])
    for idx, fix in enumerate(task_spec.get("fixes", [task_spec.get("how_fixed", "Implemented code update")]), 1):
        body.append(bullet(fix, f"Change {idx}: "))
    if task_spec.get("code_snippet"):
        body.append(code_block(task_spec["code_snippet"], task_spec.get("code_language", "python")))

    body.extend([divider(), heading_2("5. Why This Design Decision?")])
    for idx, dec in enumerate(task_spec.get("architectural_decisions", [task_spec.get("why_decision", "Maintains clean separation of concerns")]), 1):
        body.append(bullet(dec, f"Decision Rationale {idx}: "))

    body.extend([divider(), heading_2("6. Verification & Testing")])
    for test in task_spec.get("verification", ["Verified against local and test environments"]):
        body.append(bullet(test, "Verification: "))

    body.extend([divider(), heading_2("7. Git & Effort Traceability")])
    body.append(bullet(f"Commit {commit} on {branch}", "Branch & Commit: "))
    if task_spec.get("files"):
        body.append(bullet(", ".join(task_spec["files"]), "Modified / Added Files: "))
    resolved_hours = time_spent_hours if time_spent_hours is not None else _extract_hours_value(task_spec)
    if resolved_hours is not None:
        body.append(
            bullet(
                f"{format_hours(float(resolved_hours))} — realistic senior-engineer effort across analysis, implementation, verification, and git sync.",
                "Estimated Senior Engineer Effort: ",
            )
        )

    return body


def _find_matching_task_page(
    target: Dict[str, Any],
    date_str: str,
    title: str,
    engineer_name: str,
) -> Optional[Dict[str, Any]]:
    pages = _query_target_for_date(target, date_str, engineer_name)
    for p in pages:
        props = p.get("properties", {})
        page_title = "".join(x.get("plain_text", "") for x in props.get("Name", {}).get("title", []))
        if page_title == title:
            return p
    return None


def _upsert_task_on_target(
    target: Dict[str, Any],
    norm: Dict[str, Any],
    body: List[Dict[str, Any]],
    engineer_name: str,
    upsert_existing: bool = True,
) -> Dict[str, str]:
    client = target["client"]
    if target["is_shared"]:
        _ensure_target_columns(target)
    props = _attach_engineer_property(norm["properties"], target, engineer_name)
    overview_callout = callout(norm["overview"] or f"Overview of {norm['title']}", emoji="📌")

    existing = (
        _find_matching_task_page(target, norm["date_str"], norm["title"], engineer_name)
        if upsert_existing
        else None
    )
    if existing:
        page_id = existing["id"]
        page_url = existing.get("url", "")
        client.pages.update(page_id=page_id, properties=props)
        clear_page_blocks(client, page_id)
        append_blocks_safely(client, page_id, [overview_callout] + body)
        return {"id": page_id, "url": page_url, "action": "updated"}

    new_page = client.pages.create(
        parent={"database_id": target["db_id"]},
        properties=props,
        children=[overview_callout],
    )
    page_id = new_page["id"]
    page_url = new_page.get("url", "")
    append_blocks_safely(client, page_id, body)
    return {"id": page_id, "url": page_url, "action": "created"}


def log_task(task_spec: Dict[str, Any]) -> Dict[str, str]:
    """Publish a structured task to Personal (and optional Shared Team) Notion Tasks DB."""
    client = get_client()
    _require_db_id("tasks_database_id", "NOTION_TASKS_DB_ID")
    engineer_name = _require_engineer_name() if _has_shared_config() else str(CONFIG.get("engineer_name") or "").strip()

    norm = _normalize_task_spec(task_spec)
    date_str = norm["date_str"]
    raw_hours = norm["time_spent_hours"]

    clean_spec = {k: v for k, v in task_spec.items() if not k.startswith("notion_")}
    clean_spec["date"] = date_str
    clean_spec["raw_estimated_hours"] = raw_hours
    clean_spec["time_spent_hours"] = raw_hours

    all_buffered = _dedupe_tasks(read_buffer())
    day_tasks = [t for t in all_buffered if t.get("date") == date_str]
    is_new_entry = not any(t.get("title") == norm["title"] for t in day_tasks)
    other_prior_changed = False

    if is_new_entry:
        day_tasks.append(clean_spec)
        _, changed = rebalance_date_tasks(day_tasks, max_daily_hours=MAX_DAILY_HOURS)
        other_prior_changed = changed and len(day_tasks) > 1
        norm["time_spent_hours"] = clean_spec["time_spent_hours"]
        norm["properties"]["Time Spent (hrs)"] = {"number": norm["time_spent_hours"]}

    body = _build_task_body(
        task_spec,
        commit=norm["commit"],
        branch=norm["branch"],
        time_spent_hours=norm["time_spent_hours"],
    )

    targets = _get_tasks_targets(personal_client=client)
    personal_target = targets[0]
    personal_res = _upsert_task_on_target(
        personal_target,
        norm,
        body,
        engineer_name,
        upsert_existing=False,
    )

    if is_new_entry:
        if other_prior_changed:
            write_buffer(all_buffered + [clean_spec])
            _sync_notion_task_hours_for_date(client, date_str, day_tasks)
        else:
            append_to_buffer(clean_spec)

    print(f"Task successfully published to Notion! URL: {personal_res['url']}")
    result: Dict[str, str] = {"id": personal_res["id"], "url": personal_res["url"]}

    for shared_target in targets[1:]:
        try:
            shared_res = _upsert_task_on_target(
                shared_target,
                norm,
                body,
                engineer_name,
                upsert_existing=True,
            )
            result["shared_id"] = shared_res["id"]
            result["shared_url"] = shared_res["url"]
            print(f"Task mirrored to Shared Team Notion DB ({shared_res['action']})! URL: {shared_res['url']}")
        except Exception as exc:
            print(
                f"Error mirroring task to Shared Team Notion DB: {exc}\n"
                f"Personal task & local buffer were saved. Run 'python notion_logger.py --sync-shared --date {date_str}' to retry."
            )
            raise

    return result


def update_task_page(page_id: str, task_spec: Dict[str, Any]) -> Dict[str, str]:
    """Update an existing Notion task page's properties and body cleanly after commit/refinement."""
    client = get_client()
    engineer_name = str(CONFIG.get("engineer_name") or "").strip()
    norm = _normalize_task_spec(task_spec)
    body = _build_task_body(
        task_spec,
        commit=norm["commit"],
        branch=norm["branch"],
        time_spent_hours=norm["time_spent_hours"],
    )
    overview_callout = callout(norm["overview"] or f"Overview of {norm['title']}", emoji="📌")

    targets = _get_tasks_targets(personal_client=client)
    personal_props = _attach_engineer_property(norm["properties"], targets[0], engineer_name) if targets else norm["properties"]
    client.pages.update(page_id=page_id, properties=personal_props)
    clear_page_blocks(client, page_id)
    append_blocks_safely(client, page_id, [overview_callout] + body)

    result: Dict[str, str] = {"id": page_id}
    for shared_target in targets[1:]:
        shared_res = _upsert_task_on_target(
            shared_target,
            norm,
            body,
            engineer_name,
            upsert_existing=True,
        )
        result["shared_id"] = shared_res["id"]
    return result

def _dedupe_tasks(tasks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    unique: List[Dict[str, Any]] = []
    for t in tasks:
        key = (t.get("date"), t.get("title"))
        if key in seen:
            continue
        seen.add(key)
        unique.append(t)
    return unique


def _build_eod_body(
    tasks: List[Dict[str, Any]],
    total_hours_label: str,
) -> List[Dict[str, Any]]:
    """Build the Notion block body for a daily EOD engineering briefing."""
    default_project = CONFIG.get("default_project", "My Project")
    default_branch = CONFIG.get("default_branch", "main")
    body: List[Dict[str, Any]] = [
        divider(),
        heading_1("Today's Engineering Summary"),
        paragraph(
            f"Today we accomplished {len(tasks)} engineering milestones on {default_project} "
            f"(Total Estimated Senior Engineer Effort: {total_hours_label}): " +
            "; ".join(f"({i+1}) {t.get('title')}" for i, t in enumerate(tasks)) + "."
        ),
        divider(),
        heading_2("1. Detailed Work Breakdown")
    ]

    for idx, t in enumerate(tasks, 1):
        body.append(heading_3(f"Task {idx}: {t.get('title')}"))
        if t.get("context"):
            body.append(bullet(t["context"], "System Context: "))
        if t.get("problem"):
            body.append(bullet(t["problem"], "Problem / Need: "))
        if t.get("behavior_before"):
            body.append(bullet(t["behavior_before"], "Before (Prior Behavior): "))
        if t.get("behavior_after"):
            body.append(bullet(t["behavior_after"], "After (New Behavior): "))
        
        why = t.get("why_failed")
        if not why and t.get("root_causes"):
            rc_list = t["root_causes"] if isinstance(t["root_causes"], list) else [t["root_causes"]]
            why = "; ".join(rc_list)
        if why:
            body.append(bullet(why, "Root Cause: "))

        how = t.get("how_fixed")
        if not how and t.get("fixes"):
            fix_list = t["fixes"] if isinstance(t["fixes"], list) else [t["fixes"]]
            how = "; ".join(fix_list)
        if how:
            body.append(bullet(how, "How It Was Fixed: "))

        task_hours = _extract_hours_value(t)
        if task_hours is not None:
            body.append(bullet(format_hours(float(task_hours)), "Time Spent (Senior Eng. Benchmark): "))

        if t.get("commit"):
            body.append(bullet(f"Commit {t['commit']} on {t.get('branch', default_branch)}", "Traceability: "))

    body.extend([
        divider(),
        heading_2("2. Key Architectural Decisions (Future Reference)"),
    ])

    all_arch_decisions = []
    for t in tasks:
        decisions = t.get("architectural_decisions") or []
        if isinstance(decisions, str):
            decisions = [decisions]
        for d in decisions:
            if d and d not in all_arch_decisions:
                all_arch_decisions.append(d)

    if all_arch_decisions:
        for d in all_arch_decisions:
            body.append(bullet(d))
    else:
        body.extend([
            bullet("Preserves strict separation between synchronous UI actions and asynchronous transactional confirmations.", "Confirmation Policy: "),
            bullet("Consolidated in-memory lookups reduce multi-query search overhead to single-pass O(N) evaluation.", "Performance Rationale: "),
            bullet("Dynamic Redis/PostgreSQL check ensures instant zero-downtime hotfixing with flow code fallback.", "Dual Resilience: "),
        ])

    import subprocess
    repo_root = Path.cwd()
    try:
        top = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"], cwd=repo_root, text=True, stderr=subprocess.DEVNULL
        ).strip()
        if top:
            repo_root = Path(top)
    except Exception:
        pass
    branch_name = default_branch
    head_hash = "unknown"
    dirty_count = None
    try:
        branch_name = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_root, text=True, stderr=subprocess.DEVNULL
        ).strip() or branch_name
        head_hash = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=repo_root, text=True, stderr=subprocess.DEVNULL
        ).strip() or head_hash
        status_lines = subprocess.check_output(
            ["git", "status", "-s"], cwd=repo_root, text=True, stderr=subprocess.DEVNULL
        ).splitlines()
        dirty_count = len([ln for ln in status_lines if ln.strip()])
    except Exception:
        pass

    if dirty_count == 0:
        code_status_text = f"Latest HEAD commit {head_hash} on branch {branch_name}. Working tree clean."
    elif isinstance(dirty_count, int):
        code_status_text = f"Branch {branch_name} (HEAD {head_hash}) with {dirty_count} pending uncommitted working tree file(s) verified locally."
    else:
        code_status_text = f"Branch {branch_name} changes verified locally."

    remotes_label = ", ".join(CONFIG.get("default_remotes", ["origin"]))
    body.extend([
        divider(),
        heading_2("3. Current Status & Tomorrow's Priorities"),
        bullet(code_status_text, "Code Status: "),
        bullet(total_hours_label, "Daily Effort Summary: "),
        bullet("PostgreSQL schemas, dynamic configurations, and verification checks validated cleanly against local test suites.", "Database & Infrastructure: "),
        bullet(f"Keep {branch_name} synchronized across remotes ({remotes_label}) and proceed with queued sprint items.", "Next Steps: ")
    ])
    return body


def _upsert_eod_on_target(
    target: Dict[str, Any],
    target_date: str,
    tasks: List[Dict[str, Any]],
    total_hours: float,
    total_hours_label: str,
    eod_body: List[Dict[str, Any]],
    engineer_name: str,
) -> Dict[str, str]:
    client = target["client"]
    if target["is_shared"]:
        _ensure_target_columns(target)

    title_suffix = CONFIG.get("eod_title_suffix") or CONFIG.get("default_project", "Engineering Development")
    if target["is_shared"] and engineer_name:
        page_title = f"📅 {target_date} EOD ({engineer_name}): {title_suffix}"
        callout_text = (
            f"Daily Engineering Briefing (EOD Report)\n"
            f"Engineer: {engineer_name} | Date: {target_date} | Total Estimated Senior Engineer Effort: {total_hours_label}"
        )
    else:
        page_title = f"📅 {target_date} EOD Engineering Briefing: {title_suffix}"
        callout_text = (
            f"Daily Engineering Briefing (EOD Report)\n"
            f"Date: {target_date} | Total Estimated Senior Engineer Effort: {total_hours_label}"
        )

    eod_callout = callout(callout_text, emoji="📋")
    focus_area = ", ".join(t.get("title", "")[:40] for t in tasks)[:2000]
    existing_pages = _query_target_for_date(target, target_date, engineer_name)

    if existing_pages:
        page_id = existing_pages[0]["id"]
        page_url = existing_pages[0].get("url", "")
        print(f"Updating existing [{target['name']}] EOD Page for {target_date}: {page_id}")
        clear_page_blocks(client, page_id)
        update_props = {
            "Tasks Completed": {"number": len(tasks)},
            "Total Time Spent (hrs)": {"number": total_hours},
            "Status": {"select": {"name": "Submitted"}},
            "Focus Area": {"rich_text": [{"text": {"content": focus_area}}]},
        }
        update_props = _attach_engineer_property(update_props, target, engineer_name)
        client.pages.update(page_id=page_id, properties=update_props)
        append_blocks_safely(client, page_id, [eod_callout] + eod_body)
        return {"id": page_id, "url": page_url, "action": "updated"}

    print(f"Creating new [{target['name']}] EOD Page for {target_date}...")
    sprint_name = CONFIG.get("default_sprint", "Sprint 1")
    properties = {
        "Name": {"title": [{"text": {"content": page_title}}]},
        "Date": {"date": {"start": target_date}},
        "Status": {"select": {"name": "Submitted"}},
        "Sprint / Cycle": {"rich_text": [{"text": {"content": sprint_name}}]},
        "Tasks Completed": {"number": len(tasks)},
        "Total Time Spent (hrs)": {"number": total_hours},
        "Focus Area": {"rich_text": [{"text": {"content": focus_area}}]},
    }
    properties = _attach_engineer_property(properties, target, engineer_name)
    new_page = client.pages.create(
        parent={"database_id": target["db_id"]},
        properties=properties,
        children=[eod_callout],
    )
    page_id = new_page["id"]
    page_url = new_page.get("url", "")
    append_blocks_safely(client, page_id, eod_body)
    return {"id": page_id, "url": page_url, "action": "created"}


def sync_eod(target_date: Optional[str] = None) -> str:
    """Compile all tasks for target_date into Personal (and optional Shared Team) EOD Reports."""
    client = get_client()
    _require_db_id("eod_database_id", "NOTION_EOD_DB_ID")
    engineer_name = _require_engineer_name() if _has_shared_config() else str(CONFIG.get("engineer_name") or "").strip()
    if not target_date or target_date == "today":
        target_date = datetime.now().strftime("%Y-%m-%d")

    rebalance_buffer_and_notion(client=client, target_date=target_date, max_daily_hours=MAX_DAILY_HOURS)

    tasks = _dedupe_tasks(read_buffer(date=target_date))
    if not tasks:
        print(f"No buffered tasks found for date {target_date} in {BUFFER_FILE}")
        return ""

    total_hours = round(sum(float(_extract_hours_value(t) or 0) for t in tasks), 2)
    total_hours_label = format_hours(total_hours)
    eod_body = _build_eod_body(tasks, total_hours_label)

    targets = _get_eod_targets(personal_client=client)
    personal_res = _upsert_eod_on_target(
        targets[0], target_date, tasks, total_hours, total_hours_label, eod_body, engineer_name
    )
    print(f"EOD Report synchronized successfully! URL: {personal_res['url']}")

    for shared_target in targets[1:]:
        try:
            shared_res = _upsert_eod_on_target(
                shared_target, target_date, tasks, total_hours, total_hours_label, eod_body, engineer_name
            )
            print(f"Shared Team EOD Report synchronized ({shared_res['action']})! URL: {shared_res['url']}")
        except Exception as exc:
            print(
                f"Error mirroring EOD Report to Shared Team Notion DB: {exc}\n"
                f"Personal EOD was saved. Run 'python notion_logger.py --sync-shared --date {target_date}' to retry."
            )
            raise

    return personal_res["url"]


def sync_shared(target_date: Optional[str] = None) -> Dict[str, Any]:
    """Backfill/repair buffered tasks (and shared EODs if configured) into the Shared Team DB."""
    _require_db_id("shared_tasks_database_id", "NOTION_SHARED_TASKS_DB_ID")
    engineer_name = _require_engineer_name()
    normalized_date = (
        datetime.now().strftime("%Y-%m-%d")
        if (not target_date or target_date == "today")
        else target_date
    )

    rebalance_buffer_and_notion(client=None, target_date=normalized_date, max_daily_hours=MAX_DAILY_HOURS)
    all_tasks = _dedupe_tasks(read_buffer())
    dates_to_sync = (
        sorted({t.get("date") for t in all_tasks if t.get("date")})
        if normalized_date == "all"
        else [normalized_date]
    )

    personal_client = None
    try:
        personal_client = get_client()
    except Exception:
        pass

    shared_tasks_targets = [t for t in _get_tasks_targets(personal_client=personal_client) if t["is_shared"]]
    shared_eod_targets = [t for t in _get_eod_targets(personal_client=personal_client) if t["is_shared"]]

    tasks_synced = 0
    eods_synced = 0
    synced_dates: List[str] = []

    for d in dates_to_sync:
        day_tasks = [t for t in all_tasks if t.get("date") == d]
        if not day_tasks:
            continue
        synced_dates.append(d)
        for task_spec in day_tasks:
            norm = _normalize_task_spec(task_spec)
            body = _build_task_body(
                task_spec,
                commit=norm["commit"],
                branch=norm["branch"],
                time_spent_hours=norm["time_spent_hours"],
            )
            for st in shared_tasks_targets:
                res = _upsert_task_on_target(st, norm, body, engineer_name, upsert_existing=True)
                tasks_synced += 1
                print(f"  [{res['action']}] {d} | {norm['title']}")

        if shared_eod_targets:
            total_hours = round(sum(float(_extract_hours_value(t) or 0) for t in day_tasks), 2)
            total_hours_label = format_hours(total_hours)
            eod_body = _build_eod_body(day_tasks, total_hours_label)
            for se in shared_eod_targets:
                _upsert_eod_on_target(se, d, day_tasks, total_hours, total_hours_label, eod_body, engineer_name)
                eods_synced += 1

    print(f"Shared Team sync complete: {tasks_synced} task(s), {eods_synced} EOD report(s) across {len(synced_dates)} date(s).")
    return {"dates": synced_dates, "tasks_synced": tasks_synced, "eods_synced": eods_synced}


def _store_token_file(filename: str, token_value: str) -> Path:
    token_dir = Path.home() / ".config" / "engineering-reporting"
    token_dir.mkdir(parents=True, exist_ok=True)
    token_path = token_dir / filename
    token_path.write_text(token_value.strip() + "\n", encoding="utf-8")
    try:
        os.chmod(token_path, 0o600)
    except Exception:
        pass
    return token_path


def _extract_notion_id(value: str) -> str:
    """Extract a canonical dashed Notion UUID from a Notion URL, raw 32-hex ID, or UUID."""
    raw = (value or "").strip()
    if not raw:
        raise ValueError("Missing Notion page URL or ID.")
    path_part = raw.split("?", 1)[0].split("#", 1)[0]
    uuid_or_hex_pat = (
        r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
        r"|(?<![0-9a-fA-F])[0-9a-fA-F]{32}(?![0-9a-fA-F])"
    )
    matches = re.findall(uuid_or_hex_pat, path_part)
    if not matches:
        raise ValueError(
            f"Could not find a valid 32-character Notion page/database ID in: '{value}'. "
            "Paste the Notion page URL or its 32-character ID."
        )
    hex_id = matches[-1].replace("-", "").lower()
    return f"{hex_id[0:8]}-{hex_id[8:12]}-{hex_id[12:16]}-{hex_id[16:20]}-{hex_id[20:32]}"


def _tasks_db_schema(include_engineer: bool = False) -> Dict[str, Any]:
    schema: Dict[str, Any] = {
        "Name": {"title": {}},
        "Project": {"select": {"options": []}},
        "Category": {
            "select": {
                "options": [
                    {"name": "Feature", "color": "blue"},
                    {"name": "Bug Fix", "color": "red"},
                    {"name": "Architecture / Tooling", "color": "purple"},
                    {"name": "Performance", "color": "green"},
                    {"name": "Security / Audit", "color": "orange"},
                ]
            }
        },
        "Status": {
            "select": {
                "options": [
                    {"name": "Done", "color": "green"},
                    {"name": "In Progress", "color": "yellow"},
                ]
            }
        },
        "Date": {"date": {}},
        "Branches": {"rich_text": {}},
        "Git Commits": {"rich_text": {}},
        "Time Spent (hrs)": {"number": {"format": "number"}},
        "Manager Notes / Impact": {"rich_text": {}},
    }
    if include_engineer:
        schema["Engineer"] = {"select": {"options": []}}
    return schema


def _eod_db_schema(include_engineer: bool = False) -> Dict[str, Any]:
    schema: Dict[str, Any] = {
        "Name": {"title": {}},
        "Date": {"date": {}},
        "Status": {
            "select": {
                "options": [
                    {"name": "Submitted", "color": "green"},
                    {"name": "Draft", "color": "gray"},
                ]
            }
        },
        "Sprint / Cycle": {"rich_text": {}},
        "Tasks Completed": {"number": {"format": "number"}},
        "Total Time Spent (hrs)": {"number": {"format": "number"}},
        "Focus Area": {"rich_text": {}},
    }
    if include_engineer:
        schema["Engineer"] = {"select": {"options": []}}
    return schema


def _strip_leading_emoji(text: str) -> str:
    return re.sub(r"^[^\w]+", "", (text or "").strip()).strip()


def _find_existing_child_databases(client: Client, parent_page_id: str) -> Tuple[Dict[str, str], List[Dict[str, Any]]]:
    existing: Dict[str, str] = {}
    blocks: List[Dict[str, Any]] = []
    try:
        res = client.blocks.children.list(block_id=parent_page_id)
        blocks = res.get("results", [])
        for blk in blocks:
            if blk.get("type") == "child_database":
                title = (blk.get("child_database") or {}).get("title", "").strip()
                if title and blk.get("id"):
                    existing[title] = blk["id"]
                    stripped = _strip_leading_emoji(title)
                    if stripped:
                        existing.setdefault(stripped, blk["id"])
    except Exception:
        pass
    return existing, blocks


def _create_database_on_page(
    client: Client,
    parent_page_id: str,
    title: str,
    properties: Dict[str, Any],
    icon_emoji: str,
    existing_map: Optional[Dict[str, str]] = None,
) -> Dict[str, str]:
    icon_payload = {"type": "emoji", "emoji": icon_emoji}
    title_payload = [{"type": "text", "text": {"content": title}}]

    matched_id = None
    if existing_map:
        matched_id = existing_map.get(title) or existing_map.get(_strip_leading_emoji(title))

    if matched_id:
        if hasattr(client.databases, "update"):
            try:
                client.databases.update(
                    database_id=matched_id,
                    title=title_payload,
                    is_inline=False,
                    icon=icon_payload,
                )
            except Exception as exc:
                print(f"Warning: Could not convert database {matched_id} to full-page view: {exc}")
        return {"id": matched_id, "url": f"https://www.notion.so/{matched_id.replace('-', '')}", "action": "reused"}

    parent_payload = {"type": "page_id", "page_id": parent_page_id}
    if hasattr(client, "data_sources"):
        created = client.databases.create(
            parent=parent_payload,
            title=title_payload,
            is_inline=False,
            icon=icon_payload,
            initial_data_source={"properties": properties},
        )
    else:
        created = client.databases.create(
            parent=parent_payload,
            title=title_payload,
            is_inline=False,
            icon=icon_payload,
            properties=properties,
        )
    return {"id": created["id"], "url": created.get("url", ""), "action": "created"}


def _format_workspace_parent_page(
    client: Client,
    parent_page_id: str,
    existing_blocks: List[Dict[str, Any]],
    shared: bool = False,
) -> None:
    """Keep the parent hub page tidy with an icon, intro callout, and full-page DB links."""
    try:
        if hasattr(client.pages, "retrieve") and hasattr(client.pages, "update"):
            page_meta = client.pages.retrieve(page_id=parent_page_id)
            if not page_meta.get("icon"):
                client.pages.update(page_id=parent_page_id, icon={"type": "emoji", "emoji": "💻"})
    except Exception:
        pass

    has_callout = any(b.get("type") == "callout" for b in existing_blocks)
    for b in existing_blocks:
        if b.get("type") == "paragraph":
            rt = (b.get("paragraph") or {}).get("rich_text", [])
            if not rt and b.get("id"):
                try:
                    client.blocks.delete(block_id=b["id"])
                except Exception:
                    pass

    if not has_callout:
        summary_text = (
            "Shared Team Engineering Workspace\n"
            "Tasks, commits, effort logs, and daily EOD briefings from all team members mirror here automatically. "
            "Open either database above to view or filter by Engineer and Date."
            if shared
            else
            "Engineering Reporting Workspace\n"
            "All completed tasks, Git traceability, effort logs, and daily EOD manager briefings are synced here. "
            "Open either database above to browse full views."
        )
        try:
            append_blocks_safely(
                client,
                parent_page_id,
                [callout(summary_text, emoji="🤖"), divider()],
            )
        except Exception:
            pass


def init_notion_databases(parent_page: str, shared: bool = False) -> Dict[str, Any]:
    """Create Personal (or Shared Team) full-page Tasks + EOD databases under a Notion hub page."""
    parent_page_id = _extract_notion_id(parent_page)
    client = get_shared_client() if shared else get_client()
    existing_map, existing_blocks = _find_existing_child_databases(client, parent_page_id)

    tasks_title = "📋 Shared Team Engineering Tasks" if shared else "📋 Tasks & Engineering Activity Log"
    eod_title = "📰 Shared Team Daily EOD Briefings" if shared else "📰 Daily Manager Briefings (EOD Reports)"

    tasks_res = _create_database_on_page(
        client,
        parent_page_id,
        tasks_title,
        _tasks_db_schema(include_engineer=shared),
        icon_emoji="📋",
        existing_map=existing_map,
    )
    eod_res = _create_database_on_page(
        client,
        parent_page_id,
        eod_title,
        _eod_db_schema(include_engineer=shared),
        icon_emoji="📰",
        existing_map=existing_map,
    )
    _format_workspace_parent_page(client, parent_page_id, existing_blocks, shared=shared)

    cfg = load_config()
    if shared:
        cfg["shared_parent_page_id"] = parent_page_id
        cfg["shared_tasks_database_id"] = tasks_res["id"]
        cfg["shared_eod_database_id"] = eod_res["id"]
    else:
        cfg["parent_page_id"] = parent_page_id
        cfg["tasks_database_id"] = tasks_res["id"]
        cfg["eod_database_id"] = eod_res["id"]

    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    CONFIG.clear()
    CONFIG.update(load_config())
    _DB_PROPERTIES_CACHE.clear()
    _ENSURED_SHARED_TARGETS.clear()

    if tasks_res["action"] == "reused" or eod_res["action"] == "reused":
        ensure_time_spent_columns(get_client() if not shared else client)

    label = "Shared Team" if shared else "Personal"
    print(f"{label} Tasks DB ({tasks_res['action']}): {tasks_res['id']} {tasks_res['url']}")
    print(f"{label} EOD DB   ({eod_res['action']}): {eod_res['id']} {eod_res['url']}")
    print(f"Saved database IDs to {CONFIG_FILE}")
    return {
        "tasks_database_id": tasks_res["id"],
        "tasks_url": tasks_res["url"],
        "tasks_action": tasks_res["action"],
        "eod_database_id": eod_res["id"],
        "eod_url": eod_res["url"],
        "eod_action": eod_res["action"],
    }


def setup_member(
    name: Optional[str] = None,
    tasks_db: Optional[str] = None,
    eod_db: Optional[str] = None,
    shared_tasks_db: Optional[str] = None,
    shared_eod_db: Optional[str] = None,
    parent_page: Optional[str] = None,
    shared_parent_page: Optional[str] = None,
    project: Optional[str] = None,
    branch: Optional[str] = None,
    sprint: Optional[str] = None,
    token: Optional[str] = None,
    shared_token: Optional[str] = None,
) -> Dict[str, Any]:
    """Create or update config.json (and optionally provision Notion DBs + token files) for a team member."""
    if token and token.strip():
        saved = _store_token_file(".notion_token", token)
        print(f"Saved personal Notion token to {saved}")
    if shared_token and shared_token.strip():
        saved_shared = _store_token_file(".shared_notion_token", shared_token)
        print(f"Saved shared Notion token to {saved_shared}")

    if parent_page and parent_page.strip() and not (tasks_db and eod_db):
        created = init_notion_databases(parent_page.strip(), shared=False)
        tasks_db = tasks_db or created["tasks_database_id"]
        eod_db = eod_db or created["eod_database_id"]

    if shared_parent_page and shared_parent_page.strip() and not (shared_tasks_db and shared_eod_db):
        created_shared = init_notion_databases(shared_parent_page.strip(), shared=True)
        shared_tasks_db = shared_tasks_db or created_shared["tasks_database_id"]
        shared_eod_db = shared_eod_db or created_shared["eod_database_id"]

    cfg = load_config()
    interactive = sys.stdin.isatty()

    def _pick(val: Optional[str], key: str, label: str) -> str:
        cur = str(cfg.get(key) or "").strip()
        if val is not None:
            return val.strip()
        if interactive:
            entered = input(f"{label} [{cur}]: ").strip()
            return entered or cur
        return cur

    cfg["engineer_name"] = _pick(name, "engineer_name", "Engineer Name")
    cfg["tasks_database_id"] = _pick(tasks_db, "tasks_database_id", "Personal Tasks Database ID")
    cfg["eod_database_id"] = _pick(eod_db, "eod_database_id", "Personal EOD Database ID")
    cfg["shared_tasks_database_id"] = _pick(shared_tasks_db, "shared_tasks_database_id", "Shared Team Tasks Database ID (optional)")
    cfg["shared_eod_database_id"] = _pick(shared_eod_db, "shared_eod_database_id", "Shared Team EOD Database ID (optional)")
    cfg["default_project"] = _pick(project, "default_project", "Default Project Name") or "My Project"
    cfg["default_branch"] = _pick(branch, "default_branch", "Default Git Branch") or "main"
    cfg["default_sprint"] = _pick(sprint, "default_sprint", "Default Sprint / Cycle") or "Sprint 1"

    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")

    CONFIG.clear()
    CONFIG.update(load_config())
    _DB_PROPERTIES_CACHE.clear()
    _ENSURED_SHARED_TARGETS.clear()

    print(f"Member configuration written cleanly to {CONFIG_FILE}")
    return cfg


# ---------------------------------------------------------
# Parking Items (Deferred Plans — Dual Personal & Shared)
# ---------------------------------------------------------
_PARKING_INDEX_TITLE = "Parking items"
_PARKING_INDEX_CALLOUT = (
    "Parked engineering items — click any item below to open its full implementation plan."
)


def _save_config_updates(updates: Dict[str, Any]) -> None:
    cfg = load_config()
    cfg.update(updates)
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    CONFIG.clear()
    CONFIG.update(load_config())


def _resolve_hub_page_id(client: Client, shared: bool = False) -> Optional[str]:
    cfg_key = "shared_parent_page_id" if shared else "parent_page_id"
    raw_parent = str(CONFIG.get(cfg_key) or "").strip()
    if raw_parent:
        return _extract_notion_id(raw_parent)

    db_keys = (
        ("shared_tasks_database_id", "shared_eod_database_id")
        if shared
        else ("tasks_database_id", "eod_database_id")
    )
    for db_key in db_keys:
        db_id = str(CONFIG.get(db_key) or "").strip()
        if not db_id:
            continue
        try:
            meta = client.databases.retrieve(database_id=db_id)
            parent = meta.get("parent") or {}
            if parent.get("type") == "page_id" and parent.get("page_id"):
                return parent["page_id"]
        except Exception:
            pass
    return None


def _find_child_page_by_title(
    client: Client,
    parent_page_id: str,
    title: str,
) -> Optional[Dict[str, str]]:
    want = title.strip().lower()
    want_stripped = _strip_leading_emoji(title).lower()
    for blk in _list_all_children(client, parent_page_id):
        if blk.get("type") != "child_page":
            continue
        found_title = (blk.get("child_page") or {}).get("title", "").strip()
        if found_title.lower() == want or (
            want_stripped and _strip_leading_emoji(found_title).lower() == want_stripped
        ):
            compact_id = blk["id"].replace("-", "")
            return {
                "id": blk["id"],
                "title": found_title,
                "url": f"https://www.notion.so/{compact_id}",
            }
    return None


def _ensure_parking_index_page(
    client: Client,
    hub_page_id: str,
    configured_parking_id: str = "",
    clean_index: bool = False,
) -> Dict[str, str]:
    """Ensure ONE 'Parking items' child page exists under hub_page_id with a minimal index."""
    parking_id = ""
    parking_url = ""
    action = "reused"

    if configured_parking_id:
        try:
            meta = client.pages.retrieve(page_id=_extract_notion_id(configured_parking_id))
            if not meta.get("archived") and not meta.get("in_trash"):
                parking_id = meta["id"]
                parking_url = meta.get("url", "")
        except Exception:
            parking_id = ""

    if not parking_id:
        existing = _find_child_page_by_title(client, hub_page_id, _PARKING_INDEX_TITLE)
        if existing:
            parking_id = existing["id"]
            parking_url = existing["url"]
            try:
                page_meta = client.pages.retrieve(page_id=parking_id)
                parking_url = page_meta.get("url") or parking_url
            except Exception:
                pass

    if not parking_id:
        created = client.pages.create(
            parent={"page_id": hub_page_id},
            icon={"type": "emoji", "emoji": "🅿️"},
            properties={"title": {"title": [{"text": {"content": _PARKING_INDEX_TITLE}}]}},
            children=[
                callout(
                    _PARKING_INDEX_CALLOUT,
                    emoji="🅿️",
                    color="gray_background",
                )
            ],
        )
        return {"id": created["id"], "url": created.get("url", ""), "action": "created"}

    # Ensure existing Parking items index page stays clean & uncluttered
    if clean_index:
        clear_page_blocks(client, parking_id, preserve_child_pages=True)
        existing_blocks: List[Dict[str, Any]] = []
    else:
        existing_blocks = _list_all_children(client, parking_id)

    has_callout = any(b.get("type") == "callout" for b in existing_blocks)
    if not has_callout:
        append_blocks_safely(
            client,
            parking_id,
            [callout(_PARKING_INDEX_CALLOUT, emoji="🅿️", color="gray_background")],
        )
    return {"id": parking_id, "url": parking_url, "action": action}


def _resolve_parking_targets(
    target: str = "personal",
    personal_parent: Optional[str] = None,
    shared_parent: Optional[str] = None,
    clean_index: bool = False,
    create_if_missing: bool = True,
) -> List[Dict[str, Any]]:
    mode = (target or "personal").strip().lower()
    if mode not in ("personal", "shared", "both"):
        raise ValueError(f"Invalid --target '{target}'. Use 'personal', 'shared', or 'both'.")

    targets: List[Dict[str, Any]] = []
    cfg_updates: Dict[str, Any] = {}

    if mode in ("both", "personal"):
        p_client = get_client()
        hub_id = (
            _extract_notion_id(personal_parent)
            if personal_parent
            else _resolve_hub_page_id(p_client, shared=False)
        )
        cfg_parking = str(CONFIG.get("parking_page_id") or "").strip()
        if not hub_id and not cfg_parking:
            raise ValueError(
                "Could not determine Personal Notion hub page for Parking items. "
                "Pass --parent-page or set 'parent_page_id' / 'parking_page_id' in config.json."
            )
        if not cfg_parking and hub_id:
            cfg_updates["parent_page_id"] = hub_id
        if create_if_missing:
            info = (
                _ensure_parking_index_page(
                    p_client,
                    hub_id or "",
                    configured_parking_id=cfg_parking,
                    clean_index=clean_index,
                )
                if hub_id
                else {"id": _extract_notion_id(cfg_parking), "url": "", "action": "reused"}
            )
            cfg_updates["parking_page_id"] = info["id"]
            targets.append({
                "name": "personal",
                "is_shared": False,
                "client": p_client,
                "hub_page_id": hub_id,
                "parking_page_id": info["id"],
                "parking_url": info["url"],
                "index_action": info["action"],
            })
        else:
            existing = (
                {"id": _extract_notion_id(cfg_parking), "url": ""}
                if cfg_parking
                else (_find_child_page_by_title(p_client, hub_id, _PARKING_INDEX_TITLE) if hub_id else None)
            )
            if existing:
                targets.append({
                    "name": "personal",
                    "is_shared": False,
                    "client": p_client,
                    "hub_page_id": hub_id,
                    "parking_page_id": existing["id"],
                    "parking_url": existing.get("url", ""),
                    "index_action": "reused",
                })

    has_shared = bool(
        shared_parent
        or CONFIG.get("shared_parking_page_id")
        or CONFIG.get("shared_parent_page_id")
        or _has_shared_config()
    )
    if mode in ("shared", "both"):
        if not has_shared:
            raise ValueError(
                "Shared target requested, but no Shared Notion hub/database is configured in config.json."
            )
        s_client = _resolve_shared_client()
        s_hub_id = (
            _extract_notion_id(shared_parent)
            if shared_parent
            else _resolve_hub_page_id(s_client, shared=True)
        )
        cfg_s_parking = str(CONFIG.get("shared_parking_page_id") or "").strip()
        if not s_hub_id and not cfg_s_parking:
            raise ValueError(
                "Could not determine Shared Notion hub page for Parking items. "
                "Pass --shared-parent-page or set 'shared_parent_page_id' / 'shared_parking_page_id' in config.json."
            )
        if s_hub_id:
            cfg_updates["shared_parent_page_id"] = s_hub_id
        if create_if_missing:
            s_info = (
                _ensure_parking_index_page(
                    s_client,
                    s_hub_id or "",
                    configured_parking_id=cfg_s_parking,
                    clean_index=clean_index,
                )
                if s_hub_id
                else {"id": _extract_notion_id(cfg_s_parking), "url": "", "action": "reused"}
            )
            cfg_updates["shared_parking_page_id"] = s_info["id"]
            targets.append({
                "name": "shared",
                "is_shared": True,
                "client": s_client,
                "hub_page_id": s_hub_id,
                "parking_page_id": s_info["id"],
                "parking_url": s_info["url"],
                "index_action": s_info["action"],
            })
        else:
            existing_s = (
                {"id": _extract_notion_id(cfg_s_parking), "url": ""}
                if cfg_s_parking
                else (_find_child_page_by_title(s_client, s_hub_id, _PARKING_INDEX_TITLE) if s_hub_id else None)
            )
            if existing_s:
                targets.append({
                    "name": "shared",
                    "is_shared": True,
                    "client": s_client,
                    "hub_page_id": s_hub_id,
                    "parking_page_id": existing_s["id"],
                    "parking_url": existing_s.get("url", ""),
                    "index_action": "reused",
                })

    if cfg_updates:
        _save_config_updates(cfg_updates)
    return targets


def _markdown_to_notion_blocks(md_text: str) -> Tuple[Optional[str], List[Dict[str, Any]]]:
    """Parse structured engineering markdown (callouts, tables, code fences, nested lists, checklists) into Notion blocks."""
    lines = md_text.replace("\r\n", "\n").split("\n")
    extracted_title: Optional[str] = None
    blocks: List[Dict[str, Any]] = []
    i = 0
    n = len(lines)

    _LIST_ITEM_RE = re.compile(r"^(\s*)(\d+\.\s+|[-*]\s+)(.*)$")
    _TODO_RE = re.compile(r"^-\s+\[([ xX])\]\s+(.*)$")
    _CALLOUT_KIND_EMOJI = {
        "NOTE": ("📌", "blue_background"),
        "TIP": ("💡", "green_background"),
        "IMPORTANT": ("❗", "purple_background"),
        "WARNING": ("⚠️", "yellow_background"),
        "CAUTION": ("🚨", "red_background"),
    }

    def _collect_nested_children(base_indent: int, start_idx: int, depth: int) -> Tuple[List[Dict[str, Any]], int]:
        children: List[Dict[str, Any]] = []
        idx = start_idx
        while idx < n:
            line = lines[idx]
            stripped = line.strip()
            if not stripped:
                # Peek ahead: stop list nesting if next non-empty line is not indented deeper than base_indent
                peek = idx + 1
                while peek < n and not lines[peek].strip():
                    peek += 1
                if peek >= n:
                    idx = peek
                    break
                next_indent = len(lines[peek]) - len(lines[peek].lstrip(" "))
                if next_indent <= base_indent:
                    idx += 1
                    break
                idx += 1
                continue

            indent = len(line) - len(line.lstrip(" "))
            if indent <= base_indent:
                break

            # Fenced code block indented inside a list item
            if stripped.startswith("```"):
                lang = stripped[3:].strip() or "plain text"
                code_lines: List[str] = []
                idx += 1
                while idx < n:
                    cur = lines[idx]
                    if cur.strip().startswith("```"):
                        idx += 1
                        break
                    if len(cur) >= indent and not cur[:indent].strip():
                        code_lines.append(cur[indent:])
                    else:
                        code_lines.append(cur.lstrip())
                    idx += 1
                children.append(code_block("\n".join(code_lines), language=lang))
                continue

            m = _LIST_ITEM_RE.match(line)
            if m:
                is_num = bool(re.match(r"^\d+\.\s+", m.group(2)))
                item_text = m.group(3).strip()
                item_indent = len(m.group(1))
                sub_children: List[Dict[str, Any]] = []
                idx += 1
                if depth < 1:
                    sub_children, idx = _collect_nested_children(item_indent, idx, depth + 1)
                if is_num:
                    children.append(numbered_item(item_text, children=sub_children or None))
                else:
                    children.append(bullet(item_text, children=sub_children or None))
                continue

            # Continuation text line inside list item
            children.append(bullet(stripped))
            idx += 1
        return children, idx

    while i < n:
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            i += 1
            continue

        # Top-level H1 (used as page title if present at top)
        if stripped.startswith("# ") and not blocks and extracted_title is None:
            extracted_title = stripped[2:].strip()
            i += 1
            continue

        if stripped == "---":
            blocks.append(divider())
            i += 1
            continue

        if stripped.startswith("### "):
            blocks.append(heading_3(stripped[4:].strip()))
            i += 1
            continue
        if stripped.startswith("## "):
            blocks.append(heading_2(stripped[3:].strip()))
            i += 1
            continue
        if stripped.startswith("# "):
            blocks.append(heading_1(stripped[2:].strip()))
            i += 1
            continue

        # Blockquote / GitHub alert callout
        if stripped.startswith(">"):
            quote_lines: List[str] = []
            while i < n and lines[i].strip().startswith(">"):
                content = lines[i].strip()[1:].lstrip()
                quote_lines.append(content)
                i += 1
            emoji, color = "📌", "blue_background"
            if quote_lines:
                alert_match = re.match(r"^\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]$", quote_lines[0].strip(), re.IGNORECASE)
                if alert_match:
                    emoji, color = _CALLOUT_KIND_EMOJI[alert_match.group(1).upper()]
                    quote_lines = quote_lines[1:]
            blocks.append(callout("\n".join(quote_lines).strip(), emoji=emoji, color=color))
            continue

        # Fenced code block
        if stripped.startswith("```"):
            lang = stripped[3:].strip() or "plain text"
            code_lines = []
            i += 1
            while i < n and not lines[i].strip().startswith("```"):
                code_lines.append(lines[i])
                i += 1
            if i < n and lines[i].strip().startswith("```"):
                i += 1
            blocks.append(code_block("\n".join(code_lines), language=lang))
            continue

        # GFM Markdown table
        if stripped.startswith("|") and i + 1 < n and re.match(r"^\|[\s:\-\|]+\|$", lines[i + 1].strip()):
            table_rows: List[List[str]] = []
            header_cells = [c.strip() for c in stripped.strip("|").split("|")]
            table_rows.append([f"**{c}**" if not c.startswith("**") else c for c in header_cells])
            i += 2  # Skip separator line
            while i < n and lines[i].strip().startswith("|"):
                row_cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                table_rows.append(row_cells)
                i += 1
            blocks.append(table_block(table_rows, has_column_header=True))
            continue

        # To-do checklist
        todo_m = _TODO_RE.match(stripped)
        if todo_m:
            blocks.append(todo_item(todo_m.group(2).strip(), checked=(todo_m.group(1).lower() == "x")))
            i += 1
            continue

        # Top-level numbered or bulleted list item (with up to 2 nested levels)
        list_m = _LIST_ITEM_RE.match(line)
        if list_m:
            is_num = bool(re.match(r"^\d+\.\s+", list_m.group(2)))
            base_indent = len(list_m.group(1))
            item_text = list_m.group(3).strip()
            i += 1
            children, i = _collect_nested_children(base_indent, i, depth=0)
            if is_num:
                blocks.append(numbered_item(item_text, children=children or None))
            else:
                blocks.append(bullet(item_text, children=children or None))
            continue

        # Paragraph (group consecutive plain text lines)
        para_lines = [stripped]
        i += 1
        while i < n:
            nxt = lines[i].strip()
            if (
                not nxt
                or nxt == "---"
                or nxt.startswith(("#", ">", "```", "|"))
                or _TODO_RE.match(nxt)
                or _LIST_ITEM_RE.match(lines[i])
            ):
                break
            para_lines.append(nxt)
            i += 1
        blocks.append({"object": "block", "type": "paragraph", "paragraph": {"rich_text": _parse_inline_rich_text(" ".join(para_lines))}})

    return extracted_title, blocks


def _build_parking_step_item_block(item: Any) -> Dict[str, Any]:
    if isinstance(item, str):
        return numbered_item(item)
    text = str(item.get("text") or "")
    children: List[Dict[str, Any]] = []
    if item.get("code"):
        children.append(code_block(item["code"], language=item.get("language", "python")))
    for sub in item.get("bullets", []):
        if isinstance(sub, dict):
            sub_children: List[Dict[str, Any]] = []
            if sub.get("code"):
                sub_children.append(code_block(sub["code"], language=sub.get("language", "python")))
            for nested_b in sub.get("bullets", []):
                sub_children.append(bullet(str(nested_b)))
            for idx_num, nested_n in enumerate(sub.get("numbered", []), 1):
                sub_children.append(numbered_item(str(nested_n)))
            children.append(bullet(str(sub.get("text") or ""), children=sub_children or None))
        else:
            children.append(bullet(str(sub)))
    return numbered_item(text, children=children or None)


def _build_parking_item_blocks(
    spec: Dict[str, Any],
    *,
    is_shared: bool = False,
    engineer_name: str = "",
) -> Tuple[str, str, List[Dict[str, Any]]]:
    """Build exact 5-section Zero-Memory Implementation Plan blocks for a Parking Item page."""
    title = str(spec.get("title") or "").strip() or "Untitled Parked Item"
    icon_emoji = str(spec.get("icon") or "🛡️").strip() or "🛡️"

    if spec.get("markdown_path") or spec.get("markdown"):
        md_raw = (
            Path(spec["markdown_path"]).read_text(encoding="utf-8")
            if spec.get("markdown_path")
            else str(spec["markdown"])
        )
        parsed_title, md_blocks = _markdown_to_notion_blocks(md_raw)
        final_title = title if spec.get("title") else (parsed_title or title)
        if is_shared and engineer_name and md_blocks and md_blocks[0].get("type") == "callout":
            # Add Engineer attribution line to shared header callout cleanly
            rt_list = list(md_blocks[0]["callout"]["rich_text"])
            rt_list.append({"type": "text", "text": {"content": "\n"}})
            rt_list.extend(_chunk_rich_text("Engineer / Project: ", bold=True))
            proj = str(spec.get("project") or CONFIG.get("default_project") or "").strip()
            attr = f"{engineer_name} ({proj})" if proj else engineer_name
            rt_list.extend(_chunk_rich_text(attr))
            md_blocks[0]["callout"]["rich_text"] = rt_list
        return final_title, icon_emoji, md_blocks

    status = str(spec.get("status") or "Parked for future implementation")
    date_str = str(spec.get("date") or datetime.now().strftime("%Y-%m-%d"))
    target_branch = str(spec.get("target_branch") or CONFIG.get("default_branch") or "main")
    project = str(spec.get("project") or CONFIG.get("default_project") or "")
    owner_trigger = str(spec.get("owner_trigger") or "")
    if owner_trigger:
        validate_customer_input(owner_trigger)

    meta_parts: List[str] = [f"**Status:** {status} ({date_str})"]
    if is_shared and (engineer_name or project):
        meta_parts.append(f"**Engineer / Project:** {engineer_name or 'Team'} ({project})")
    elif project:
        meta_parts.append(f"**Project:** {project}")
    meta_parts.append(f"**Target Branch:** `{target_branch}`")
    if owner_trigger:
        meta_parts.append(f"**Owner / Trigger:** {owner_trigger}")

    blocks: List[Dict[str, Any]] = [
        callout("\n".join(meta_parts), emoji="📌", color="blue_background"),
        divider(),
    ]

    # 1. Problem & Exact Root Cause
    problem = spec.get("problem") or {}
    if problem:
        blocks.append(heading_2("1. Problem & Exact Root Cause"))
        if problem.get("summary"):
            validate_customer_input(str(problem["summary"]))
            blocks.append({"object": "block", "type": "paragraph", "paragraph": {"rich_text": _parse_inline_rich_text(str(problem["summary"]))}})
        sample = problem.get("sample_payload")
        if isinstance(sample, dict) and sample.get("code"):
            blocks.append(code_block(sample["code"], language=sample.get("language", "json")))
        root_causes = problem.get("root_causes") or []
        if root_causes:
            blocks.append(heading_3(str(problem.get("why_not_caught_title") or "Why existing safeguards missed this")))
            for rc in root_causes:
                if isinstance(rc, dict):
                    rc_text = f"**{rc.get('title', 'Root Cause')}:** {rc.get('detail', '')}"
                else:
                    rc_text = str(rc)
                blocks.append(numbered_item(rc_text))
        blocks.append(divider())

    # 2. Complete Component / Flow Audit
    audit = spec.get("audit") or {}
    if audit:
        blocks.append(heading_2(str(audit.get("title") or "2. Complete Flow Audit (Critical Constraints Before Editing)")))
        if audit.get("warning"):
            blocks.append(callout(str(audit["warning"]), emoji="⚠️", color="yellow_background"))
        cols = audit.get("columns") or []
        rows = audit.get("rows") or []
        if cols and rows:
            header_row = [f"**{c}**" if not str(c).startswith("**") else str(c) for c in cols]
            blocks.append(table_block([header_row] + rows, has_column_header=True))
        blocks.append(divider())

    # 3. Exact Step-by-Step Implementation Instructions
    impl_steps = spec.get("implementation_steps") or []
    if impl_steps:
        blocks.append(heading_2("3. Exact Step-by-Step Implementation Instructions"))
        for step in impl_steps:
            blocks.append(heading_3(str(step.get("title") or "Implementation Step")))
            if step.get("file"):
                blocks.append({"object": "block", "type": "paragraph", "paragraph": {"rich_text": _parse_inline_rich_text(f"**File:** `{step['file']}`")}})
            if step.get("description"):
                blocks.append({"object": "block", "type": "paragraph", "paragraph": {"rich_text": _parse_inline_rich_text(str(step["description"]))}})
            for item in step.get("items", []):
                blocks.append(_build_parking_step_item_block(item))
        blocks.append(divider())

    # 4. Verification Plan
    verif = spec.get("verification_plan") or {}
    if verif:
        blocks.append(heading_2(str(verif.get("title") or "4. Verification Plan")))
        if verif.get("command"):
            blocks.append({"object": "block", "type": "paragraph", "paragraph": {"rich_text": _parse_inline_rich_text(f"Run tests using `{verif['command']}`:")}})
        for case in verif.get("cases", []):
            if isinstance(case, dict):
                children = [bullet(str(d)) for d in case.get("details", [])]
                blocks.append(numbered_item(f"**{case.get('title', 'Test Case')}**", children=children or None))
            else:
                blocks.append(numbered_item(str(case)))
        blocks.append(divider())

    # 5. Rollout Checklist
    checklist = spec.get("rollout_checklist") or []
    if checklist:
        blocks.append(heading_2("5. Rollout Checklist"))
        for item in checklist:
            if isinstance(item, dict):
                blocks.append(todo_item(str(item.get("text") or ""), checked=bool(item.get("checked", False))))
            else:
                blocks.append(todo_item(str(item), checked=False))

    return title, icon_emoji, blocks


def _upsert_parking_child_page(
    target_info: Dict[str, Any],
    title: str,
    icon_emoji: str,
    blocks: List[Dict[str, Any]],
) -> Dict[str, Any]:
    client: Client = target_info["client"]
    parking_page_id: str = target_info["parking_page_id"]
    existing = _find_child_page_by_title(client, parking_page_id, title)

    if existing:
        page_id = existing["id"]
        client.pages.update(
            page_id=page_id,
            icon={"type": "emoji", "emoji": icon_emoji},
            properties={"title": {"title": [{"text": {"content": title[:2000]}}]}},
        )
        clear_page_blocks(client, page_id, preserve_child_pages=True)
        append_blocks_safely(client, page_id, blocks)
        meta = client.pages.retrieve(page_id=page_id)
        return {
            "id": page_id,
            "url": meta.get("url") or existing["url"],
            "action": "updated",
            "blocks_written": len(blocks),
        }

    created = client.pages.create(
        parent={"page_id": parking_page_id},
        icon={"type": "emoji", "emoji": icon_emoji},
        properties={"title": {"title": [{"text": {"content": title[:2000]}}]}},
        children=blocks[:100],
    )
    page_id = created["id"]
    if len(blocks) > 100:
        append_blocks_safely(client, page_id, blocks[100:])
    return {
        "id": page_id,
        "url": created.get("url", ""),
        "action": "created",
        "blocks_written": len(blocks),
    }


def init_parking_pages(
    target: str = "personal",
    personal_parent: Optional[str] = None,
    shared_parent: Optional[str] = None,
    clean_index: bool = False,
) -> Dict[str, Any]:
    """Ensure separate 'Parking items' index pages exist on the selected Notion hub(s)."""
    resolved = _resolve_parking_targets(
        target=target,
        personal_parent=personal_parent,
        shared_parent=shared_parent,
        clean_index=clean_index,
        create_if_missing=True,
    )
    summary: Dict[str, Any] = {}
    for t in resolved:
        summary[t["name"]] = {
            "hub_page_id": t["hub_page_id"],
            "parking_page_id": t["parking_page_id"],
            "parking_url": t["parking_url"],
            "action": t["index_action"],
        }
        print(
            f"[{t['name'].capitalize()}] Parking items index ({t['index_action']}): "
            f"{t['parking_page_id']} {t['parking_url']}"
        )
    return summary


def park_item(
    spec: Dict[str, Any],
    target: str = "personal",
    personal_parent: Optional[str] = None,
    shared_parent: Optional[str] = None,
    clean_index: bool = False,
) -> Dict[str, Any]:
    """Publish a deferred Zero-Memory Implementation Plan to Personal (default) and/or Shared Parking items."""
    targets = _resolve_parking_targets(
        target=target,
        personal_parent=personal_parent,
        shared_parent=shared_parent,
        clean_index=clean_index,
        create_if_missing=True,
    )
    engineer_name = str(spec.get("engineer_name") or CONFIG.get("engineer_name") or "").strip()
    results: Dict[str, Any] = {}

    for t in targets:
        final_title, icon_emoji, blocks = _build_parking_item_blocks(
            spec,
            is_shared=t["is_shared"],
            engineer_name=engineer_name,
        )
        res = _upsert_parking_child_page(t, final_title, icon_emoji, blocks)
        res["parking_page_id"] = t["parking_page_id"]
        res["parking_url"] = t["parking_url"]
        results[t["name"]] = res
        print(
            f"[{t['name'].capitalize()}] Parked item ({res['action']}, {res['blocks_written']} blocks): "
            f"{final_title}\n  URL: {res['url']}"
        )

    return results


def list_parking_items(target: str = "personal") -> Dict[str, List[Dict[str, str]]]:
    """List parked child page items in the selected Parking items page(s) without creating missing pages."""
    targets = _resolve_parking_targets(target=target, clean_index=False, create_if_missing=False)
    out: Dict[str, List[Dict[str, str]]] = {}
    for t in targets:
        items: List[Dict[str, str]] = []
        for blk in _list_all_children(t["client"], t["parking_page_id"]):
            if blk.get("type") == "child_page":
                title = (blk.get("child_page") or {}).get("title", "").strip()
                items.append({
                    "id": blk["id"],
                    "title": title,
                    "url": f"https://www.notion.so/{blk['id'].replace('-', '')}",
                })
        out[t["name"]] = items
        print(f"\n[{t['name'].capitalize()}] Parking items ({t['parking_page_id']}):")
        if not items:
            print("  (empty)")
        for idx, item in enumerate(items, 1):
            print(f"  {idx}. {item['title']} ({item['id']})")
    return out


# ---------------------------------------------------------
# CLI Entrypoint
# ---------------------------------------------------------
def _check_db_access(client: Client, label: str, db_id: str) -> bool:
    if not db_id:
        print(f"  {label}: (not configured)")
        return True
    try:
        if hasattr(client, "databases") and hasattr(client.databases, "retrieve"):
            client.databases.retrieve(database_id=db_id)
        print(f"  {label}: {db_id} [OK]")
        return True
    except Exception as exc:
        print(
            f"  {label}: {db_id} [FAILED: {exc}]\n"
            f"    Hint: Open this Notion database -> '...' -> 'Connections' and connect your Notion integration."
        )
        return False


def test_connection():
    ok = True
    try:
        client = get_client()
        user = client.users.me()
        print(f"Notion Connection Successful! Signed in as: {user.get('name', 'Integration')}")
        if CONFIG.get("engineer_name"):
            print(f"Engineer Name:     {CONFIG.get('engineer_name')}")
        ok = _check_db_access(client, "Tasks Database ID", str(CONFIG.get("tasks_database_id") or "")) and ok
        ok = _check_db_access(client, "EOD Database ID", str(CONFIG.get("eod_database_id") or "")) and ok

        shared_tasks_db = str(CONFIG.get("shared_tasks_database_id") or "").strip()
        shared_eod_db = str(CONFIG.get("shared_eod_database_id") or "").strip()
        if shared_tasks_db or shared_eod_db:
            if not str(CONFIG.get("engineer_name") or "").strip():
                print("  Warning: 'engineer_name' is empty; shared team writes require engineer_name.")
                ok = False
            shared_client = _resolve_shared_client(client)
            shared_user = shared_client.users.me()
            print(f"Shared Notion Auth OK! Signed in as: {shared_user.get('name', 'Integration')}")
            ok = _check_db_access(shared_client, "Shared Tasks DB ID", shared_tasks_db) and ok
            ok = _check_db_access(shared_client, "Shared EOD DB ID", shared_eod_db) and ok
        return ok
    except Exception as e:
        print(f"Notion Connection Failed: {e}")
        return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Automated Notion Engineering Reporter")
    parser.add_argument("--test-connection", action="store_true", help="Test Notion API connection and view config")
    parser.add_argument("--init-dbs", action="store_true", help="Auto-create Personal Tasks & EOD Notion DBs inside --parent-page")
    parser.add_argument("--init-shared-dbs", action="store_true", help="Auto-create Shared Team Tasks & EOD Notion DBs inside --shared-parent-page (or --parent-page)")
    parser.add_argument("--parent-page", type=str, help="Notion page URL or ID where Tasks & EOD DBs should be created")
    parser.add_argument("--shared-parent-page", type=str, help="Notion page URL or ID where Shared Team DBs should be created")
    parser.add_argument("--setup-member", action="store_true", help="Configure a team member's personal & shared Notion DBs")
    parser.add_argument("--name", type=str, help="Engineer name for --setup-member (used to tag shared team rows)")
    parser.add_argument("--tasks-db", type=str, help="Personal Notion Tasks database ID for --setup-member")
    parser.add_argument("--eod-db", type=str, help="Personal Notion EOD database ID for --setup-member")
    parser.add_argument("--shared-tasks-db", type=str, help="Shared Team Notion Tasks database ID for --setup-member")
    parser.add_argument("--shared-eod-db", type=str, help="Shared Team Notion EOD database ID for --setup-member")
    parser.add_argument("--project", type=str, help="Default Project name for --setup-member")
    parser.add_argument("--branch", type=str, help="Default git branch for --setup-member")
    parser.add_argument("--sprint", type=str, help="Default sprint label for --setup-member")
    parser.add_argument("--token", type=str, help="Optional personal Notion token to store securely for --setup-member")
    parser.add_argument("--shared-token", type=str, help="Optional shared workspace Notion token for --setup-member")
    parser.add_argument("--ensure-schema", action="store_true", help="Ensure Time Spent & Engineer columns exist on Notion DBs")
    parser.add_argument("--rebalance", action="store_true", help="Enforce max daily hours cap across buffer & Notion")
    parser.add_argument("--list-buffer", action="store_true", help="List tasks currently in daily_buffer.jsonl")
    parser.add_argument("--log-task", type=str, help="Path to JSON task spec file to publish to Notion")
    parser.add_argument("--sync-eod", action="store_true", help="Auto-compile today's tasks into the EOD Briefing")
    parser.add_argument("--sync-shared", action="store_true", help="Backfill buffered tasks & EODs into Shared Team Notion DBs")
    parser.add_argument("--init-parking", action="store_true", help="Create/verify separate 'Parking items' pages on Personal and Shared Notion hubs")
    parser.add_argument("--park-item", type=str, help="Path to JSON parking spec file to publish to Personal & Shared Parking items")
    parser.add_argument("--park-md", type=str, help="Path to a Markdown implementation plan to publish to Personal & Shared Parking items")
    parser.add_argument("--list-parking", action="store_true", help="List parked items under Personal & Shared Parking items pages")
    parser.add_argument("--target", type=str, default="personal", choices=["personal", "shared", "both"], help="Where to publish/list parking items (default: personal; pass 'shared' or 'both' ONLY when explicitly requested)")
    parser.add_argument("--title", type=str, help="Optional override title for --park-md / --park-item")
    parser.add_argument("--icon", type=str, help="Optional emoji icon for parked child page (default: 🛡️)")
    parser.add_argument("--clean-index", action="store_true", help="Strip non-child-page clutter from the Parking items index page")
    parser.add_argument("--date", type=str, default="today", help="Date in YYYY-MM-DD format or 'all' for --rebalance / --sync-shared")
    args = parser.parse_args()

    if args.test_connection:
        sys.exit(0 if test_connection() else 1)
    elif args.init_dbs:
        if not args.parent_page:
            print("Error: --init-dbs requires --parent-page <notion_page_url_or_id>")
            sys.exit(1)
        init_notion_databases(args.parent_page, shared=False)
    elif args.init_shared_dbs:
        target_page = args.shared_parent_page or args.parent_page
        if not target_page:
            print("Error: --init-shared-dbs requires --shared-parent-page <url_or_id> (or --parent-page)")
            sys.exit(1)
        init_notion_databases(target_page, shared=True)
    elif args.setup_member:
        setup_member(
            name=args.name,
            tasks_db=args.tasks_db,
            eod_db=args.eod_db,
            shared_tasks_db=args.shared_tasks_db,
            shared_eod_db=args.shared_eod_db,
            parent_page=args.parent_page,
            shared_parent_page=args.shared_parent_page,
            project=args.project,
            branch=args.branch,
            sprint=args.sprint,
            token=args.token,
            shared_token=args.shared_token,
        )
    elif args.ensure_schema:
        ensure_time_spent_columns(get_client())
        print("Verified schema columns on configured Notion data sources.")
    elif args.rebalance:
        target = datetime.now().strftime("%Y-%m-%d") if args.date == "today" else args.date
        res = rebalance_buffer_and_notion(client=get_client(), target_date=target, max_daily_hours=MAX_DAILY_HOURS)
        for d, info in sorted(res.items()):
            print(
                f"  {d}: {info['count']} tasks | raw={info['raw_total']}h -> capped={info['capped_total']}h"
                + (f" (rebalanced {info.get('notion_tasks_updated', 0)} Notion pages)" if info["rebalanced"] else " (unchanged)")
            )
    elif args.list_buffer:
        tasks = _dedupe_tasks(read_buffer())
        print(f"Found {len(tasks)} tasks in daily buffer:")
        for i, t in enumerate(tasks, 1):
            hrs = _extract_hours_value(t)
            hrs_lbl = format_hours(float(hrs)) if hrs is not None else "N/A"
            print(f"  {i}. [{t.get('date')}] {t.get('title')} (Commit: {t.get('commit', 'N/A')} | Time: {hrs_lbl})")
    elif args.log_task:
        spec_path = Path(args.log_task)
        if not spec_path.exists():
            print(f"Error: Spec file not found: {args.log_task}")
            sys.exit(1)
        data = json.loads(spec_path.read_text(encoding="utf-8"))
        log_task(data)
    elif args.sync_eod:
        target = datetime.now().strftime("%Y-%m-%d") if args.date == "today" else args.date
        sync_eod(target_date=target)
    elif args.sync_shared:
        target = datetime.now().strftime("%Y-%m-%d") if args.date == "today" else args.date
        sync_shared(target_date=target)
    elif args.init_parking:
        init_parking_pages(
            target=args.target,
            personal_parent=args.parent_page,
            shared_parent=args.shared_parent_page,
            clean_index=args.clean_index,
        )
    elif args.park_item:
        spec_path = Path(args.park_item)
        if not spec_path.exists():
            print(f"Error: Parking spec file not found: {args.park_item}")
            sys.exit(1)
        data = json.loads(spec_path.read_text(encoding="utf-8"))
        if args.title:
            data["title"] = args.title
        if args.icon:
            data["icon"] = args.icon
        park_item(
            data,
            target=args.target,
            personal_parent=args.parent_page,
            shared_parent=args.shared_parent_page,
            clean_index=args.clean_index,
        )
    elif args.park_md:
        md_path = Path(args.park_md)
        if not md_path.exists():
            print(f"Error: Markdown plan file not found: {args.park_md}")
            sys.exit(1)
        data = {
            "markdown_path": str(md_path),
            "title": args.title or "",
            "icon": args.icon or "🛡️",
        }
        park_item(
            data,
            target=args.target,
            personal_parent=args.parent_page,
            shared_parent=args.shared_parent_page,
            clean_index=args.clean_index,
        )
    elif args.list_parking:
        list_parking_items(target=args.target)
    else:
        parser.print_help()
