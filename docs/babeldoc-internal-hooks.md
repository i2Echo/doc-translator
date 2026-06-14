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

## 同行碎片合并

另一类重叠不是换行丢失，而是同一视觉行被 BabelDOC 上游切成多个 paragraph。例如一个普通句子可能被拆成 `All specific`、`ations ... note`、`d.` 三段；翻译后每段各自 typeset，就会出现源文残片和译文挤在同一行、甚至互相覆盖。

当前 hook 在翻译前做通用合并：

1. 只看相邻 paragraph，且两者必须位于同一 baseline、垂直重叠充分、水平间隙很小。
2. 排除 TOC、竖排标签、重复页眉页脚和页面边缘对象。
3. 文本必须像 prose 或断词边界，纯数字、页码和符号不合并。
4. 合并后 union 原 box、拼接 composition，并重新建立 role。

这一步不依赖具体 PDF 的词汇，只修复结构切分错误；普通段落仍保留 BabelDOC 的 rich text 翻译路径。

## 图表竖向文字

BabelDOC 默认会跳过 `vertical=True` paragraph；如果强行送进普通 paragraph 翻译，图表坐标轴常会被拆成单字符堆叠。当前 hook 对 BabelDOC vertical paragraph 和高窄多行块使用 `vertical_label/preserve`，优先避免破坏原图表。

另一个问题发生在更晚的 render backend：某些 PDF 的旋转文字不是 paragraph，而是 `page.pdf_character`；它们会以窄高连续字形列出现，但 `vertical` 标记丢失。针对这类对象，hook 在 `PDFCreater.create_render_units_for_page` 前只按几何和字符序列恢复旋转标记：窄高、字符连续、非纯数字/符号、包含足够字母或单位。这里不使用固定轴标题词表。

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
