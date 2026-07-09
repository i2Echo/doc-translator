# PDF Layout Convergence Plan

## 背景

当前 PDF 翻译质量的问题不是单点规则不够精细，而是结构修复策略整体缺少收敛边界。

当前接入方式不是 BabelDOC 官方 hook API，而是 `babeldoc_runner.py` 里的 `_build_hooked_high_level()` 子类化 `ParagraphFinder`、`StylesAndFormulas`、`ILTranslator`、`Typesetting`、`PDFCreater` 等 stage 类，再把这些子类放回 `high_level` 的函数 globals。这个接线方式很灵活，但也强依赖 BabelDOC 私有实现。BabelDOC 升级时，覆盖点和方法签名都可能脆断。

`babeldoc_hooks.py` 分别处理段落切分、同行碎片合并、重复文本、竖排标签、技术 token、字号恢复和 render-unit 替换。局部看，每条规则都能修一个具体问题；全局看，规则之间共享同一批不稳定信号，如 `layout_label`、矩形、baseline、字体大小和文本形态。一个规则提前改了 paragraph 边界，后续规则就在新的结构上继续翻译和排版，错误会被放大。

目标不是继续堆更多特判，而是把当前策略改成可验证、可回退、可分层的版面修复体系。

## 现状校正

落地前需要先对齐几个代码事实。

1. 没有官方 hook 注册层。  
   所有接线都集中在 `babeldoc_runner.py` 的 monkey-patch 子类方案里。后续整改应继续把 BabelDOC 私有覆盖点集中在这个文件，不要把 monkey-patch 扩散到更多模块。升级 BabelDOC 时必须跑完整回归集。

2. 主要结构改写集中在 `StylesAndFormulas.process`，但不是全部。  
   `ILTranslator` 阶段主要做 `should_skip_translation`、`translation_text_override`、`translated_text_override`、`record_translation` 等 text-only 行为，不直接改 paragraph 边界。大多数结构规则在翻译前执行；但 `split_numbered_lists_before_typesetting` 在翻译后、typesetting 前执行，也会重写 `page.pdf_paragraph`。因此 layout guard 不能只覆盖 `StylesAndFormulas.process` 阶段，翻译后结构切分也必须纳入同一套策略。

3. 当前并不是完全“先改结构再分类”。  
   实际顺序是 `normalize_font_traits`、`normalize_fragmented_paragraphs_before_translation`、`classify_document`，之后每个结构规则成功后都会全量 `classify_document`。所以后续的“增量重分类”不是新能力，而是对当前多次全量重扫的性能和可解释性优化。

4. 还没有 per-rule 开关层。  
   今天要关闭某个结构规则，只能改代码调用点。这意味着“默认关闭”和“可回退”都还没有基础设施支撑。

5. sidecar 还不足以支撑所有验收项。  
   现有部分 action 只记录数量和 sample，不记录 role、region、guard decision。要按“普通正文触发结构 action 数量”验收，必须先补 sidecar 字段。

6. 存在未接线的结构规则死代码。  
   `split_fallback_line_technical_token_runs_before_translation`、`merge_fallback_line_underscore_compounds_before_translation`、`normalize_fallback_line_texts_before_translation`、`merge_fallback_line_fragments_before_translation` 在当前 runner 中没有调用点。它们不应被纳入第一阶段开关，也不应被“顺手补接线”激活；后续应在清理阶段删除。

## 核心诊断

全局不收敛主要来自四类问题。

1. 结构改写过早。  
   `normalize_fragmented_paragraphs_before_translation`、`merge_same_line_fragments_before_translation`、`remove_subsumed_same_line_duplicates_before_translation`、`collapse_overlapping_same_baseline_fragments_before_translation` 都在翻译前直接改 `pdf_paragraph`。一旦误切或误并，后续翻译、token 保护和 typesetting 都会建立在错误结构上。

2. 局部几何信号承担了全局版面判断。  
   baseline、gap、overlap 可以判断两个片段是否“看起来相邻”，但不能可靠判断它们是否属于同一栏、同一语义块、同一表格、同一图注或同一正文段。

3. 规则没有明确风险等级。  
   有些规则只是保护 token，有些规则会删除、复制、合并或拆分 paragraph，但它们在调用链里没有统一的风险门槛。低置信规则和高置信规则都可能直接改结构。

4. 缺少回归闭环。  
   sidecar 能记录发生了什么，但没有自动告诉我们这次修改是否让一组代表性 PDF 整体变好。修一个样本后，另一个样本退化，只能靠人工截图发现。

