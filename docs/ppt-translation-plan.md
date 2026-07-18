# PPT/PPTX 翻译调用路径记录

## 目标

在不新增 worker、存储体系或上传接口的前提下，让现有异步任务链路支持演示文稿翻译：

- 上传、任务、审计、结果文件、预览 sidecar 和下载继续复用现有 `JobFile`/`TranslationJob` 模型。
- worker 仍从同一队列取任务，只在 `run_translation_job` 内按扩展名分发到独立演示文稿翻译函数。
- `.pptx` 保持为 PPTX 输出；`.ppt` 在 worker 容器中通过 LibreOffice headless 转成 `.pptx` 后翻译，最终下载 `.pptx`。

## 支持范围

本期支持：

- `.pptx` Office Open XML 演示文稿。
- `.ppt` 二进制演示文稿的导入转换，依赖 Docker 镜像中的 `libreoffice-impress`。
- `ppt/slides/slide*.xml` 和 `ppt/notesSlides/notesSlide*.xml` 中 DrawingML 段落文本。
- 在线预览、编辑、保存和下载译文 PPTX，且浏览器预览应尽量保留幻灯片视觉版式，而不是退化为纯文本卡片。

明确不支持：

- 将译文再转回旧二进制 `.ppt`。
- SmartArt、图表内部数据、嵌入对象和图片 OCR 文本。
- 将浏览器预览降级为纯文本卡片。

## 实现

- `apps/api/doc_translator/storage.py` 增加 `.ppt`/`.pptx` 扩展名白名单，仍使用现有 uploads/results 目录。
- `apps/api/doc_translator/pptx_translator.py` 负责 PPT 转换、PPTX 文本抽取、翻译写回和包完整性校验。
- `apps/api/doc_translator/translation.py` 在同一 worker 调用路径内分发 `.ppt`/`.pptx`，不新增队列或 worker 进程。
- `apps/api/doc_translator/preview.py` 为 `document_kind="pptx"` 生成预览 sidecar，并在保存编辑后更新真实 PPTX 文件。
- `apps/web/src/views/WorkspaceView.vue` 接受 PPT/PPTX 上传；`PreviewView.vue` 负责按幻灯片版式展示预览，并复用现有编辑、保存和下载交互。

## 验收建议

1. 在 Docker 后端镜像中上传 `.pptx`，确认任务完成、可预览编辑、保存后下载的 PPTX 能打开。
2. 上传 `.ppt`，确认任务事件包含转换阶段，最终输出文件名为 `*-<lang>.pptx`。
3. 在浏览器预览中抽查典型 PPT 样本，确认幻灯片轮廓、图片、形状和文本框位置没有退化成纯文本列表。
4. 用 PowerPoint 或 LibreOffice Impress 打开输出文件，检查幻灯片、备注、图片和布局对象仍存在。
5. 对包含 SmartArt/图表的样本做人工复核，确认这类对象内文本按“不支持范围”保留原样。
