# 资料解释规范

## document.md

`document.md` 是解析器整理后的主文本。优先用于理解文档主体，但不要忽略其可能包含 OCR 错字、断行、页眉页脚或表格变形。

## blocks.json

`blocks.json` 是结构块。关注：

- `type`: heading、paragraph、table、image、code、formula 等。
- `text`: 块文本。
- `page` / `bbox`: 页码与区域。
- `confidence`: 置信度。

低置信度块只能作为线索，不能单独支撑强事实。

## 严格事实保真

创建用户分身时，个人履历、学校、公司、实习任务、项目名称、竞赛奖项、数字指标和时间线必须逐字贴近来源，不得为了让故事更完整而替换、泛化或改写成另一个事实。

- 如果来源写的是“成都星桥智能科技有限公司”，不要改成“某互联网公司”或“某科技公司”。
- 如果来源写的是“P95 延迟从 780ms 降到 240ms”，不要改成“500ms 到 120ms”或其他更顺口的数字。
- 如果来源写的是“日志告警服务 / 慢查询 / REST 与 GraphQL 技术评审”，不要改成“订单查询接口”或其他常见后端案例。
- 低置信 OCR、图表注释、公式页只能补充已有事实的证据，不得独立生成新的公司、项目、指标、奖项或经历。
- 没有来源的具体例子只能放入 `unknowns`、`warnings` 或候选线索，不得写入 profile、timeline、dialogue scenes、evidence cards 或 persona kernel 的确定事实。

## provenance.json

所有事实、风格判断和证据卡都必须绑定 provenance。没有 provenance 的内容只能写入 unknowns 或 warnings。

## web_sources

`web_sources` 来自联网资料搜索与网页抓取，已经带有 URL、title、source_family、
trust_level、content_hash 和 locator。使用规则：

- 只有 trust_level 较高、内容与分身明显相关、且 provenance 完整的 web source 才能支撑确定事实。
- weak_clue、论坛传闻、SEO 页面和低分候选只能作为线索或待确认内容。
- 同一事实若多源冲突，不要自行消解；写入 fact_graph.conflicts，并在 reviewed corpus 中标出不确定性。
- evidence card 的 provenance 可以使用 web_source_id、url、title、content_hash、locator，不得只写“来自网络”。

## diagnostics.json

使用 diagnostics 判断文档质量：

- OCR 页、扫描页、低质量页需要降低事实置信度。
- 乱码率高的文件先修复再使用，无法修复则标记为低质量。
- 多 parser 结果冲突时保留冲突，不要擅自二选一编故事。

## 矛盾处理

遇到矛盾资料：

1. 标出冲突来源。
2. 优先使用用户明确提供的自述、简历、正式文档。
3. 不确定时写成“材料中存在两种说法”，不要伪装确定。