## 总体方向

采用“三层收敛”路线。

1. 先把危险规则降级。  
   短期内禁止低置信结构改写，只保留明确可证明的窄场景。先让普通正文回到 BabelDOC 原生排版路径。

2. 再引入页面版面模型。  
   在 paragraph 改写前，先构建 page-level layout model，包括栏位、正文区域、边栏、图表区域、页眉页脚和表格候选。任何合并、切分、复制都必须经过该模型约束。

3. 最后建立样本回归门禁。  
   每次修改规则都必须跑固定样本集，比较 sidecar 行为、页面截图和结构指标，避免继续凭单个 PDF 调阈值。

实际落地顺序建议为：先完成 Milestone 1，再做 Milestone 3a 的单 PDF metrics runner，然后做 Milestone 2 的页面布局 guard，最后做 Milestone 3b 的批量门禁。也就是先有尺子，再造 guard，再把尺子升级成门禁。

## 第一阶段：止血

周期：分 M1a 和 M1b 两步，每步 1 到 2 天。

目标：先停止最容易破坏普通文档的结构改写。

### 0. 建立 per-rule 开关层

这是第一阶段的前置步骤。没有开关层，“默认关闭”和“可回退”都只能靠改代码或 git revert，落地成本和风险都太高。

建议先用环境变量或 runtime settings 中的内部配置实现，不需要先做 UI。

建议字段：

```text
PDF_HOOK_STRUCTURE_NORMALIZE_FRAGMENTED=observe|apply|off
PDF_HOOK_STRUCTURE_MERGE_SAME_LINE=observe|apply|off
PDF_HOOK_STRUCTURE_REMOVE_SUBSUMED=observe|apply|off
PDF_HOOK_STRUCTURE_COLLAPSE_OVERLAP=observe|apply|off
PDF_HOOK_STRUCTURE_SPLIT_NUMBERED_LISTS=observe|apply|off
PDF_HOOK_STRUCTURE_RECONCILE_REPEATED_EDGE=observe|apply|off
PDF_HOOK_STYLE_RESTORE_VERTICAL_LAYOUT=observe|apply|off
PDF_HOOK_RENDER_AXIS_LABEL=observe|apply|off
```

默认值建议：

| 规则类型 | 默认 |
| --- | --- |
| `text_only` | `apply` |
| `style_only` | `apply`，但必须 scoped |
| `structure` | `observe` |
| `render` | `apply`，保留现有轴标签路径 |

第一版可以只在 `BabeldocHookContext` 初始化时生成一个 `HookPolicy`，由 `babeldoc_runner.py` 传入。不要把环境变量读取散落到每条规则内部。

`observe` 应作为默认回退模式，保留可见性；`off` 只用于已知坏规则、废弃规则或临时故障隔离。不要把 `off` 当作常规调参手段。

需要注意：`observe` 不是给现有函数外层套一个 if。当前结构规则通常把“判定要做什么”和“实际改写 paragraph”写在同一个循环里。要支持 observe，必须把每条结构规则拆成 dry-run plan 和 apply 两段：plan 产出本来会做的 action，apply 才真正修改 `unicode`、`composition`、`box` 或 `page.pdf_paragraph`。这是 M1 的实际工程前提。

### 1. 给结构改写规则加风险分级

新增一个内部分类，不一定先抽象成复杂框架，可以先用函数命名和调用分组落地。

| 等级 | 行为 | 例子 | 默认策略 |
| --- | --- | --- | --- |
| `observe` | 只写 sidecar，不改结构 | 疑似跨栏、疑似图注、疑似碎片 | 总是允许 |
| `text_only` | 只改翻译输入/输出文本，不改 paragraph 边界 | 技术 token 保护、TOC title 翻译 | 高置信允许 |
| `style_only` | 只改 run 样式或恢复已标记段落布局，不改段落边界 | 局部字号恢复、竖排 passthrough 恢复 | 必须 scoped |
| `structure` | 拆、并、删、复制 paragraph，或跨页覆盖 composition | 多行切分、同行合并、重复块删除、编号列表切分、重复页眉页脚同步 | 默认 observe，白名单 apply |
| `render` | 替换最终 render unit | 竖排轴标签重绘 | 独立门禁 |

第一阶段要做的是把所有 `structure` 规则都改成显式白名单触发。普通正文、双栏正文、多行 prose block、未知 layout label 默认不改。

### 2. 立即降级的规则

建议先处理以下规则，因为它们最容易引发全局漂移。

