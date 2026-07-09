# BabelDOC Internal Hooks IR Refactor

## 背景

之前的后处理路线把问题放在 BabelDOC 输出之后解决：先生成 PDF，再用 preview/gatekeeper 找缺块、未译块并补译。这类方案容易局部有效、全局不收敛，因为它看到的是已经排版后的结果，缺少 BabelDOC 在 paragraph、style、typesetting 阶段掌握的结构上下文。

新的路线不 fork BabelDOC，也不在 Docker 构建时 patch BabelDOC 源码。应用改为通过 BabelDOC library API 调用 `async_translate`，并在运行期临时 hook `high_level` 里已经导入的中间层类。hook 默认透传，只对高置信结构写入 sidecar IR，并在少数可逆、可幂等的场景里影响翻译。

## 当前落地

PDF 翻译入口从 CLI 子进程改为 `doc_translator.babeldoc_runner.translate_pdf_with_babeldoc_library`。它保留原有关键参数：OpenAI-compatible translator、无水印单语输出、OCR workaround、qps、report interval、BabelDOC progress event 到任务进度的映射。

运行期 hook 点：

1. `ParagraphFinder.process`
2. `StylesAndFormulas.process`
3. `ILTranslator.pre_translate_paragraph`
4. `ILTranslator.post_translate_paragraph`
5. `ILTranslatorLLMOnly.translate`
6. `Typesetting.typesetting_document`
7. `PDFCreater.create_render_units_for_page`

`StylesAndFormulas` 之后建立分类，因为这时 paragraph 已经稳定，公式和样式也已处理，比解析早期更适合做 role 判断。分类后会先做一次通用的同 baseline paragraph 合并，再重新分类；这样可以处理 PDF 文本提取把一个视觉行切成多个 paragraph 的情况，避免半个英文词、半句源文分别进入翻译和排版。

因为 BabelDOC 0.6.2 的 `high_level` pipeline 在模块全局引用这些类，runner 不直接修改模块全局对象，而是为每个 PDF job 克隆 `async_translate` / `do_translate` / `_do_translate_single` / `get_translation_stage` 的函数 globals，并把其中的中间层类绑定到本 job 的 Hooked 类。这样多个 PDF job 可以并行执行，hook context 和 sidecar 不会互相串线。DOCX 翻译不经过这条 hook 路径。

每次 PDF 翻译会在输出旁写一个 sidecar：

```text
<output>.pdf.babeldoc-ir.json
```

sidecar 记录 schema、角色计数、命中的 paragraph、分组、hook 阶段事件和实际应用过的策略。
其中 `axis_diagnostics` 专门记录疑似图表轴标签：`paragraph_candidates` 来自 paragraph/role 阶段，`character_groups` 来自 PDF 创建阶段的最终 `render_units` 替换阶段，并附带轴标签的标准化英文文本与最终译文，用来判断异常发生在 BabelDOC IR、字符分组，还是最终渲染。

## 高置信 Role

高置信 role 不由 LLM 判断，只由确定性规则产生。规则必须同时满足这些原则：

1. 全局扫描后再决策，不按单页局部立即改写。
2. 默认 `pass_through`，无法高置信就不介入。
3. role 与 policy 分离：分类不等于修改。
4. 所有实际修改必须能写入 sidecar，并且能重复运行得到同类结果。
5. 不把 TOC、竖排文字这类几何敏感对象强行塞进普通正文翻译路径。
6. 不把某个测试 PDF 的固定短语、厂商文案或章节标题写成规则；真实规则只能依赖结构、几何、重复性和 token 形态。

当前 role：

| role | policy | 当前行为 |
| --- | --- | --- |
| `preserved_token` | `preserve` | 跳过页码、单个短技术 token、纯数字/符号等明显不应翻译的 paragraph；带空格的小标题不再进入 preserve |
| `running_edge_text` | `translate_once` | 对跨页重复且靠近页边的页眉/页脚类文本建立分组；若 BabelDOC 已生成可复制的纯 unicode composition，则统一重复文本翻译 |
| `toc_entry` | `translate_title_preserve_locator` | 识别早期页面中带点线 leader 和页码尾缀的 TOC 行，只翻译标题段，leader 和页码原样拼回 |
| `vertical_label` | `preserve` | 识别 BabelDOC vertical paragraph 或高窄多行坐标轴块，暂时跳过普通翻译，避免竖排标签被拆成散字 |

