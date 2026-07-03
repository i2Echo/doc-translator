# Doc Translator 代码审查报告

- **审查日期**: 2026-07-02
- **审查范围**: `apps/api`（Python 后端，37 个源文件）、`apps/worker`、`apps/web/src`（Vue 3 前端，12 个源文件）。`infra/`、`docker-compose.yml`、`nginx.conf` 等部署/边缘层**未逐行审**，相关风险集中见文末 [附录：Deployment / Edge hardening](#附录deployment--edge-hardening)。
- **审查分支**: `feat-optimize`
- **审查目标**: 基于 BabelDOC 的通用 PDF 翻译器（面向工业领域，私有化部署 MVP），查找 Bug、安全、健壮性、性能与可维护性问题

## 概览

本次审查共发现 **约 120 项问题**，按严重级别分布如下：

| 级别 | 数量 | 说明 |
|------|------|------|
| Critical | 5 | 部署即可被接管 / 单段坏文本导致整单失败 / 存储型 XSS 提权 |
| High | 12 | 数据一致性、并发崩溃、密钥泄露、鉴权薄弱 |
| Medium | 40+ | 错误处理、性能、SSRF、队列一致性、前端未处理拒绝 |
| Low | 60+ | 代码质量、可访问性、魔法数字、重复代码 |

### 最应优先修复（Top 8）

1. **不安全的启动默认值**（JWT secret=`change-me`、admin 密码=`change-this-password`，无校验）— 直接导致系统被接管。`core/config.py:9`、`bootstrap.py:18-25`
2. **存储型 XSS 提权**：上传 `.pdf` 文件但 `Content-Type` 伪造为 `text/html`，且下载接口用 `inline` 且无 `nosniff`，普通用户可攻击管理员。`storage.py:68`、`api/main.py:504-509`
3. **BabelDOC hooks 全程无 fail-open 异常保护**（设计文档承诺但未实现），任意一个异常段落都会让整份 PDF 任务崩溃。`babeldoc_hooks.py`（全文件）
4. **FAILED 任务仍保留已提交的输出文件**，数据库状态与磁盘不一致。`translation.py:944-1012`
5. **Worker 崩溃后任务永久卡在 running**，无租约/心跳/定期孤儿清理。`worker_service.py:54`
6. **`fitz.Font` 经 `lru_cache` 跨 FastAPI 线程共享**，并发度量查询存在竞争。`preview.py:769-775`
7. **`model_api_key` 明文回传前端**，`model_base_url` 无 SSRF 校验。`schemas.py:60`、`api/main.py:320-338`
8. **前端无 401/Token 过期处理 + 轮询不停**，过期后静默失效、控制台刷错。`store.js:115-124`

---

## Critical（5）

### C1 — 不安全的启动默认值 + bootstrap 每次补后门账号，可被直接接管
- **位置**: `apps/api/doc_translator/core/config.py:9`、`apps/api/doc_translator/bootstrap.py:16-26`
- **类别**: Security
- **描述**: 两个叠加缺陷：
  1. `app_secret_key` 默认 `"change-me"`、`admin_password` 默认 `"change-this-password"`，启动时无任何校验。若运维复制了 `.env.example` 后忘记修改，攻击者可用已知 secret 伪造任意 HS256 JWT 冒充任何用户/管理员。
  2. **bootstrap 的补建条件远比"没有 admin"更宽**：`bootstrap_defaults` 只 `filter(User.email == settings.admin_email.lower())`（`bootstrap.py:16`），仅判断"该邮箱的用户是否存在"，**不**判断系统里是否已有任意 admin。因此只要默认 `admin@example.com` 这个邮箱在库里不存在，**每次带默认值启动都会补一个用默认密码的 admin 账号**——即使系统本来已有别的活跃 admin、即使这不是首次启动。风险不是"首启忘改配置"，而是"任何一次带着默认 `ADMIN_EMAIL`/`ADMIN_PASSWORD` 的启动都可能开后门"。叠加第 1 点，攻击者可在任意时机用已知默认邮箱+密码登录该后门账号，未授权完全接管。
- **影响面（上调）**: 单次启动即可落地后门；不依赖"首次部署"窗口；任何重启/扩容/迁移/CI 重建若环境变量未正确注入即触发。
- **建议**: 生产环境（`app_env == "production"`）下，`lifespan`/`bootstrap_defaults` 检测到 secret 仍是已知弱默认值或低于最小长度、`admin_password` 仍是默认值时**拒绝启动**；强制通过环境变量提供。`bootstrap_defaults` 改为仅当系统**没有任何活跃 admin**时才补建，并要求补建使用的密码非默认值（否则报警并跳过）；记录 `auth.bootstrap_admin_created` 审计事件。

### C2 — 存储型 XSS 提权（伪造 Content-Type + inline + 无 nosniff）
- **位置**: `apps/api/doc_translator/storage.py:68`、`apps/api/doc_translator/api/main.py:504-509`
- **类别**: Security
- **描述**: 存储的 `content_type` 取自客户端 `UploadFile.content_type`，优先于扩展名派生值（`file.content_type or SUPPORTED_EXTENSIONS[extension]`）。`read_job_document` 随后以 `media_type=job_file.content_type` + `Content-Disposition: inline` 返回文件，且无 `X-Content-Type-Options: nosniff`。普通用户可上传名为 `x.pdf`、内容为 HTML/`<script>`、`Content-Type: text/html` 的文件（扩展名校验通过）。当管理员在浏览器打开该任务的源文件/译文时，浏览器以 inline 渲染 HTML → 在管理员会话中执行脚本。伪造的 content-type 还会随译文输出传播（`translation.py:948` 复制 `input_file.content_type`）。
- **建议**: `content_type` 一律由校验过的扩展名派生，忽略客户端头；文件响应加 `X-Content-Type-Options: nosniff`，对用户上传文件优先 `attachment` 而非 `inline`。

### C3 — BabelDOC hooks 全程无 fail-open 异常保护
- **位置**: `apps/api/doc_translator/babeldoc_hooks.py:298-1330`（所有 hook 入口）；`babeldoc_runner.py:189-302`（调用方）
- **类别**: Error handling / Robustness
- **描述**: 4957 行内**零** `try/except`。设计文档（`docs/babeldoc-internal-hooks.md` 第 124 行）声明"所有 hook 都是 fail-open：无法分类…保留 BabelDOC 原行为"，但**未实现**。runner 也只在最外层事件循环捕获并重新抛出（取消整单）。工业 PDF 异构文本多，单个异常段落（`pdf_style=None`、非有限 rect、意外 `None` 文本）即可让整份任务中止。
- **建议**: 每个 hook 入口方法体包裹 try/except，记录日志并返回透传结果（`return text` / `return render_units` / `return None`）。至少覆盖 `should_skip_translation`、`translation_text_override`、`translated_text_override`、`classify_document`、`replace_axis_label_render_units`、`record_translation` 及各 `normalize_*_before_translation`。

### C4 — `_AxisLabelRenderUnit.render` 裸属性访问，可抛 AttributeError 破坏输出
- **位置**: `apps/api/doc_translator/babeldoc_hooks.py:2180-2252`
- **类别**: Error handling / Robustness
- **描述**: `render()` 用裸属性访问：`first.box.x2`、`first.pdf_style.font_size`、`char.pdf_style.graphic_state` 等。文件其余部分防御性地用 `getattr(...)` 与 `_box_rect(...)`，此方法没有。若任一 char 的 `pdf_style=None` 或 `box=None`（`_can_render_axis_label_as_group` 只校验 `font_id`/`font_size` 非空，未校验 `box`/`graphic_state`），`render()` 抛错。该方法由 BabelDOC PDF 后端调用，异常会损坏输出 PDF 或崩溃任务。
- **建议**: 访问 `box`/`pdf_style`/`graphic_state` 前用 getattr/None 守卫，缺字段的 char 跳过。

### C5 — 渲染热路径中 `translator.translate()` 未受保护
- **位置**: `apps/api/doc_translator/babeldoc_hooks.py:1338`、`2460`
- **类别**: Error handling
- **描述**: `_translate_axis_label_text` 与 `_retry_translate_axis_label_body_only` 调用 `translator.translate(..., ignore_cache=True)` 无 try/except。网络错误/限流/鉴权失败/畸形响应都会沿 `replace_axis_label_render_units` → `create_render_units_for_page` 上抛中止 PDF。`if not translated: translated = source_text`（1346）只处理空字符串，不处理异常。
- **建议**: 包裹每次 `translate()` 调用；异常时记录日志并回退到 `source_text`。

---

## High（12）

### H1 — FAILED 任务仍保留已提交的输出文件，且旧译文经 /documents/translated 持续暴露
- **位置**: `apps/api/doc_translator/translation.py:944-978`（成功路径）、`992-1012`（失败路径）；API 影响面 `apps/api/doc_translator/api/main.py:127-136`（`load_job_document`）、`438-465`（`retry_job`）
- **类别**: Bug / Error handling / Security
- **描述**: 两个叠加缺陷：
  1. **worker 侧**：`run_translation_job` 中 output `JobFile` 先 `session.add`+`flush`（954-955）并赋值 `job.output_file_id`（957），之后才 `load_or_create_preview`。PDF 任务预览失败会 `raise`（965-966），落入外层 `except`，标记 FAILED 并 `commit`（995-1012）。该 commit 同时持久化了 FAILED 状态与已 flush 的 `output_file` 记录及 `output_file_id`。结果：DB 标记 FAILED 的任务仍指向磁盘上的成品 PDF，审计记录失败而译文存在，输出文件成为孤儿。
  2. **API 侧（影响面放大）**：`load_job_document("translated")`（`api/main.py:130-135`）**只校验 `output_file` 是否为 None 与 `deleted_at`，完全不校验 `job.status`**。因此上述 FAILED 任务（`output_file_id` 仍非空、`deleted_at` 为空）可直接通过 `GET /api/v1/jobs/{id}/documents/translated` 取到译文——把"失败"的内容当成成品下发。更严重的是 `retry_job`（`438-465`）重置 status/progress/error_message/cancel_requested/started_at/completed_at，却**不清 `output_file_id`、不删旧 output 文件**；于是**重试进行中（QUEUED）的任务**也仍挂着旧译文，`/documents/translated` 持续暴露上一次（可能失败/可能被取消/可能是旧版本）的产物，直到新一次翻译成功覆盖 `output_file_id`。`download_job`（476 行）有 `status != COMPLETED` 守卫，但 `/documents/translated` 与 `read_job_preview`（经 `ensure_job_has_previewable_output` 只查 COMPLETED，但此处仅讨论 documents 路径）绕过了该守卫。
- **建议**: worker 侧把 `session.add(output_file)`/`flush()`/`job.output_file_id=` 延后到预览成功之后，或预览失败时先 `rollback()` 再标记 FAILED，或 PDF 预览失败不 re-raise 改 COMPLETED + 警告（DOCX 已这样做 967-968）。API 侧 `load_job_document("translated")` 增补 `job.status == COMPLETED` 守卫，非 COMPLETED 返 409/404；`retry_job` 在置 QUEUED 时清空 `job.output_file_id`（并可选删除/隔离旧 output 文件），避免重试期间旧译文暴露。

### H2 — `fitz.Font` 经 `lru_cache` 跨线程共享
- **位置**: `apps/api/doc_translator/preview.py:769-775`
- **类别**: Concurrency
- **证据级别**: 代码路径**已确认**；"PyMuPDF 字体对象非线程安全"为**高风险推断**（未在本环境取到上游文档佐证，见下方）
- **描述**: `_pdf_metrics_font` 用 `@lru_cache(maxsize=16)`，返回的 `fitz.Font` 实例为模块全局。`update_preview`/`_apply_pdf_preview_updates` 从 FastAPI **同步**端点 `save_job_preview`（`api/main.py:545`）经 Starlette threadpool 调用 `_pdf_text_width` → `_pdf_metrics_font`（`preview.py:2669,2698-2702`），多请求线程可拿到**同一缓存 `fitz.Font`** 并发 `.text_length()`。
- **已确认事实**: (1) 缓存为模块全局；(2) 调用方在 Starlette threadpool（同步端点）并发执行；(3) 缓存命中即返回同一对象。这三点由代码直接证实。
- **高风险推断**: PyMuPDF/MuPDF 字体对象是否线程安全——本环境无法联网取上游文档/issue 佐证（WebFetch 被沙箱拦截），PyMuPDF 官方文档无明确"Font 线程安全"承诺。鉴于 MuPDF/FreeType 内部 `FT_Library`/`FT_Face` 状态非天然线程安全，按保守原则判为高风险。
- **复现步骤**: 启动 API；用同一管理员账号并发发起多个 `PUT /api/v1/jobs/{id}/preview`（不同 job，PDF 含相同字体）；观察偶发段错误/度量返回 NaN/进程崩溃，或加 `threading.Lock` 包裹 `.text_length()` 后现象消失即佐证。
- **建议**: 去掉 `lru_cache` 每次新建 `fitz.Font`（已加载 buffer 廉价），或 thread-local 缓存，或加锁，或只缓存不可变 buffer 而每线程建 `fitz.Font`。若团队确认该版本 PyMuPDF 字体对象线程安全，可降级并加注释引用依据。

### H3 — 服务器内部路径泄露进错误消息
- **位置**: `apps/api/doc_translator/translation.py:808-813`
- **类别**: Security（信息泄露）
- **描述**: `RuntimeError` 消息嵌入完整服务器端 `input_path`（如 `/var/data/uploads/<uuid>.pdf`），存入 `job.error_message` 与 `JobEvent.details`，可经任务状态接口返回客户端，暴露内部目录结构。
- **建议**: 面向用户用通用消息（"输入文件不可用或不完整"），路径仅写入服务端日志。

### H4 — `model_api_key` 明文回传前端；`SettingsUpdate` 强制全量
- **位置**: `apps/api/doc_translator/schemas.py:60`、`apps/api/doc_translator/settings_service.py:85`、`apps/api/doc_translator/api/main.py:295-317`
- **类别**: Security
- **描述**: `GET /api/v1/settings` 与 `PUT /api/v1/settings` 响应返回完整原始 `model_api_key`。因 `SettingsUpdate` 要求全字段（非 partial），前端必须回传 key，故被暴露。key 随后驻留浏览器内存/localStorage、代理日志。虽仅管理员可见，但它是外部模型供应商的凭证。
- **建议**: `SettingsRead` 中掩码 key（仅显示末 4 位）；`SettingsUpdate` 改为 partial（字段 Optional），`None`/空视为"不变"，前端无需回传真实 key。

### H5 — `model_base_url` 无 SSRF 校验
- **位置**: `apps/api/doc_translator/api/main.py:320-338`、`schemas.py:74-75,84-88`、`settings_service.py:74-76`
- **类别**: Security (SSRF)
- **描述**: admin 可配置的 `model_base_url` 为任意字符串，无 scheme/host 校验。`test_model_connection` 向该 URL 发起出站请求（`translation.py:135-136` 拼 `{base_url}/chat/completions`），worker 翻译时也用同一 URL。admin（或窃取 admin token 的攻击者）可指向 `http://169.254.169.254/...`、内部服务、外发主机，`test-model` 沦为探测/请求原语。
- **建议**: 校验 `model_base_url` 为 `http(s)`，拒绝回环/链路本地/私网段与元数据 IP（或显式 allowlist），`update_settings` 同样校验。

### H6 — 登录无限流/无锁定，且可用户枚举
- **位置**: `apps/api/doc_translator/api/main.py:155-183`、`apps/api/doc_translator/auth.py:37-43`
- **类别**: Security
- **描述**: `/api/v1/auth/login` 无限流、无账户锁定、无退避。`authenticate_user` 对"用户不存在"与"密码错误"都返回 `None`，但仅在用户存在时才调用 `verify_password`（bcrypt），响应时序可区分邮箱是否注册 → 用户枚举 + 无限在线爆破。
- **建议**: 加按 IP/邮箱限流（如 `slowapi` 或 Redis 令牌桶）与失败 N 次后临时锁定；对不存在用户执行一次常量时间 dummy bcrypt 以抹平时序。

### H7 — 下载文件名注入响应头（header injection）
- **位置**: `apps/api/doc_translator/api/main.py:504-509`
- **类别**: Security
- **描述**: `Content-Disposition` 用 f-string 从 `job_file.original_name`（用户上传文件名，原样存储 `storage.py:65`）拼接。若文件名含 `"`、`\r`、`\n`，原始值被注入响应头，可造成响应头注入/拆分。不同于 `FileResponse(filename=...)`（Starlette 会编码），此处手工头未转义。
- **建议**: 移除手工 `Content-Disposition`，改用 `FileResponse(filename=...)`（自动编码），或对 `original_name` 净化（去控制字符与 `"`）后再拼接。

### H8 — BabelDOC 全局限流器被每个任务改写（跨任务耦合）
- **位置**: `apps/api/doc_translator/babeldoc_runner.py:49`、`babeldoc_runner.py:96`（`pool_max_workers=qps`）
- **类别**: Concurrency
- **证据级别**: "调用模块全局 setter"为**已确认**；"限流器为模块级全局、跨所有并发任务共享"为**高风险推断**
- **已确认事实**: `from babeldoc.translator.translator import set_translate_rate_limiter` 后 `set_translate_rate_limiter(qps)`（49 行）在 `translate_pdf_with_babeldoc_library` 入口被每任务调用；worker `ThreadPoolExecutor(max_workers=16)`（`worker_service.py:45`）可并发多个任务各自调用该 setter；`pool_max_workers=qps`（96 行）按任务设置并发。setter 名 `set_translate_rate_limiter` 强烈暗示其操作模块级单例，但本环境无法 `import babeldoc`（未装）或联网取 `babeldoc==0.6.2` 源码（`infra/docker/backend.Dockerfile:31` 固定版本）佐证"全局单例"与"BabelDOC 单任务内是否并发翻译段落"。
- **高风险推断**: 若限流器确为模块级全局，则配置的 `qps` 在所有并发任务间合计执行而非每任务，与每任务 `pool_max_workers=qps` 语义矛盾；该 setter 改写也非线程安全。若 BabelDOC 单任务内并发翻译段落，还存在 setter 与并发读的竞争。
- **复现步骤**: 装环境后 `inspect.getsource(babeldoc.translator.translator.set_translate_rate_limiter)` 确认是否操作模块级变量；并行跑 2 个 `translate_pdf_with_babeldoc_library` 并打点统计实际 LLM QPS，看是否合计被 `qps` 封顶。
- **建议**: 先按上述步骤确认语义；明确 QPS 是全局还是每任务。若每任务而 BabelDOC 全局 setter 不支持，需换机制；至少文档说明为全局，且 `qps` 未变时不重复调用。确认后可降级或升级本条。

### H9 — HTTP/OpenAI 客户端从不关闭，连接池无上限
- **位置**: `apps/api/doc_translator/babeldoc_runner.py:58-65`
- **类别**: Robustness / Performance
- **描述**: 每任务新建 `openai.OpenAI(...)` 包裹 `httpx.Client(limits=httpx.Limits(max_connections=None, max_keepalive_connections=None), ...)`，从不显式关闭。`max_connections=None` 即无界池。BabelDOC `pool_max_workers=qps` 并发 LLM 调用，worker 同时跑最多 16 任务，数十个无界池并存可耗尽 socket/端口。
- **建议**: `with`/`try...finally` 包裹，`finally` 中 `client.close()`；设有限 `max_connections`/`max_keepalive_connections`。

### H10 — Worker 崩溃后任务永久卡在 running
- **位置**: `apps/api/doc_translator/worker_service.py:54`（仅启动时恢复）、`66`（关停）、`71-158`
- **类别**: Robustness / Concurrency
- **描述**: `recover_orphaned_jobs` 仅在 `start()` 运行。若单 worker 进程崩溃/OOM，所有 `PARSING/OCR_RUNNING/TRANSLATING/...` 任务永久停留该状态，无其他进程重排，无每任务 TTL/心跳或定期孤儿扫描。优雅关停同理：`executor.shutdown(wait=False, cancel_futures=True)` 取消待执行但不停运行中任务，进行中任务被中途遗弃、DB session 未关、状态停留在中间。工业 24/7 场景任务会静默挂起直到手动重启 worker。
- **建议**: 在 `cleanup_loop` 加定期孤儿扫描，重排 `updated_at` 早于租约阈值的任务；让 `run_translation_job` 写心跳 `updated_at`；优雅关停时等待运行中 future 有限时长或退出前标记为 FAILED/QUEUED。

### H11 — 无整体翻译超时，任务可无限挂起
- **位置**: `apps/api/doc_translator/babeldoc_runner.py:125`（及 `translation.py:905` 调用方）
- **类别**: Robustness
- **描述**: `asyncio.run(_run_babeldoc_translation(...))` 无超时。单请求 httpx 超时覆盖单次 LLM 调用，但整条管线（解析→OCR→翻译→排版）在非 HTTP 调用处（字体子集化、TCP 层不响应的代理、逻辑死锁）可无限阻塞，卡住任务占用 worker 线程。
- **建议**: 包裹整体截止时间（`asyncio.wait_for(...)` 或墙钟看门狗）按页数缩放，超时给出明确错误使任务失败、释放槽位。

### H12 — 翻译术语 `_diagnostic_samples` 去重比较 dataclass 与 dict 永远为假
- **位置**: `apps/api/doc_translator/babeldoc_hooks.py:1444`
- **类别**: Bug
- **描述**: 第二个循环 `if record in samples: continue`，但 `samples` 是 `list[dict]`，`record` 是 `_ParagraphRecord`（`@dataclass(slots=True)`，非 frozen，永不等于 dict）。`record in samples` 恒 `False`，去重守卫无效。已在第一循环匹配 `_is_diagnostic_sample` 的记录若再通过高窄过滤，会在第二循环再次追加，产生重复 sidecar 条目并浪费 80 样本预算。
- **建议**: 用 `set` 跟踪已见 `paragraph_id`，`if record.paragraph_id in seen_ids: continue`。

---

## Medium（主要项，按模块分组）

### 后端 / 翻译管线

- **M1 — TOC 点导引正则把空格也当导引符**：`babeldoc_hooks.py:22` 的 `_TOC_ENTRY_RE` leader 组为 `(?:[.\u00b7\u2026]|\s){4,}`，匹配空格。`_compose_toc_entry`（3271-3280）恒输出 `'.' * leader_width`，对原本用空格对齐的 TOC 静默改成点导引。建议 leader 组仅匹配点/中点/省略号，或保留原导引样式。
- **M2 — `_formula_numeric_bridge_fragment` 返回部分匹配，遗留小数**：`babeldoc_hooks.py:3709-3728`。`r"=\s*{numeric_head}(?=[\.,]\d)"` 的 lookahead 不计入 group(0)，对 `= 1.25` 返回 `'= 1'`，调用方 `replace` 后 `.25` 悬留。建议把小数部分纳入返回 span。
- **M3 — `re.sub` 替换串未转义**：`babeldoc_hooks.py:3576-3580`、`452`。`re.sub(re.escape(placeholder), token, ...)` 中 `token`（技术文本）未转义；若含 `\1`/`\g<...>`/`\` 会触发 `re.error` 或插入垃圾。建议用 lambda：`re.sub(re.escape(placeholder), lambda m: token, ...)` 或 `str.replace`。
- **M4 — hook 共享可变状态多处未加锁**：`babeldoc_hooks.py` 中 `self._lock`（240 行）仅 3 处使用，`applied_events`/`groups`/`records_by_id`/`_protected_tokens` 等写入未同步。若 BabelDOC 单任务内并发翻译段落，存在竞争。建议统一加锁或明确单线程并移除锁。
- **M5 — sidecar/结构快照 IO 无错误处理**：`babeldoc_hooks.py:1382-1405`、`1410-1423`。`write_text`/`mkdir` 未守护，磁盘满/权限错会传播中止任务（sidecar 仅为诊断）。建议 try/except 记录警告并返回 `None`。
- **M6 — `_build_typesetting_fonts` 返回值类型不一致**：`babeldoc_hooks.py:2548-2561`。普通字体 value 为单个 font，xobj 条目 value 为 dict-of-fonts，类型提示 `dict[str|int, Any]` 掩盖。建议拆分结构或明确多态并在消费方处理。
- **M7 — 进度提交失败会杀掉正在进行的翻译**：`translation.py:211-233`、`635-668`。每次进度变更 `session.commit()`，瞬时 DB 错（连接抖动/死锁）会从 BabelDOC 异步循环抛出中止成功中的翻译，未区分"翻译失败"与"写进度失败"。建议进度提交 try/except 记录并继续。
- **M8 — 失败/取消路径的 `record_audit`+`commit` 可能丢失状态更新**：`translation.py:980-1012`。若 `record_audit` 或 commit 自身抛错（DB 刚宕，可能正是原始异常源），任务留在不一致状态且原始异常被掩盖。建议失败路径尽力而为：包裹审计/commit 吞错并记录，保留原始异常。
- **M9 — `split_text` 不切分超大单段**：`translation.py:242-255`。单段长于 `max_chars` 时整段发送，可能超 token 限制被截断。建议按句/长度硬切。
- **M10 — `httpx.post` 在 try 之外，无重试**：`translation.py:164-198`。连接/超时/DNS 错以裸异常抛出而非统一 `RuntimeError`；无 5xx/429/超时退避重试，单次抖动失败整批工业任务。建议移入 try、统一包装、有界退避重试。
- **M11 — OCR/Tesseract 失败未优雅处理**：`translation.py:397-440`、`518-570`。`pytesseract.image_to_data` 无 try/except，未安装/误配/页失败即裸异常失败整单且信息不可操作。建议捕获 `TesseractNotFoundError` 给清晰提示，逐页失败跳过并告警事件。
- **M12 — 预览编辑后 output 文件 size/checksum 未提交**：`preview.py:2669-2670`、`2698-2724`。`_apply_pdf_preview_updates` 改 `job.output_file.size_bytes/checksum` 但不 commit，依赖调用方提交；若未提交则 DB 留旧值，破坏完整性校验。建议在此处 commit 或明确契约。
- **M13 — sidecar 字段访问越界假设**：`preview.py:2559,2602,2563-2564,2567,2218`。`_preview_matches_schema` 未保证每块有 `block_id`/`rect`、每格有 `cell_id`/`rect`；手改/部分损坏 sidecar 会深处 `KeyError` → 500。建议对照显式 schema 校验，缺失返回 400。
- **M14 — 字体文件从 CWD/home 缓存目录注入**：`preview.py:425-436`。缓存根含 `Path.cwd()/"tmp"/"babeldoc-cache"/"fonts"` 与 `Path.home()/".cache"/"babeldoc"/"fonts"`。若攻击者可写 worker CWD 或用户 home（共享/误配部署），可植入恶意字体供 MuPDF 解析嵌入（字体解析历史上有内存损坏漏洞）。建议限定为 admin 配置的 root 拥有目录，丢弃 CWD/home 默认，校验路径在配置根内。
- **M15 — 译文段落替换破坏 run 级格式与超链接**：`translation.py:714-719`。`replace_paragraph_text` 删除所有 `}r`/`}hyperlink` 子节点写单一纯 run，丢失加粗/斜体/颜色/字号/超链接。工业规格表混合格式单元格降质。建议尽量逐 run 替换文本，至少重写超链接显示文本而非删除。
- **M16 — `_cluster_pdf_fragment_groups` 近立方复杂度**：`preview.py:1007-1041`。密集工业 datasheet（引脚表/BOM）每页成百小片段时 O(n³)。建议空间索引或按行/列预分组。
- **M17 — `_sanitize_pdf_preview_edit_text` O(n²) 相似度扫描**：`preview.py:343-392`。每行 ≥8 字符扫描全部已保留行跑 `SequenceMatcher.ratio()`。建议先按长度桶/前缀粗筛，仅对近候选跑 SequenceMatcher。
- **M18 — 字体解析反复未缓存的 stat 调用**：`preview.py:418-436`、`444-505`。每文本块多次 `Path.exists()`，50–100 块即数百 stat/预览。建议按语言 profile 缓存字体文件路径。

### Worker / 队列

- **M19 — 硬编码 executor 大小与可配置并发矛盾**：`worker_service.py:45` vs `167-169`。`ThreadPoolExecutor(max_workers=16)` 硬编码，调度按 DB `max_concurrent_jobs` 限流；设 32 实际只得 16（多余在 executor 排队）。建议按启动时 `max_concurrent_jobs` 设置或文档说明 16 为硬上限。
- **M20 — DB commit 在 Redis 入队之前，Redis 失败致孤儿**：`worker_service.py:141-148`。恢复时先 commit 标记 QUEUED 再 `rpush`，rpush 失败则 DB 有 QUEUED 而 Redis 无，永不被调度直到下次重启。建议先入队后提交或用事务发件箱。
- **M21 — 重复出队被静默丢弃（消息丢失）**：`worker_service.py:172-179`。`blpop` 已弹出，`if job_id in self.futures: continue` 丢弃第二次；若首次失败无副本可重试。建议源头防重复入队，或重复弹出时重新 rpush。
- **M22 — 多 worker 启动竞争重复处理同一任务**：`worker_service.py:71-148`。两 worker 并发启动各自恢复并 rpush 同一可恢复任务，都 blpop 并 `run_translation_job`，重复输出与 LLM 调用。建议恢复用 Redis 逐任务锁协调，或文档强制单 worker。
- **M23 — 失败 future 异常从未检查**：`worker_service.py:184-188`、`translation.py:906`。`_prune_finished` 不调 `future.exception()`；`SessionLocal()` 在 try 之外，DB 连接失败异常被静默吞，任务留原状态无事件无日志。建议 `_prune_finished` 检查并记录 `future.exception()`，`SessionLocal()` 移入 try。
- **M24 — 清理批单文件失败回滚全部已删文件的 DB 标记**：`worker_service.py:213-232`。`unlink` 仅抑制 `FileNotFoundError`，其他 OS 错传播中断循环；`session.commit()` 在循环外，N 号文件失败则前 N-1 文件已物理删除但 `deleted_at`/审计全回滚——磁盘删了 DB 仍说存在。建议逐文件 try/except 提交。
- **M25 — Redis 客户端每次新建从不关闭**：`queueing.py:9-11`、`worker_service.py:163`。`get_redis_client()` 每次新 `redis.Redis.from_url`（新连接池），从不关闭，频繁重连时漏池。建议进程级单例共享池。

### API / 鉴权 / 配置

- **M26 — 上传/重试 commit 后才入队，Redis 失败致孤儿**：`api/main.py:384-385`、`462-463`。`session.commit()` 后 `enqueue_job`，rpush 失败 API 返 500 但任务已持久化为 QUEUED 且队列无。建议入队后提交或发件箱/定期扫描重排。
- **M27 — `list_jobs` 无分页**：`api/main.py:391-401`。`.all()` 返回所有任务（admin 为所有用户）且 `selectinload` 三关系，表增长后无界查询。建议加 `offset`/`limit`（`list_users` 已有）。
- **M28 — admin 可自禁用/自降级，无最后管理员保护**：`api/main.py:259-292`。单管理员可一键 `is_active=False` 或降级，`bootstrap_defaults` 不会恢复，自我锁定无恢复路径。建议禁止最后活跃 admin 被禁用/降级，或禁止自禁用/自降级。
- **M29 — `test_model` 同步阻塞最长 3600s 可耗尽线程池**：`api/main.py:320-338`、`schemas.py:88`。sync `httpx.post` 超时可达 3600s，FastAPI sync 端点默认 40 线程池，数个慢/恶意端点即饿死其他请求。建议测试端点固定短超时（≤10s）。
- **M30 — `read_job_preview` 把 `str(exc)` 直接回客户端**：`api/main.py:540-541`。500 detail 嵌 `f"Could not prepare preview: {exc}"`，泄露内部异常文本/路径。建议服务端记全量、客户端返通用消息。
- **M31 — JWT 12h 有效无刷新无吊销**：`core/config.py:10`、`auth.py:26-34`。无 refresh、无 `jti`/`iat`、无服务端吊销；改密/改角色不失效旧 token，被盗 token 最长 12h 可用。建议缩短默认（15–60min），加 `iat`/`jti` + 用户 token 版本号（改密时 bump）。
- **M32 — `local_storage_path` 无校验**：`schemas.py:71-72`。admin 可设任意路径作存储根，`storage.py` 直接在其下建目录写文件。建议校验在允许根内，`storage_mode` 约束为枚举。
- **M33 — 源文件过期路径处理不一致（source 分支不看 `deleted_at`）**：`api/main.py:127-136`（`load_job_document`）、`worker_service.py:207-224`（清理）。`load_job_document` 的 `translated` 分支对 `deleted_at` 返 410，但 `source` 分支（128-129）直接 `return job.input_file` 不查 `deleted_at`。而 retention 清理对 input 与 output 一视同仁地删物理文件并打 `deleted_at`（`worker_service.py:213-224`）。结果：源文件过期后该接口走到 `FileResponse(path=job_file.storage_path)` → 物理文件已删 → `FileNotFoundError` → 500，而非与 translated 一致的 410/Gone；客户端也无法据此判断"源文件已过期"还是"服务器出错"。建议 source 分支同样校验 `job.input_file.deleted_at is not None` 返 410。

### 前端

- **M34 — AppSelect 每实例 id 重复**：`components/AppSelect.vue:4,46`。`let selectId = 0` 在 `<script setup>` 内为每实例变量，所有实例都算出 `listboxId="app-select-1"`，重复 DOM id，`aria-controls` 解析到首个元素，多 select 场景 a11y/关联失效。建议移到模块级 `<script>` 或用 `useId()`/`crypto.randomUUID()`。
- **M35 — Token 存 localStorage，XSS 即泄露**：`store.js:19,88-95`。bearer 在 localStorage，任意 JS 可读，未来任一依赖 XSS 即窃取。建议改 HttpOnly/SameSite/Secure cookie；不可避免则用 `sessionStorage` + 严格 CSP。
- **M36 — 无 401/Token 过期处理 + 轮询不停**：`store.js:115-124,380-386`。过期后 15s 轮询持续 401，回调仅 `console.error` 不停轮询/登出/提示，`isAuthenticated` 仍真，任务列表静默过期。建议 `apiRequest` 集中 401 处理：登出/清会话/停轮询并提示会话过期。
- **M37 — 登录 `refreshAll` 失败留半登录态**：`store.js:366-368` + `LoginView.vue:12-21`。`login()` 先设 `state.user`/token 再 `await refreshAll()`，仅 `finally` 无 catch；refreshAll 抛错时已设 user → `isAuthenticated` 真 → 卸载 LoginView，但错误写入不再显示的 `state.messages.login`，呈现空任务列表半登录态。建议 refreshAll 失败回滚 user/token 或视为非致命。
- **M38 — 无导航守卫，仅靠 `App.vue` 条件渲染**：`router.js:1-29`。无 `beforeEach`，重载 `/admin/...` 时 `state.user` 仍 null，watch 不触发，非 admin 留在 `/admin`；无 404 兜底。建议加 `beforeEach` 鉴权 + admin 守卫 + catch-all 路由。
- **M39 — 多处异步操作无 try/catch 无 disabled 态**：`WorkspaceView.vue:399,413,427,474,477`、`AdminView.vue:341,347`、`PreviewView.vue:786,794`、`App.vue:74`、`WorkspaceView.vue:249`。`cancelJob`/`retryJob`/`downloadJob`/`toggleUserState`/`savePreview`/`refreshAll` 在模板直接调用无 await/catch，无 `pending.*` → 双击重复调用、失败成未处理拒绝无反馈。建议每调用点 try/catch 写消息 + pending 标志绑 `:disabled`。
- **M40 — `refreshAll` all-or-nothing**：`store.js:395-405,433-435`。admin 用 `Promise.all([jobs,settings,users,storage,audit])`，任一失败整 reject 且 `state.jobs` 未更新。建议 `Promise.allSettled` 或拆分 admin 获取与 jobs。
- **M41 — PreviewView async watcher/onUnmounted 未处理**：`PreviewView.vue:696-702,713-744,748-754,746`。多个 async `watch` 无 try/catch（`loadPdfPreview`/`getDocument` 抛错即未处理拒绝，预览留空无提示）；`onUnmounted(async () => ...)` Vue 不 await，`destroy()` 拒绝则另一 doc 未销毁漏内存且 `clearPreviewState` 不执行；`renderQueue` 末尾无 `.catch` 致最后一次渲染未处理拒绝。建议 watcher 包 try/catch；onUnmounted 改同步逐个 try/catch destroy 再同步清状态；renderQueue 加终态 `.catch`。
- **M42 — fetch 无超时无 Abort**：`api.js:14-38`。后端挂起则前端无限等待，下载无法取消。建议 `AbortController` + 超时。
- **M43 — 上传消息按文案子串判错/对**：`WorkspaceView.vue:43-55`。`message.includes("Choose"/"请先"/...)` 判 error/success，文案一改即坏。建议用独立 `uploadKind` 字段显式标记。
- **M44 — 时间线每秒重排全量事件**：`WorkspaceView.vue:61-79,227-231`。`selectedJobTimeline` 依赖每秒更新的 `nowMs`，每 tick `[...events].sort()` 并重建数组。建议拆为稳定排序列表（memo 于 events）+ 仅运行中时长小 computed。
- **M45 — 预览脏/溢出每次按键全树扫描**：`store.js:76-77,171-217,201-217`、`PreviewView.vue:69-87,89-115`。`previewDirty`/溢出计数扫每页每块每格，`previewDraft` 深响应，每次按键 O(N) 重算。大工业 PDF（百页千块）将卡顿。建议按页 memo 脏检查、debounce、用变更 block id 集合；移除 store 与 view 重复的溢出逻辑。
- **M46 — URL 路径段未 `encodeURIComponent`**：`store.js` 多处、`PreviewView.vue:289,297,311,611-612`。`jobId` 直接拼入 `/jobs/${jobId}/...`，来自路由参数（vue-router 解码），构造 `/preview/..%2F..` 可注入路径段。建议一律 `encodeURIComponent` 并校验 id 格式。
- **M47 — 可点击 `<article>` 无键盘可达性**：`WorkspaceView.vue:353-359`、`PreviewView.vue:952-964`。任务卡/编辑行用 `<article @click>` 无 `tabindex`/`role="button"`/`@keydown`，键盘不可达。建议加 `tabindex="0"` `role="button"` `@keydown.enter/space` 或用 `<button>`。

---

## Low（主要项，按模块分组）

### BabelDOC hooks / 渲染守卫
- **L1 — 死代码**：`babeldoc_hooks.py:2018-2029`（`_merge_paragraphs_with_overlap`）、`2094-2106`（`_should_absorb_overlapping_fragment`）从未被调用。建议删除。
- **L2 — 函数内 `re.compile`**：`babeldoc_hooks.py:3338` 等。热函数内显式 compile，依赖正则缓存。建议提到模块级。
- **L3 — 多个归一化遍历 O(n²)**：`babeldoc_hooks.py:714-753,872-921,923-1042,1897-1934`。按基线/列桶可降为近线性。
- **L4 — 每段落 `copy.deepcopy(composition)`**：`babeldoc_hooks.py:478,1519-1525`。大 PDF 内存膨胀。建议仅 deepcopy 实际复用的。
- **L5 — 每字符动态新建类**：`babeldoc_hooks.py:3899-3918`。`type("SyntheticBox",(),{})()` 每字符新建类。建议模块级定义一次。
- **L6 — `_page_number` +1 歧义**：`babeldoc_hooks.py:1670-1674`。条件 +1 脆弱无文档，影响 TOC 候选判定。建议统一规范一次性归一。
- **L7 — 魔法数字遍布**：`babeldoc_hooks.py` 大量阈值（0.62/0.45/0.55/0.8/6.0/...）内联无命名常量。建议提取命名常量。
- **L8 — `_AxisLabelRenderUnit.render` 直写 PDF 算子未校验 font_id 合法性**：`babeldoc_hooks.py:2226-2252`。`font_id` 含空格/括号则输出非法 PDF 名。建议校验为合法 PDF 名 token。
- **L9 — `grouper.dominant_value` O(n²)**：`interceptors/grouper.py:7`。`max(set(values), key=values.count)`。建议 `Counter.most_common(1)`。
- **L10 — `trie_matcher` 无 marisa-trie 回退 O(terms×text_len)**：`translators/trie_matcher.py:44-49`。建议编译正则或硬依赖 marisa_trie。
- **L11 — 术语子串匹配无词边界**：`translators/trie_matcher.py:50-54`。短词如 `IC`/`in`/`V` 匹配进无关词（`RADICAL`/`running`/`VDDIO`）并注入提示误导模型。建议加词边界/最小长度。
- **L12 — 提示术语行数无上限**：`translators/prompt_builder.py:8-16`。长文本×大词库可注入成百"锁定术语"撑爆上下文与成本。建议 cap top N 并净化换行。
- **L13 — `cascade_scaler` 用 `or` 链把 0.0 当缺失**：`render_guards/cascade_scaler.py:6-8`。`0.0` 合法字号被跳过；非数字串 `float()` 抛错未捕获。建议显式 None 检查并 guard float。
- **L14 — `line_wrapper` 运行时 tokenizer 错未 fail-open**：`render_guards/line_wrapper.py:16-26`。仅处理 `ImportError`，运行时 `word_tokenize` 抛错会中止翻译。建议 try/except 回退原文。
- **L15 — `font_router` 配置值假设为 list**：`render_guards/font_router.py:60-61`。若 JSON 存单字符串，迭代按字符检查 `Path(c).exists()` 返回无意义结果。建议校验为 list 或 coerce。
- **L16 — `weight_detector` 子串匹配误报**：`interceptors/weight_detector.py:25-27`。`black` 匹配 `blackletter`、`demi` 匹配 `demibold`。建议 token 级匹配。

### 翻译 / 预览
- **L17 — 重复工具函数**：`preview.py:395-415` vs `translation.py:324-344`（`_has_codepoint_in_ranges`/`_select_pdf_font`）逐字复制将漂移。建议抽共享模块。
- **L18 — 重复页构建逻辑**：`preview.py:1740-1819` vs `2087-2161`。仅 seed 不同，块装配循环逐字重复。建议抽共享 `_assemble_page_blocks`。
- **L19 — `_write_preview` 写失败漏临时文件**：`preview.py:1913-1918`。`json.dump` 抛错则 `delete=False` 的临时文件不删。建议 try/finally unlink。
- **L20 — 白矩形"擦除"假设白底**：`preview.py:2395,2399,2428,2432,2472,2502`。深底/彩带工业 PDF 产生显眼白块。建议采样背景色填充。
- **L21 — `subset_fonts`/`clean=True` 每次预览编辑都跑**：`preview.py:2657-2658`。可能改动复杂 PDF 特性，子集失败抛裸 PyMuPDF 错。建议 subset try/except 回退无子集保存。
- **L22 — 无更新仍重存 PDF**：`preview.py:2582-2658`。`block_updates` 空 仍 open/subset/save/replace。建议空更新早返回。
- **L23 — `BABELDOC_QPS` 非整数导入即崩**：`translation.py:70`。`int(os.getenv(...))` 非数字抛 ValueError 阻止模块加载。建议 try/except 默认值。
- **L24 — `_pixmap_to_image` 假设 RGB/RGBA**：`translation.py:290-292`。灰度/CMYK pixmap `Image.frombytes` 模式不匹配抛错。建议按 colorspace 派生 mode。
- **L25 — `_page_luminance_metrics` 纯 Python 像素循环**：`translation.py:451-469`。建议 numpy 向量化。
- **L26 — `_pdf_prefers_ocr_workaround` 每个非 OCR PDF 都跑**：`translation.py:484-515,841`。渲染 5 页扫描像素。建议按 checksum 缓存决策。
- **L27 — `translate_pdf` 重开输出 PDF 仅为数页**：`translation.py:893-897`。建议从已持有 handle 返回页数。
- **L28 — 取消检查粒度为段非块**：`translation.py:270-271`。段内多 chunk 时取消延迟到下一段。建议每 chunk 前检查。
- **L29 — 预览构建 `output_path` 存在性未检查**：`preview.py:1742`。retention 删除后 `fitz.open` 抛 `FileNotFoundError` 无清晰信息。建议检查并抛清晰错误。
- **L30 — 畸形乘号净化可能改非乘 `*`**：`preview.py:139,337`。`digit * digit` 改 `×`，但工业件号/修订码 `2*03` 被误改。建议 `*` 分支限定乘法上下文或仅归一化 Unicode 乘号字形。

### Worker / 基础设施
- **L31 — 清理删除路径无根域限制**：`worker_service.py:217-222`。删 DB 存 `storage_path` 任意绝对路径，无 `is_relative_to` 守卫。建议删前校验在配置存储根内。
- **L32 — `ready()` 无锁读 `len(futures)`**：`worker_service.py:267`。建议加锁或快照。
- **L33 — 每秒查 DB 取并发上限**：`worker_service.py:167,190-192`。建议带 TTL 缓存。
- **L34 — `Path` 在循环内 import**：`worker_service.py:215`。建议移到模块顶。
- **L35 — 弃用 FastAPI 生命周期钩子**：`worker_service.py:239,244`。`@on_event` 已弃用，建议改 `lifespan` asynccontextmanager。
- **L36 — worker 硬编码 host/port 无日志配置**：`apps/worker/main.py:14`。`0.0.0.0:8001` 硬编码，无 `log_config`。建议从 settings 读并集成 `configure_logging`。
- **L37 — 运行时 `sys.path` 注入**：`apps/worker/main.py:6-8`。建议装为包或用 entry point。
- **L38 — `_mono_output_from_result` glob+stat 竞争**：`babeldoc_runner.py:354-357`。建议 `stat()` 包 try/except 跳过缺失。
- **L39 — `config.cancel_translation()` 可能掩盖原始异常**：`babeldoc_runner.py:165-167`。建议守卫 cancel 调用。
- **L40 — ONNX 布局模型每任务重载**：`babeldoc_runner.py:66`。建议启动时单例。
- **L41 — hook 隔离依赖硬编码克隆函数集**：`babeldoc_runner.py:304-319`。未克隆 helper 经原 `__globals__` 解析到未 hook 类，未来 BabelDOC 重构可能静默失效。建议加启动自测或紧钉版本+升级回归测试。
- **L42 — `font_router` `lru_cache` 永久缓存**：`render_guards/font_router.py:53`。改 JSON 需重启才生效。建议文档说明或 mtime 失效。
- **L43 — `trie_matcher` 词库 JSON 无结构校验**：`translators/trie_matcher.py:21-24`。`domain` 值非 dict 时 `.items()` 抛 `AttributeError`。建议校验 `isinstance`。
- **L44 — `record_audit` 不 commit 依赖调用方纪律**：`audit.py:6-25`。`details` 含非 JSON 序列化值会使 commit 抛错回滚无关工作。建议文档化契约或内部 commit + 净化 details。

### API / 鉴权
- **L45 — `ready` 无 try/except**：`api/main.py:196-201`。依赖宕时 500 带栈而非结构化 503。建议包检查返降级状态。
- **L46 — 原始文件名无长度/字符校验**：`storage.py:65`、`models.py:69`（VARCHAR(255)）。超 255 字符 flush 抛错 500。建议在 `validate_upload_name` 截断/校验。
- **L47 — 语言无 allow-list**：`api/main.py:345-346`。不支持值上传通过、worker 才失败为 FAILED 而非 400。建议上传时校验。
- **L48 — `storage_summary` 五次查询**：`api/main.py:594-608`。建议合并条件聚合。
- **L49 — 函数内懒 import `hash_password`**：`api/main.py:234,278`。建议顶部统一导入。
- **L50 — `load_job_or_404` 总 selectinload events**：`api/main.py:95-104`。下载/取消/重试不用 events 却全量加载。建议仅详情路径加载。
- **L51 — JWT 含未用 `role` claim 且无 `iat`**：`auth.py:29-34`。建议移除或加 `iat`，始终从 DB 授权。
- **L52 — 无显式 CORS/TrustedHost 中间件**：`api/main.py`。默认安全但依赖 Nginx 同源；建议显式编码策略。

### 前端
- **L53 — 无 `app.config.errorHandler`**：`main.js:1-6`。建议安装全局错误处理。
- **L54 — `contentDispositionFilename` 不处理 RFC 5987 `filename*`**：`api.js:55-58`。非 ASCII 文件名不解码。建议加 `filename*=UTF-8''…` 分支。
- **L55 — 上传串行**：`store.js:507-517`。`for…await` 逐个上传。建议有限并发。
- **L56 — 轮询在标签隐藏时仍跑**：`store.js:115-124`。建议按 `visibilitychange` 暂停。
- **L57 — `resize` 监听在 setup 顶层非 onMounted**：`PreviewView.vue:746`。建议移入 onMounted。
- **L58 — 溢出计数逻辑 store 与 view 重复**：`store.js:201-217` vs `PreviewView.vue:80-87,89-115`。建议合并共享 util。
- **L59 — 脏/载荷越界假设结构一致**：`store.js:171-199,257-291`。`draft.pages[i].blocks[j]` 无边界检查。建议 optional chaining/长度检查优雅降级。
- **L60 — `languageName` 每渲染重建选项数组**：`utils.js:74-76`。建议 memoize。
- **L61 — `measurePdfItem` 用 innerHTML+手写转义**：`PreviewView.vue:129-135,194`。当前安全但脆弱。建议用 textContent + DOM `<br>`。
- **L62 — `storage_mode` 用自由文本输入**：`AdminView.vue:218-222`。建议改 AppSelect 枚举。
- **L63 — 缩放两列同值却两控件**：`PreviewView.vue:350-359`。`adjustZoom` 总同时设 source/translated。建议真分列或单控件。
- **L64 — AppSelect 菜单不翻折**：`components/AppSelect.vue:126-142`。近底部仍向下展开。建议空间不足时向上。
- **L65 — 消息存已解析字符串**：`store.js` 各 `state.messages.*`。切语言后旧消息不更新。建议存 key+params 模板解析。
- **L66 — AppSelect `options` 仅校验 Array**：`components/AppSelect.vue:6-14`。无 `{value,label}` 校验。建议加 validator。
- **L67 — `pollHandle` 存于 reactive 对象**：`store.js:71,97-102`。非显示状态却触发响应式开销。建议移到模块级 `let`。
- **L68 — `onOptionKeydown` 末尾无条件赋值**：`components/AppSelect.vue:217`。无 type-ahead 时无意义。建议实现 type-ahead 或移除。

---

## 正面观察（非问题）

- **任务/文件授权一致**：所有带 `job_id` 的端点经 `load_job_or_404`，非拥有者返 404（非 403）防枚举；`list_jobs` 非 admin 按 `created_by` 过滤。未见 IDOR。
- **密码哈希**：bcrypt + 每哈希盐（`auth.py:14`），无明文存储。
- **上传路径用 uuid `stored_name`**（`storage.py:38`），用户文件名不达文件系统路径；流式校验大小并在失败时清理临时文件（`storage.py:50-62`）。
- **审计日志**覆盖鉴权、用户、设置、任务生命周期；模型测试审计记 `model_base_url` 但**不**记 api key（`api/main.py:335`）。
- **调试产物路径**由服务端 uuid 派生 + 固定后缀，`artifact_kind` 白名单两值，无路径穿越（`api/main.py:139-152`）。
- **runner 无 `shell=True` 子进程调用**，无命令注入/不安全反序列化（流水线进程内调用 BabelDOC 库 API）。
- **`_box_rect` 的 `math.isfinite` 守卫**、**`_rect_overlap_ratio` 的 `max(...,1e-6)`**、**`zip(..., strict=True)`** 等防御性写法正确。

---

## 附录：Deployment / Edge hardening

本报告主体仅审 `apps/*`，未对 `infra/`、`docker-compose.yml`、`nginx.conf` 逐行审。但这些部署/边缘层对本仓库的边界安全起决定性作用，且已与正文若干发现形成放大关系，故集中在此列为"范围外但需关注"风险（不编入主问题号）。

- **API 默认直接暴露 0.0.0.0:8000**：`docker-compose.yml:50-51` 默认 `"${API_BIND_HOST:-0.0.0.0}:8000:8000"`。若宿主直接公网/办公网可达，API 绕过 nginx 同源代理对外，正文 L52（无显式 CORS/TrustedHost）即从"默认安全"变为"实际暴露"。建议生产把 `API_BIND_HOST` 默认改为 `127.0.0.1`，仅在确需外部直连时显式放开。
- **Web 端缺安全响应头**：`infra/docker/web/nginx.conf` 全文无任何 `add_header`，`apps/web/index.html` 无 `<meta http-equiv>`。缺失 `Content-Security-Policy`、`X-Frame-Options`/`frame-ancestors`、`X-Content-Type-Options: nosniff`、`Referrer-Policy`。这与正文 C2（伪造 `text/html` + `inline` 无 `nosniff` 的存储型 XSS）、M35（token 存 localStorage，XSS 即泄露）直接叠加：无 CSP 时任一脚本注入即可读 token。建议 nginx 统一 `add_header` 上述头（CSP 至少 `default-src 'self';`，`X-Content-Type-Options: nosniff`，`X-Frame-Options: DENY`，`Referrer-Policy: same-origin`）；API 文件响应（C2/H7）补 `nosniff` 并改 `attachment`。
- **Redis `--protected-mode no --bind 0.0.0.0`**：`docker-compose.yml:24`。容器内可接受，但若端口被误映射或网络为 host 模式，Redis 无鉴权裸奔。建议确认未映射 6379 到宿主、网络隔离；生产加 `requirepass`。
- **postgres 默认弱口令**：`docker-compose.yml:9-11` `POSTGRES_PASSWORD: doc_translator`。仅容器内网可信，但与 C1（不安全默认值）同源风险——部署若把 5432 暴露即弱口令。建议 `.env` 注入强口令并确认不映射。
- **`.env` 已提交且含真实值**（仓库根 `.env` 存在）。与 C1 叠加：若 `.env` 内 secret/密码被提交进历史，即使后续修改，旧值仍在 git 历史中可被用于伪造旧 token。建议核对 `.gitignore` 是否覆盖 `.env`、必要时 `git filter-repo` 清理历史并轮换所有 secret。

> 上述任一条单独看是"部署配置"，但与正文的安全发现组合后，影响面显著放大。建议把边缘加固纳入部署前阻断清单。

---

## 修复优先级建议

1. **立即（部署前阻断）**: C1 默认密钥/密码校验、C2 content-type/inline/nosniff、H7 文件名头注入、H4/H5 API key 明文回传 + SSRF 校验、**附录边缘加固**（API 绑定 127.0.0.1、nginx 安全响应头 + `nosniff`、`.env` 不入库并轮换 secret）。
2. **本周**: C3/C4/C5 hooks fail-open 与热路径异常保护、H1 FAILED 留文件 + `/documents/translated` 状态守卫 + `retry_job` 清旧 output、H2 跨线程 Font、H10/H11 worker 崩溃恢复与整体超时、H8/H9 限流器与连接池。
3. **迭代优化**: M 组（队列一致性、进度提交容错、M33 源文件过期 410、前端 401/守卫/disabled 态、性能 O(n²) 与重复 stat）。
4. **长期清理**: L 组（死代码、重复逻辑、魔法数字、可访问性、命名常量）。