| 规则 | 位置 | 问题 | 第一阶段策略 |
| --- | --- | --- | --- |
| `normalize_fragmented_paragraphs_before_translation` | `babeldoc_hooks.py` | 会把普通多行正文拆成独立段，破坏缩进和字号 | 仅保留高置信 `fallback_line` 技术标签；普通正文只记录诊断 |
| `merge_same_line_fragments_before_translation` | `babeldoc_hooks.py` | 会跨栏误并多行正文块 | 禁止合并两个多行 prose block；禁止跨栏合并 |
| `collapse_overlapping_same_baseline_fragments_before_translation` | `babeldoc_hooks.py` | 会吞掉重叠但语义不同的片段 | 只对同一小型标签/数字碎片启用 |
| `remove_subsumed_same_line_duplicates_before_translation` | `babeldoc_hooks.py` | 可能删掉真实重复文本或公式周边 token | 先改为 observe，收集命中样本 |
| `split_numbered_lists_before_typesetting` | `babeldoc_hooks.py` | 翻译后才拆 paragraph，绕过翻译前 layout guard | 纳入 `structure`，只允许编号 marker 高置信命中 |
| `reconcile_translation` | `babeldoc_hooks.py` | 跨页复制 leader 的译文和 composition 到 follower | 纳入 `structure`，对白名单 `running_edge_text` 默认 apply |
| `restore_source_layouts_before_typesetting` | `babeldoc_hooks.py` | 恢复 `vertical_label` 的原始 unicode/composition/scale | 纳入 `style_only` scoped，默认 apply |
| `normalize_body_font_sizes_before_typesetting` | `babeldoc_hooks.py` | 如果前面结构错，会继续放大字号问题 | 只允许作用于被本 job 明确标记的 scoped paragraph |

### 3. 第一阶段验收

必须满足：

1. `translate.cli.font.unknown.pdf` 不再把普通正文拆成视觉行。
2. `translate.cli.text.with.figure.pdf` 不再跨栏合并正文块。
3. `lm555.pdf` 首页不出现明显漏译、重叠或大面积原文残留。
4. sidecar 中普通正文触发 `decision=applied` 的 `structure` action 数量接近 0。

验收顺序必须是：先补 sidecar action 类型、role、region、guard decision，再调整开关默认值，最后跑样本验收。否则第 4 条没有可测数据。

这一阶段不追求修复所有历史问题，只追求把最大破坏面压下来。

## 第二阶段：页面版面模型

周期：3 到 5 天。

目标：让规则先知道“页面上有哪些区域”，再决定能不能改结构。

### 1. 新增 page layout summary

在 `StylesAndFormulas.process` 后、任何结构改写前，对每页建立轻量模型。

建议字段：

```text
PageLayoutSummary
- page_number
- page_rect
- content_rect
- columns
- edge_bands
- header_footer_candidates
- figure_regions
- table_like_regions
- paragraph_regions
```

第一版不需要机器学习，也不需要完美识别，但不能只依赖 paragraph rect 的 x 聚类。栏位检测必须融合多类信号，低置信时降级为 `unknown`，而不是强行分配 `body_column`。

建议融合信号：

1. paragraph rect 的 x/y 分布。
2. vector 分隔线和页面线条。
3. image/xobj 区域。
4. `xobj_id` 边界。
5. 小 rect 密度和重复短文本。
6. 现有 `_looks_like_table_column_group`、`_should_skip_page_level_axis_group` 这类 guard 的判定经验。

标记每个 paragraph 的 `layout_region`：`body_column`、`edge`、`figure`、`table`、`unknown`。每个 region 都需要带 `confidence`。低置信 region 一律按 `unknown` 处理，只 observe，不 apply。

`PageLayoutSummary` 必须在 `StylesAndFormulas.process` 内构建完成并冻结为只读对象。后续并行阶段只读不写，避免引入新的共享状态问题。

### 2. 所有结构规则必须检查 layout guard

新增统一判断：

```text
can_merge(left, right, page_layout)
can_split(paragraph, page_layout)
can_remove(candidate, anchor, page_layout)
```

最关键的 guard：

1. 不跨 column 合并正文。
2. 不把 `body_column` 和 `figure/table/edge` 合并。
3. 不合并两个多行正文块。
4. 不拆普通正文块。
5. 只在同一 layout region 内处理碎片。
6. 对 `unknown` 默认 observe。