已经移除的方向：

1. 不再内置某个厂商 datasheet 的 NOTE、状态说明、章节标题等确定性译文。
2. 不再用固定词表识别图表轴标题，例如某些测试样本中的电流、电压、误差等英文词。
3. 不再通过样本 signature 抑制某些残片；这类处理必须回到结构分块或 render-unit 层。
4. 不再因为普通段落“看起来像富文本碎片”就强制关闭 rich text 翻译；混合未译、重叠这类问题优先回到 paragraph 分块层定位。

## 为什么不再用 Gatekeeper

Gatekeeper 的视角太晚。它只能比较 preview 的源文和译文，很难知道一个 block 是 TOC、页脚、图表竖排标签、公式周边 token，还是 BabelDOC 本来就应该跳过的稳定文本。后处理补译还会绕过 BabelDOC 的 paragraph composition 和 typesetting 决策，容易修好漏译却破坏原本排版不错的地方。

新方案把判断前移到 IR 阶段，并保留 BabelDOC 原始 typesetting。没有把握的对象只分类，不改写。

## 页脚和页眉

页脚/页眉不靠单页位置判断，而是使用全局重复性：

1. 同一 canonical text 出现在多个页面。
2. 大多数实例位于页面顶部、底部或左右边缘。
3. 排除页码和明显技术 token。
4. 只在翻译后 composition 可安全复制时做一致化。

这避免了把正文首行、图注或表格边缘内容误判成页脚。

## TOC

TOC 当前走 `translate_title_preserve_locator`。hook 会把一行 TOC 拆成 title、leader、page number 三段，只把 title 发给翻译模型，再按源行的页码列宽重新生成 dot leader，把 page number 拼回 translated paragraph。同一页同一列的 TOC 会共用一个页码锚点，避免每行各自估算导致页码列轻微抖动。

后续安全推进路径：

1. 从 sidecar 中收集 `toc_entry`。
2. 解析 title、leader、page number 三段结构。
3. 翻译 title，不翻译 leader 和 page number。
4. 在 typesetting 前重建 TOC composition，保留原有右侧页码锚点。
5. 后续如果 leader 仍因字体宽度漂移，再升级到按右侧页码锚点重排，而不是回到整行翻译。

## 多行段落

BabelDOC 有时会把视觉上的多行脚注、页眉或变更记录合成一个 paragraph。LLM 翻译这类 paragraph 时可能把源文本里的换行吞掉；即使 hook 把 `\n` 放回 `paragraph.unicode`，BabelDOC 0.6.2 的 typesetting 也会在创建排版单元时跳过换行字符。因此只改译文字符串并不能保证视觉换行生效。

当前 hook 只处理高置信编号段：

1. 源 paragraph 从编号 marker 开始，并包含多个编号 marker，例如 `(1)`、`(2)`、`(3)`。
2. 翻译后先在编号 marker 前恢复逻辑换行。
3. typesetting 前把该 paragraph 拆成多个 paragraph，每个编号项独立排版。
4. 不对普通正文、多行标题或未知结构强拆。


## 图表竖向文字

BabelDOC 默认会跳过 `vertical=True` paragraph；如果强行送进普通 paragraph 翻译，图表坐标轴常会被拆成单字符堆叠。当前 hook 对 BabelDOC vertical paragraph 和高窄多行块使用 `vertical_label/preserve`，优先避免破坏原图表。

另一个问题发生在更晚的 render backend：某些 PDF 的旋转文字进入最终 `render_units` 后会变成窄高连续字形列。针对这类对象，hook 在 `PDFCreater.create_render_units_for_page` 里按几何和完整轴标题形态识别候选，先把 CamelCase 原文标准化并单独翻译，再用 BabelDOC 的 typesetting 生成译文字符，最后把这些字符作为一个旋转文本 render unit 输出，避免每个字母被单独摆放。这里不使用固定轴标题词表。

后续安全推进路径：

