# 输出契约

DeepSeek 必须返回严格 JSON。禁止返回 Markdown 代码围栏。

## 顶层 JSON

```json
{
  "source_depth": "limited|moderate|rich",
  "repaired_sources": [],
  "fact_graph": {},
  "style_profile": {},
  "corpus_files": {},
  "evidence_cards": [],
  "persona_kernel": {},
  "quality_summary": {}
}
```

## corpus_files 必需文件

- `profile.md`
- `source_notes.md`
- `timeline.md`
- `thinking_style.md`
- `voice_style.md`
- `quote_anchors.md`
- `qa_seed.md`
- `negative_facts.md`
- `style_boundaries.md`
- `source_expansion_overview.md`
- `source_expansion_dialogue_scenes.md`

每个 Markdown 文件必须包含：

```yaml
---
persona_id: "<persona_id>"
source_type: "reviewed_profile|timeline|voice_style|evidence_expansion|style_boundary|qa_seed"
trust_level: "reviewed"
privacy_level: "private"
---
```

## evidence_cards

每张卡：

```json
{
  "card_id": "persona_id_card_000001",
  "source_title": "文件名或资料标题",
  "source_locator": "页码/段落/区域",
  "tags": ["身份", "风格"],
  "keywords": ["关键词"],
  "quote_anchor": "短锚点，不复制长篇原文",
  "text": "一条可检索、可回答的证据内容",
  "boundary_note": "适用边界或不确定性",
  "provenance": [
    {
      "file_id": "upload file id",
      "block_id": "block id",
      "page": 1,
      "confidence": 0.92
    },
    {
      "web_source_id": "web source id",
      "url": "https://example.com/source",
      "title": "网页标题",
      "content_hash": "sha256",
      "locator": "web/sentence/section"
    }
  ]
}
```

要求：

- `text` 必须能由 provenance 支撑。
- `quote_anchor` 控制在短锚点，不要复制整段版权文本。
- 资料不足时允许少于 3200 张。

## persona_kernel

```json
{
  "persona_id": "...",
  "display_name": "...",
  "speech_rhythm": [],
  "emotional_posture": [],
  "conversation_principles": [],
  "boundary_posture": [],
  "typical_scenes": [],
  "overused_theme_bans": [],
  "unknowns": []
}
```

## quality_summary

```json
{
  "source_depth": "limited|moderate|rich",
  "provenance_coverage": 0.0,
  "evidence_card_count": 0,
  "ocr_low_confidence_count": 0,
  "conflicts": [],
  "blockers": [],
  "warnings": []
}
```