现有轴标签路径可以作为模板：`replace_axis_label_render_units` 和 `_should_skip_page_level_axis_group` 已经有 overlap、table-column、preserved record、axis record 的拒绝逻辑。M2 的 `can_merge`、`can_split`、`can_remove` 应优先复用这种“先收集候选、再给出明确 reject reason”的判定结构。

layout guard 的优先级高于规则自身启发式。也就是说，`can_merge`、`can_split`、`can_remove` 返回 reject 时，一律否决；各规则自己的 `_should_*` 只能在 guard 放行后继续收紧。

`split_numbered_lists_before_typesetting` 在 `Typesetting` 阶段执行，必须复用同一份冻结的 `PageLayoutSummary` 调用 `can_split`。它不能因为发生在翻译后就绕过 layout guard。

### 3. 修改 sidecar schema

sidecar 需要记录每个结构 action 的 guard 结果，便于后续排查。

建议加入：

```json
{
  "action": "merge_same_line_fragments_before_translation",
  "decision": "rejected",
  "reason": "cross_column",
  "left_region": "body_column:left",
  "right_region": "body_column:right"
}
```

所有 `structure` 事件都必须带 `decision` 字段，取值为 `applied`、`rejected`、`observed`、`skipped`。`observe` 模式写 `observed`，真正修改文档才写 `applied`。这样以后看到坏页，不需要重新猜是哪条规则，也能按 decision 做验收。

## 第三阶段：规则重排

周期：2 到 4 天。

目标：减少规则互相踩踏。

执行顺序以“推荐落地顺序”为准。规则重排应在单 PDF runner 和批量门禁可用后推进。

### 1. 调整 pipeline 顺序

当前顺序已经包含多次全量 `classify_document`：先 split，再 classify，后续 merge/remove/collapse 成功后继续全量 reclassify。建议改为：

1. BabelDOC 原始 paragraph。
2. capture source snapshot。
3. classify roles。
4. build page layout summary。
5. run structure diagnostics。
6. apply high-confidence structure changes。
7. reclassify changed paragraphs only。
8. translate。
9. text/style scoped postprocess。
10. render-level replacement。

重点是先诊断再改写，并且每次结构改写都能解释它基于哪个 layout guard。`reclassify changed paragraphs only` 的收益是减少当前多次全量重扫，不是改变最终分类语义。

### 2. 收紧结构规则职责

每条结构规则只解决一个形态，不再让一个函数同时处理正文、脚注、表格、技术标签。

建议拆分：

| 当前规则 | 拆分方向 |
| --- | --- |
| `normalize_fragmented_paragraphs_before_translation` | `split_compact_fallback_labels`、`observe_multiline_body_blocks` |
| `merge_same_line_fragments_before_translation` | `merge_broken_word_fragments`、`merge_inline_punctuation_fragments`、`observe_same_line_body_neighbors` |
| `collapse_overlapping_same_baseline_fragments_before_translation` | `merge_overprinted_duplicate_glyphs`、`observe_overlap_clusters` |

拆分后，每个函数的触发条件会窄很多，sidecar 也更容易看懂。

### 3. 保留 BabelDOC 原生行为作为基线

任何规则都必须能回答：

1. 不启用这条规则时，BabelDOC 原生输出坏在哪里？
2. 启用这条规则后，修复指标是什么？
3. 这条规则的拒绝条件是什么？
4. 哪些样本证明它没有扩大破坏面？

回答不了就先 observe，不进入 apply。

因为当前接线依赖 BabelDOC 私有 stage 类，基线还必须包含“BabelDOC 版本”这一维度。升级 BabelDOC 或修改 `_build_hooked_high_level()` 覆盖点时，必须跑完整样本集。

## 第四阶段：回归门禁

周期：分两步搭建，后续长期维护。

目标：让“全局是否变好”可见。

执行顺序以“推荐落地顺序”为准。单 PDF runner 应前移到页面布局 guard 之前，先提供量化判据。

### 1. 建立固定样本集

样本不能放在 `tmp/`，因为 `tmp/` 是临时目录并被 gitignore。建议放在版本化目录 `tests/regression/inputs/`，如果 PDF 体积继续增长，再考虑 Git LFS。

至少包含：

