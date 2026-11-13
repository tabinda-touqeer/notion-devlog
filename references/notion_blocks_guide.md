# Notion Blocks & Data Source API Guide

This document provides technical guidelines and code patterns for publishing formatted blocks to Notion using `notion-client` in Python.

---

## 1. Core Block Builders

Use these standard helper functions to construct clean Notion block payloads:

```python
def heading_1(text):
    return {"object": "block", "type": "heading_1", "heading_1": {"rich_text": [{"text": {"content": text}}]}}

def heading_2(text):
    return {"object": "block", "type": "heading_2", "heading_2": {"rich_text": [{"text": {"content": text}}]}}

def heading_3(text):
    return {"object": "block", "type": "heading_3", "heading_3": {"rich_text": [{"text": {"content": text}}]}}

def paragraph(text, bold_prefix=""):
    rt = []
    if bold_prefix:
        rt.append({"text": {"content": bold_prefix}, "annotations": {"bold": True}})
    rt.append({"text": {"content": text}})
    return {"object": "block", "type": "paragraph", "paragraph": {"rich_text": rt}}

def bullet(text, bold_prefix=""):
    rt = []
    if bold_prefix:
        rt.append({"text": {"content": bold_prefix}, "annotations": {"bold": True}})
    rt.append({"text": {"content": text}})
    return {"object": "block", "type": "bulleted_list_item", "bulleted_list_item": {"rich_text": rt}}

def callout(text, emoji="📌"):
    return {
        "object": "block",
        "type": "callout",
        "callout": {
            "icon": {"type": "emoji", "emoji": emoji},
            "rich_text": [{"text": {"content": text}}]
        }
    }

def code_block(code, language="python"):
    return {
        "object": "block",
        "type": "code",
        "code": {
            "language": language,
            "rich_text": _chunk_rich_text(code),  # split <= 1900 chars per item
        }
    }

def todo_item(text, checked=False):
    return {
        "object": "block",
        "type": "to_do",
        "to_do": {"rich_text": _parse_inline_rich_text(text), "checked": bool(checked)},
    }

def table_block(rows, has_column_header=True):
    width = len(rows[0])
    return {
        "object": "block",
        "type": "table",
        "table": {
            "table_width": width,
            "has_column_header": has_column_header,
            "has_row_header": False,
            "children": [
                {"type": "table_row", "table_row": {"cells": [_parse_inline_rich_text(c) for c in r]}}
                for r in rows
            ],
        },
    }

def divider():
    return {"object": "block", "type": "divider", "divider": {}}
```

> **Note:** Nested list items (`numbered_list_item` / `bulleted_list_item` with `children`) must stay at **<= 2 levels of nesting** per Notion API `create`/`append` call, and inline markdown (`**bold**`, `*italic*`, `` `code` ``) should be parsed into Notion `annotations` rather than left as raw asterisks/backticks.

---

## 2. API Limits & Safe Chunking

* **Max 100 Blocks per Request**: The Notion API rejects payloads with more than 100 blocks in a single `blocks.children.append` call.
* **Max 2000 Characters per Rich Text Object**: Any single string longer than 2000 characters must be split across multiple rich text items.

### Chunking Pattern:
```python
def append_blocks_safely(notion, page_id, blocks):
    for i in range(0, len(blocks), 100):
        chunk = blocks[i:i + 100]
        notion.blocks.children.append(block_id=page_id, children=chunk)
```

---

## 3. Notion 2025/2026 Data Source API Notes

In modern Notion API versions:
* Databases act as containers that house underlying `data_source` objects.
* When querying rows, use `notion.data_sources.query(data_source_id=...)`.
* When updating schemas, send `PATCH` requests to `/v1/data_sources/{data_source_id}`.
* When creating rows, pass `parent: {"data_source_id": data_source_id}`.