1. 分类出竖排标签和所在页面/rect。
2. 对文本进行独立翻译，但不交给普通 paragraph typesetting。
3. 在 PDF 输出阶段建立专门的旋转 overlay 或 vertical redraw。
4. 保留原 rect、旋转方向、字体族和字号缩放边界。
5. 只在能够擦除原文且目标文本能在原框内收敛时启用。

## 技术 Token

表格条件、单位和值不走普通语义翻译。hook 会在送入模型前保护变量名、单位和值，例如 `VDD`、`GND`、`ISINK`、`10 mA`、`0.3V`、`50Hz`、`8SPS`，译文回来后再恢复原 token。若模型仍把常见单位翻成中文，post-translate 会根据源文出现过的单位做兜底替回，例如 `毫安` -> `mA`、`伏/伏特` -> `V`、`接地` -> `GND`。

## 失败策略

所有 hook 都是 fail-open：无法分类、无法复制 composition、无法确定结构时，保留 BabelDOC 原行为。sidecar 是诊断和后续策略输入，不要求每个 role 都立即产生可见修改。

这套路线的目标不是一次性覆盖所有 PDF 异常，而是把可证明的高置信策略逐步前移到 BabelDOC 内部阶段，减少后处理补丁之间互相打架的概率。

## Per-rule 开关层（HookPolicy）

收敛方案（`docs/pdf-layout-convergence-plan.md`）要求把结构规则改成可开关、可 observe、可解释。`doc_translator.hook_policy.HookPolicy` 是唯一的开关读取点：它从 `PDF_HOOK_*` 环境变量解析每条规则的 mode，`babeldoc_runner.py` 在构造 `BabeldocHookContext` 时调用一次 `HookPolicy.from_env()` 注入，规则内部只问 `hook_policy.is_apply/is_observe/is_off`，不再各自读环境变量。

mode 取值：

| mode | 行为 |
| --- | --- |
| `apply` | 跑规则并改写文档（旧行为） |
| `observe` | 跑 dry-run plan，把本来会做的 action 写进 sidecar（`decision=observed`），但**不改** paragraph 边界、composition 或 box |
| `off` | 整条跳过，不跑 plan，不写 sidecar（仅用于已知坏规则/废弃规则/临时故障隔离，不作常规调参） |

每条规则按风险分 kind：

| kind | 默认 mode | 例子 |
| --- | --- | --- |
| `text_only` | `apply` | 技术 token 保护、TOC title 翻译、源文换行恢复 |
| `style_only` | `apply`（scoped） | 字体 trait 归一、竖排 passthrough 恢复、正文字号归一 |
| `structure` | `observe`，窄域白名单除外 | 多行切分、同行合并、重复块删除、编号列表切分、跨页页眉页脚同步 |
| `render` | `apply` | 竖排轴标签重绘 |

`structure` 默认 `observe` 是 M1b 的止血本意：普通正文/双栏正文/多行 prose block 回到 BabelDOC 原生排版路径，只把"本来会做的改写"写进 sidecar，不再直接破坏 paragraph。窄域白名单规则可以默认 `apply`，但必须有明确 layout guard 和固定回归样本；例如 `merge_same_line_fragment_bridge` 只接回同 baseline 的断词、小数和内联标点碎片，`split_wrapped_same_line_tail` 只修复“同列行尾碎片被粘到下一视觉行 paragraph”的抽取形态。需要临时回退到旧行为时设 `PDF_HOOK_STRUCTURE_*=apply`。

环境变量名见 `.env.example`，例如 `PDF_HOOK_STRUCTURE_MERGE_SAME_LINE_FRAGMENT_BRIDGE=apply|observe|off` 或 `PDF_HOOK_STRUCTURE_MERGE_SAME_LINE=observe|apply|off`。

### plan / apply 拆分

每条 `structure` 规则都拆成两段：

1. `_plan_*`：只读，返回 plan items 列表（`kind`、`reason`、`role`、涉及的 paragraph_id 等），不改文档。
2. `_apply_*`：真正改写 `page.pdf_paragraph`、paragraph unicode/composition/box。