| 类型 | 样本 | 覆盖问题 |
| --- | --- | --- |
| 双栏论文 | `translate.cli.text.with.figure.pdf` | 跨栏、图文混排、竖排 arXiv |
| 未知字体论文 | `translate.cli.font.unknown.pdf` | 字体 fallback、正文重排 |
| datasheet | `lm555.pdf` 首页/多页 | 图表、表格、页眉页脚、技术 token |
| TI datasheet | `ADS1113-p01-p02.pdf`、`ADS1113-p03-p04.pdf`、`ADS1113-p11-p12.pdf` | 多栏、技术单位、页脚、表格、wrapped same-line tail 粘连、电路图短标注 |
| TOC 文档 | `toc-dot-leaders.pdf` | 点导引、页码保留 |
| 扫描/OCR 文档 | `scanned-ocr-smoke.pdf` | OCR workaround、白底擦除 |

### 2. 输出对比指标

每次跑样本生成：

1. 输出 PDF。
2. page PNG。
3. sidecar。
4. structure before/after。
5. 指标 JSON。

第一版指标不需要复杂视觉模型，可以先统计：

1. paragraph 数变化。
2. structure action 数量。
3. 被 split/merge/remove 的 role 和 region。
4. 跨栏合并拒绝次数。
5. 多行正文块被结构改写次数。
6. 字号归一命中次数。
7. 页面文本覆盖率。
8. 翻译后 overflow 段落数和每页 overflow 数。
9. `layout_status` 从 `ok` 变为 `overflow` 的段落数。

翻译后 overflow 必须进入指标。结构规则收敛不代表页面就稳定，CJK 译文变长导致的溢出是另一条独立退化链路。

第一版 PNG 渲染使用 PyMuPDF，因为项目已经依赖 `PyMuPDF`，Windows 本地和容器内都更容易复用。`pdftoppm` 或 `pdf2image` 可以作为后续更接近生产渲染的可选对照，不作为 M3a 前置依赖。

原文残留比例暂不进入第一版硬门禁。后续可以用“输出文本层对源文本长子串的匹配率”作为粗略指标，但在方法稳定前只做诊断，不做失败条件。

### 3. 设置硬门禁

建议第一批硬门禁：

1. `body_column` 之间不能跨 column merge。
2. 普通正文不能触发 visual-line split。
3. 两个多行 prose block 不能 merge。
4. `vertical_label` 不能进入普通 translation path。
5. structure action 数量相对基线突增时失败。
6. overflow 段落数相对基线突增时失败。

这些门禁比“截图看起来不错”更稳定。

### 4. 基线管理

metrics baseline 应进入版本化目录，例如 `tests/regression/baselines/`。runner 提供显式 `--update-baseline` 参数刷新基线；刷新必须在 PR 描述中说明原因。门禁只拦截恶化方向，例如 `decision=applied` 的普通正文结构 action 增加、overflow 增加、跨栏 merge 由 rejected 变 applied。改善方向放行，但仍写入 diff 供 review。

## 推荐落地顺序

### Milestone 1a：观测基础设施

0. 建立 per-rule 开关层。
1. 给现有结构规则加统一 action 类型和 sidecar 字段。
2. 所有现有 apply 路径补记 `decision=applied`。
3. 不改变任何 paragraph 行为。

交付物：

1. `babeldoc_hooks.py` 小范围修改。
2. sidecar 中结构 action 可读。
3. 单条结构规则可通过配置记录策略状态。

### Milestone 1b：行为止血

1. 将结构规则拆成 dry-run plan 和 apply 两段。
2. 把普通正文的结构改写默认降级到 `observe`。
3. 加多行正文块保护。
4. 跑三份核心样本并保存基线输出。

交付物：

1. 单条结构规则可通过配置回退到 `observe` 或 `off`。
2. 三份样本输出截图。
3. sidecar 能区分 `observed` 与 `applied`。

### Milestone 3a：单 PDF 回归 runner

1. 新增本地脚本跑单个 PDF。
2. 输出 PDF、PNG、sidecar、structure snapshot、metrics。
3. metrics 覆盖 structure action、guard decision、overflow。
4. 复用 `translate_pdf_with_babeldoc_library` 作为程序化翻译入口，不走 HTTP API。

交付物：

1. 一个可重复运行单 PDF 的命令。
2. 单 PDF metrics JSON。
3. PyMuPDF PNG 渲染输出。

### Milestone 2：页面布局 guard

1. 实现 `PageLayoutSummary`。
2. 融合 vector、xobj、rect 给 paragraph 标记 column 和 region。
3. 所有 merge/split/remove 调用 guard。
4. sidecar 记录 guard 决策。

交付物：

1. 可解释的 cross-column reject。
2. 双栏论文和 datasheet 同时稳定。
3. 低置信布局统一降级为 `unknown`，只 observe。

### Milestone 3b：批量回归门禁

