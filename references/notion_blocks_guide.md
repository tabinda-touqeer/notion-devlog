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
            "rich_text": [{"text": {"content": code}}]
        }
    }

def divider():
    return {"object": "block", "type": "divider", "divider": {}}
```

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