公开方法按 policy 分派：`off` 直接 return；`observe` 调 `_emit_observed_plan` 把 plan 写成 `decision=observed` 的 sidecar 事件，return 不改写；`apply` 调 `_apply_*` 并记 `decision=applied`。`split_numbered_lists_before_typesetting` 在 `Typesetting` 阶段（翻译后）执行，同样走 policy，不绕过 layout guard（方案 §现状校正-2）。

多行正文块保护：`normalize_fragmented` 的 plan 对真实多行 prose block 标 `reason=multiline_body_block`，apply 时只对 `reason=fallback_line_visual_split` 的项执行切分；`merge_same_line` 的 `_should_merge_same_line_fragments` 已有 `multi_line_blocks` reject，observe 模式同样记 `decision=rejected`。

## Sidecar schema v2

`write_sidecar` 输出 `schema_version=2`，在 v1 基础上增加 `hook_policy` 段，并统一 `applied_events` 每条事件的字段：

```json
{
  "schema_version": 2,
  "hook_policy": { "kind_defaults": {...}, "modes": {...}, "by_kind": {...}, "env_var_names": {...} },
  "applied_events": [
    {
      "action": "merge_same_line_fragments_before_translation",
      "rule_key": "merge_same_line",
      "rule_kind": "structure",
      "decision": "observed",
      "plan_total": 3,
      "plan_by_kind": {"merge": 3},
      "role_counts": {"body": 6},
      "samples": [{"kind": "merge", "role": "body", "reason": "ok", ...}]
    }
  ]
}
```

`decision` 取值 `applied | observed | rejected | skipped`。`observe` 模式真正改写才写 `applied`，dry-run 写 `observed`；规则内部拒绝（如 `multi_line_blocks`）写 `rejected`。这样看到坏页时可以直接按 `decision` 和 `reason` 定位是哪条规则的哪类判定，不用重新猜。

## 页面 layout guard（M2 第一切片）

`classify_document` 现在会在任何结构规则执行前构建轻量页面布局摘要，并写入 sidecar / structure snapshot：

- `body_column:left/right/single`：由同页正文段落的 x 分布识别；信心不足时不强分栏。
- `edge`：页眉页脚、边栏、竖排标签、重复边缘文本。
- `table` / `figure`：来自现有 `layout_label` 的窄信号。
- `unknown`：缺 rect、非正文、或不落在可信 column 内。

结构规则的 plan item 会带 `guard_decision`、`guard_reason` 以及左右/目标 region 和 column 字段。`observe` 模式只记录这些判断；`apply` 模式只执行 `guard_decision=allowed` 的 plan item，并把 guard 拒绝项作为 `decision=rejected` 写入 sidecar。当前已接入 `merge_same_line`、`remove_subsumed`、`collapse_overlap`、`normalize_fragmented` 和 `split_numbered_lists`。

pipeline 顺序也相应前移：`StylesAndFormulas.process` 后先 `classify_document` / build layout summary，再进入结构规则；结构规则真正改写后仍会重分类，保证后续规则看到最新结构。

## 单 PDF 回归 runner

`tests/regression/run_single_pdf.py` 复用 `translate_pdf_with_babeldoc_library`（不走 HTTP API），对一个 PDF 产出：

- `mono.pdf`、`doc_translator_ir.json`、`structure_before.json`、`structure_after.json`
- `pages/page-NNN.png`（PyMuPDF 渲染，用于人工对照）
- `metrics.json`（v1 指标）
- `baseline.diff.json`（与 `tests/regression/baselines/<name>.metrics.json` 的回归 diff）

用法：

```bash
py -3.11 -m tests.regression.run_single_pdf \
  --input tests/regression/inputs/translate.cli.font.unknown.pdf \
  --output-dir tests/regression/runs/font-unknown \
  --source-language en --target-language zh-CN \
  --model-base-url "$MODEL_BASE_URL" --model-api-key "$MODEL_API_KEY" \
  --model-name "$MODEL_NAME" \
  --update-baseline   # 首次或策略调整后刷新基线
```

未传 `--name` 时，runner 使用 `--output-dir` 的目录名作为样本名；上面的命令会匹配 `tests/regression/baselines/font-unknown.metrics.json`。

