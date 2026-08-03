from __future__ import annotations

import pytest

from app.everos.memory.repair.episode_metadata import (
    _parse_episode_rewrite_response,
    repair_episode_markdown_text,
)

pytestmark = pytest.mark.no_db


def test_repair_episode_markdown_text_updates_subject_and_summary_only():
    text = """---
id: episode_log_huajie_Sun_2026-08-03
---
<!-- entry:ep_20260803_00000002 -->
## ep_20260803_00000002

**owner_id**: huajie_Sun
**timestamp**: 2026-08-03T02:42:29.560000+00:00
**parent_type**: cluster
**parent_id**: cl_4864a1b6b2a7

### Subject
A very long subject. This second sentence should be removed.

### Summary
Old prefix summary

### Content
Full content must stay unchanged.
<!-- /entry:ep_20260803_00000002 -->
"""

    repaired, changed = repair_episode_markdown_text(
        text,
        repairs={
            "ep_20260803_00000002": {
                "Subject": "Short subject.",
                "Summary": "Independent summary.",
            }
        },
    )

    assert changed is True
    assert "### Subject\nShort subject." in repaired
    assert "### Summary\nIndependent summary." in repaired
    assert "### Content\nFull content must stay unchanged." in repaired
    assert "parent_id**: cl_4864a1b6b2a7" in repaired


def test_repair_episode_markdown_text_can_update_content():
    text = """---
id: episode_log_huajie_Sun_2026-08-03
---
<!-- entry:ep_20260803_00000002 -->
## ep_20260803_00000002

**owner_id**: huajie_Sun
**parent_type**: cluster

### Subject
English subject

### Summary
English summary

### Content
English content
<!-- /entry:ep_20260803_00000002 -->
"""

    repaired, changed = repair_episode_markdown_text(
        text,
        repairs={
            "ep_20260803_00000002": {
                "Subject": "中文主题",
                "Summary": "中文摘要",
                "Content": "中文正文",
            }
        },
    )

    assert changed is True
    assert "### Subject\n中文主题" in repaired
    assert "### Summary\n中文摘要" in repaired
    assert "### Content\n中文正文" in repaired
    assert "**owner_id**: huajie_Sun" in repaired


def test_parse_episode_rewrite_response_accepts_unescaped_quotes_in_content():
    text = '''```json
{"subject":"2026年7月31日huajie_Sun检查本地和EverOS记忆均未找到旧记录","summary":"2026年7月31日，huajie_Sun询问助手能否看到其之前的记忆。助手检查本地记忆目录未发现文件，查询EverOS记忆服务也因沙箱网络隔离无法连接。","content":"UTC 08:08，huajie_Sun回复"e vero s"（疑为意大利语"确实是"），助手随即尝试查询EverOS记忆服务。"}
```'''

    parsed = _parse_episode_rewrite_response(text)

    assert parsed == {
        "subject": "2026年7月31日huajie_Sun检查本地和EverOS记忆均未找到旧记录",
        "summary": "2026年7月31日，huajie_Sun询问助手能否看到其之前的记忆。助手检查本地记忆目录未发现文件，查询EverOS记忆服务也因沙箱网络隔离无法连接。",
        "content": 'UTC 08:08，huajie_Sun回复"e vero s"（疑为意大利语"确实是"），助手随即尝试查询EverOS记忆服务。',
    }