1. 建立固定 PDF 样本集。
2. 批量运行并汇总 metrics。
3. 对硬门禁失败返回非 0。

交付物：

1. 一个可在 PR 前运行的命令。
2. 一份 metrics diff。
3. 硬门禁失败时能定位到 PDF、页面、action 和 reason。

### Milestone 4：规则拆分和清理

1. 拆分大而泛的结构函数。
2. 删除长期 observe 但没有稳定收益的规则。
3. 删除未接线的 fallback_line 死规则，禁止补接线激活它们。
4. 把魔法阈值提成命名常量。
5. 文档同步规则职责和触发条件。

交付物：

1. 更小的规则函数。
2. 更少的 action 类型。
3. 更稳定的回归指标。

Milestone 4 风险最高，必须在 Milestone 3b 变绿后再做。`babeldoc_hooks.py` 里大量 `_looks_like_*`、`_should_*`、baseline、edge-band helper 被多条规则共享。拆分时每次只拆一个函数或一组强相关函数，拆完立即跑回归，禁止大批量重排。

## 明确不建议的方向

1. 不继续为单个 PDF 加固定短语、固定页码或固定厂商规则。
2. 不继续扩大 `layout_label` 的含义，把它当作真实语义结构。
3. 不在翻译后用 preview/gatekeeper 大范围补洞，除非只是诊断。
4. 不把结构问题交给 LLM 判断；LLM 可翻译文本，但不应决定 paragraph 边界。
5. 不为每个坏样本单独调阈值，除非这个阈值能在回归集里证明不会扩大破坏面。

## 判断方案是否成功

这套方案成功的标志不是“某个 PDF 完美”，而是以下趋势稳定出现：

1. 普通正文触发 `decision=applied` 的结构改写次数下降。
2. sidecar 中每个结构改写都有明确 guard 依据。
3. 新增坏样本时，大多数问题先表现为 observe 记录，而不是直接破坏输出。
4. 修复一类 PDF 时，回归集中其他类型不再反复退化。
5. 规则数量增长变慢，规则职责更窄，拒绝原因更清楚。

## 下一步建议

当前已完成 Milestone 1a、Milestone 1b、Milestone 3a、Milestone 2 第一版 layout guard、Milestone 3b，以及 Milestone 4。

已落地能力：

1. `HookPolicy` per-rule 开关层，结构规则默认 `observe`。
2. 结构规则 plan/apply 拆分，sidecar schema v2 记录 `decision`、`role_counts`、guard 信息。
3. `PageLayoutSummary` 第一版，支持 `body_column`、`edge`、`table`、`figure`、`unknown`，并接入 merge/split/remove/collapse/split-numbered guard。
4. 单 PDF runner 和批量 runner，固定样本 baseline 进入版本化目录。
5. 批量硬门禁覆盖普通正文 structure applied、overflow、cross-column allowed、unknown/non-body allowed、普通正文 split allowed。
6. 未接线 fallback_line 结构死规则已删除，避免后续误激活。
7. 第一版 layout guard 的列识别、区域置信度和容差阈值已收束为命名常量，后续调参可以直接对照语义修改。
8. `normalize_fragmented` 已拆为 `observe_multiline_body_blocks` 与 `split_compact_fallback_labels` 两条内部计划路径。
9. `merge_same_line` 的候选链、plan item 和 reject sample 构造已提为小 helper，plan/apply 仍复用原判定顺序。
10. `collapse_overlap` 的 cluster 构造已由 plan/apply 共享，并修复了 plan 阶段潜在未定义变量路径。
11. 新增通用 `merge_same_line_fragment_bridge` 与 `split_wrapped_same_line_tail` 白名单规则，分别修复同 baseline 断词/小数/内联标点碎片、以及同列行尾碎片被粘到下一视觉行 paragraph 的抽取形态；规则不依赖文件名、页码、厂商或固定短语。
12. 新增电路图 `fallback_line` 短标注保护：对同页同 xobj 的图形技术标注簇，只 preserve 短小且明显抽取损坏/紧凑技术化的标签，避免源文本层损坏后进入普通翻译路径。

下一步建议：

1. 继续用真实坏样本扩充固定样本集，优先替换或补充更贴近生产文档的 TOC 和扫描/OCR 样本。
2. 新增坏样本时先进入 `tests/regression/inputs/` 和 baseline，再讨论规则变化。
3. BabelDOC 升级或 `_build_hooked_high_level()` 覆盖点变化时，必须跑完整容器 batch。