metrics v1 覆盖：paragraph 数变化、structure action 按 decision/role 统计、layout guard decision/reason 统计、多行正文保护命中、字号归一命中、页面文本覆盖率、overflow（bbox 代理 v1）、hook_policy 摘要。硬门禁只拦恶化方向：`body_role_structure_decisions.applied` 增加、`overflow_paragraphs.total` 增加；改善方向（rejected/observed 增加）只写 diff 不 fail。基线文件入版本化目录 `tests/regression/baselines/`，运行输出 `tests/regression/runs/` 被 gitignore。

固定样本集在 `tests/regression/inputs/`：`translate.cli.font.unknown.pdf`（字体 fallback、正文重排）、`translate.cli.text.with.figure.pdf`（双栏、图文混排）、`lm555-p1.pdf`（图表、表格、页眉页脚、技术 token）、`ADS1113-p01-p02.pdf`（TI datasheet 前两页、多栏、技术单位、页脚）、`ADS1113-p03-p04.pdf`（通用 wrapped same-line tail 抽取粘连）、`ADS1113-p11-p12.pdf`（电路图 fallback_line 短标注抽取损坏）、`toc-dot-leaders.pdf`（TOC 点导引和页码保留）、`scanned-ocr-smoke.pdf`（image-only OCR workaround）。

## 批量回归门禁（M3b）

`tests/regression/run_batch.py` 串行运行固定样本集并写出 `tests/regression/runs/batch.summary.json`。默认会调用单 PDF runner 重新翻译每个样本；本地只想检查已有 run 产物时使用 `--metrics-only`。

```bash
py -3.11 -m tests.regression.run_batch \
  --model-base-url "$MODEL_BASE_URL" --model-api-key "$MODEL_API_KEY" \
  --model-name "$MODEL_NAME"
```

快速验收已有输出：

```bash
py -3.11 -m tests.regression.run_batch --metrics-only
```

可用 `--sample font-unknown --sample text-with-figure` 跑子集。批量模式要求 baseline 存在；缺 baseline、任一样本硬门禁失败，命令都会返回非 0。

当前硬门禁包括：

- 普通正文 `decision=applied` 的 structure action 相对 baseline 增加。
- overflow 总数相对 baseline 增加。
- `cross_column`、`unknown_region`、`non_body_region`、`ordinary_body_split`、`multiline_body_block` 等 layout guard reject reason 出现 `allowed` 增量。

## 规则清理（M4）

计划中标记为未接线的四条 fallback_line 结构规则已删除：

- `split_fallback_line_technical_token_runs_before_translation`
- `merge_fallback_line_underscore_compounds_before_translation`
- `normalize_fallback_line_texts_before_translation`
- `merge_fallback_line_fragments_before_translation`

这些规则没有 runner 调用点，也没有进入 `HookPolicy` registry；保留它们会让后续误接线时绕过当前 policy/guard 体系。删除范围只覆盖未接线公开规则和仅服务于它们的私有 helper；仍被活路径使用的 fallback_line 分类、技术标签重建和 underscore band 保护 helper 保留。

M4 同时完成了三组活路径拆分：

- `normalize_fragmented` 拆为 `observe_multiline_body_blocks` 与 `split_compact_fallback_labels` 两条内部计划路径。
- `merge_same_line` 的候选链、plan item 和 reject sample 构造拆为小 helper，保留原 action/reason 字段。
- `collapse_overlap` 的 overlap cluster 构造由 plan/apply 共享，并修复 plan 阶段潜在未定义变量路径。

第一版 layout guard 的列识别、区域置信度和容差阈值也已提为命名常量。M4 清理不改变现有 baseline 口径，后续规则变化必须先扩回归样本，再评估是否需要调阈值。

图内 `fallback_line` 短标注新增了分类保护：当同页同 `xobj_id` 内已有足够多电路/技术 pin 标注锚点时，只把位于该图形簇内、短小且呈现明显抽取损坏或紧凑技术特征的标签标为 `preserved_token`。这类源文本层可能已经是 `1 F00n`、`I C-Capabl Mastere`、`Serial AR/U T`，继续翻译会制造红框重排；保留原始绘制比猜测还原更安全。普通可译说明（如器件限定括注）仍走翻译路径。
