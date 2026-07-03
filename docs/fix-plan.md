# Doc Translator 修复计划（按优先级）

- **配套文档**: [code-review.md](./code-review.md)（问题清单与证据）
- **用途**: 把 review 发现转化为可执行的修复批次，每条给出**位置 / 修复动作 / 验证 / 工时**。Tier 0/1 给到代码级动作，Tier 2/3 按主题分组。
- **工时**: S ≈ 半天内 / M ≈ 1–2 天 / L ≈ 3+ 天（单人，含自测）。
- **修复原则**: 边修边加回归测试；安全类先加测试再改代码；涉及上游库行为的（H2/H8）先按"复现步骤"取证再决定是否降级。

---

## Tier 0 — 部署前阻断（上线前必须完成）

目标：消除"部署即可被接管"与"上传即可 XSS 提权"。全部为 S–M 工时。

### 0.1 C1 — 启动默认值守护 + bootstrap 补建条件收紧
- **位置**: `core/config.py:9,31`、`bootstrap.py:16-26`、`api/main.py:50-56`（lifespan）
- **修复动作**:
  1. `lifespan`（`main.py:50-56`）在 `bootstrap_defaults` 之前加守护：当 `settings.app_env == "production"` 且 `app_secret_key in {"change-me", ""}` 或 `len(app_secret_key) < 32` 或 `admin_password == "change-this-password"` 时，`raise RuntimeError("Refusing to start: insecure default secrets in production")`，服务不启动。
  2. `bootstrap_defaults`（`bootstrap.py:16`）把补建条件从"该邮箱不存在"改为"**系统无任何活跃 admin**"：`existing_admin = session.query(User).filter(User.role == UserRole.ADMIN, User.is_active.is_(True)).first()`；仅当其为 None 且 `admin_password != "change-this-password"` 时才补建。
  3. 补建成功后 `record_audit(..., action="auth.bootstrap_admin_created", ...)`。
- **验证**: ① 生产 env 留默认值启动应失败；② 库里已有别的 admin 时，即使 `admin@example.com` 不存在也不补建；③ 无 admin 且密码非默认时补建并留审计。
- **工时**: S

### 0.2 C2 + H7 — 上传 content-type 伪造 XSS + 下载文件名头注入
- **位置**: `storage.py:68`、`api/main.py:495-509`（`read_job_document`）
- **修复动作**:
  1. `storage.py:68` 改为始终由扩展名派生：`"content_type": SUPPORTED_EXTENSIONS[extension]`（丢弃 `file.content_type`）。`translation.py:948` 复制 `input_file.content_type` 的逻辑因此自动正确。
  2. `api/main.py:504-509` 删除手工 `Content-Disposition` f-string，改用 `FileResponse(path=..., media_type=job_file.content_type, filename=job_file.original_name)`（Starlette 自动 RFC 编码文件名，消除头注入）。
  3. 给该响应加 `headers={"X-Content-Type-Options": "nosniff"}`；对用户上传文件用 `attachment` 而非 `inline`（若前端 PDF 预览需 inline，则仅对 `application/pdf` 且扩展名校验通过时允许 inline，但 `nosniff` 必加）。
- **验证**: ① 上传 `evil.pdf`+`Content-Type: text/html`，DB 存 `application/pdf`；② 下载响应头含 `nosniff`、`Content-Disposition` 文件名含特殊字符时被正确编码、浏览器不按 HTML 渲染。
- **工时**: S

### 0.3 H4 — `model_api_key` 不再明文回传；`SettingsUpdate` 改 partial
- **位置**: `schemas.py:60`（`SettingsRead`）、`SettingsUpdate` 各字段、`settings_service.py:85`、`api/main.py:295-317`
- **修复动作**:
  1. `SettingsRead.model_api_key` 改为只读掩码字段（如 `model_api_key_masked: str`，显示 `****<末4位>` 或 `""`），不再返回真实 key。
  2. `SettingsUpdate` 字段改 `Optional[...] = None`，`None` 表示"不变"；`update_settings` 仅在字段非 None 时写入，`model_api_key` 为空串/None 时跳过。
  3. 前端 `AdminView` 设置表单：key 字段留空表示不修改，提交时不回传旧值。
- **验证**: ① `GET /settings` 响应不含完整 key；② `PUT /settings` 不传 key 时 DB 中 key 不变；③ 前端仍能保存其他字段。
- **工时**: M（含前端联动）

### 0.4 H5 — `model_base_url` SSRF 校验
- **位置**: `schemas.py:74-75,84-88`、`settings_service.py:74-76`、`api/main.py:320-338`（`test_model`）、`translation.py:135-136`
- **修复动作**:
  1. 新增 `validate_model_endpoint(url: str)`：解析 URL，要求 scheme ∈ {http,https}；解析 host，拒绝回环（127/8、::1）、链路本地（169.254/16，含 169.254.169.254 元数据 IP）、私网（10/8、172.16/12、192.168/16）、`0.0.0.0`；可选支持 admin 配置 allowlist。
  2. 在 `SettingsUpdate` 校验器、`update_settings`、`test_model_connection` 入口三处统一调用该校验，非法返 400。
- **验证**: ① 设 `http://169.254.169.254/` 被 400 拒绝；② 正常 https 端点通过；③ 内网地址被拒（除非 allowlist）。
- **工时**: S–M

### 0.5 附录边缘加固
- **位置**: `docker-compose.yml:24,50-51`、`infra/docker/web/nginx.conf`、`apps/web/index.html`、`.gitignore`
- **修复动作**:
  1. `docker-compose.yml:51` 默认改 `"${API_BIND_HOST:-127.0.0.1}:8000:8000"`（需外部直连时由 env 显式放开）；确认 redis/pg 端口未映射到宿主。
  2. `nginx.conf` 加：`add_header X-Content-Type-Options "nosniff" always;`、`add_header X-Frame-Options "DENY" always;`、`add_header Referrer-Policy "same-origin" always;`、`add_header Content-Security-Policy "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline';" always;`。
  3. 确认 `.env` 已在 `.gitignore`；若曾入库，`git filter-repo` 清理历史并轮换 `app_secret_key`/`admin_password`/`model_api_key`/DB 口令。
  4. 生产 redis 加 `requirepass`，pg 口令由 `.env` 注入强值。
- **验证**: ① `curl -I` 响应含上述头；② `git log -- .env` 无历史；③ 外部主机无法直连 8000/6379/5432。
- **工时**: M

---

## Tier 1 — 本周（核心正确性与可靠性）

目标：消除"单段坏文本崩溃整单""FAILED/重试中任务暴露旧译文""worker 崩溃任务永久卡死""连接池无界"。

### 1.1 H1 — FAILED 留文件 + `/documents/translated` 状态守卫 + retry 清旧 output
- **位置**: `translation.py:944-1012`、`api/main.py:127-136`（`load_job_document`）、`438-465`（`retry_job`）
- **修复动作**:
  1. worker 侧：把 `session.add(output_file)` + `flush()` + `job.output_file_id =` 延后到 `load_or_create_preview` 成功之后；或预览失败时先 `session.rollback()` 再标记 FAILED 再 commit。
  2. API 侧 `load_job_document` translated 分支（`main.py:130-135`）增补 `if job.status != JobStatus.COMPLETED: raise 409`。
  3. `retry_job`（`438-465`）在置 `QUEUED` 时 `job.output_file_id = None`（旧 output 文件由 retention 清理，或此处主动 `session.delete`/隔离）。
- **验证**: ① 触发 PDF 预览失败 → 任务 FAILED 且 `output_file_id` 为空、`/documents/translated` 返 409；② 重试中任务 `/documents/translated` 不再暴露旧译文。
- **工时**: M

### 1.2 C3 + C4 + C5 — BabelDOC hooks fail-open + 轴标签渲染守护 + 翻译调用回退
- **位置**: `babeldoc_hooks.py`（各 hook 入口 298-1330）、`2180-2252`（`render`）、`1338,2460`
- **修复动作**:
  1. 为每个公共 hook 入口（`should_skip_translation`、`translation_text_override`、`translated_text_override`、`classify_document`、`replace_axis_label_render_units`、`record_translation`、各 `normalize_*_before_translation`、`reconcile_translation`）包 try/except：记录 `logger.exception(...)` 并返回透传结果（`return text` / `return render_units` / `return None`）。可用装饰器统一实现。
  2. `_AxisLabelRenderUnit.render`（2180-2252）用 `getattr` 守卫 `box`/`pdf_style`/`graphic_state`，缺字段 char 跳过；校验 `font_id` 为合法 PDF 名 token。
  3. `_translate_axis_label_text`（1338）、`_retry_translate_axis_label_body_only`（2460）把 `translator.translate(...)` 包 try/except，异常时回退到 `source_text`。
- **验证**: ① 构造 `pdf_style=None` 的异常段落，整单不崩、该段保留原文；② 轴标签翻译网络错误时回退源文、任务继续；③ 产出 PDF 可正常打开。
- **工时**: M–L（hooks 多，建议用装饰器 + 抽样回归）

### 1.3 H10 + H11 — worker 崩溃恢复 + 整体翻译超时
- **位置**: `worker_service.py:54,66,71-158,203-232`、`babeldoc_runner.py:125`、`translation.py:905`
- **修复动作**:
  1. `cleanup_loop`（`worker_service.py:194-201`）加定期孤儿扫描：查询 `status in (PARSING,OCR_RUNNING,TRANSLATING,REBUILDING,VALIDATING)` 且 `updated_at < now - lease`（如 30min）的任务，重置为 `QUEUED` 并 `enqueue_job`；`run_translation_job` 每进度更新写 `job.updated_at` 作心跳。
  2. 优雅关停（`66`）：`executor.shutdown(wait=True, cancel_futures=True)` 配超时，超时后把仍 running 的任务标记 `FAILED`（"worker shutdown"）。
  3. `babeldoc_runner.py:125` 用 `asyncio.wait_for(_run_babeldoc_translation(...), timeout=base + page_count * per_page)` 包裹，超时抛清晰错误使任务失败、释放槽位。
- **验证**: ① kill worker 进程后重启，卡住任务被重排；② 模拟 BabelDOC 挂起，超时后任务 FAILED 而非永久 running。
- **工时**: M

### 1.4 H2 — `fitz.Font` 跨线程共享
- **位置**: `preview.py:769-775`
- **修复动作**（先取证再改）: 按 review 的复现步骤并发 `PUT /preview` 看是否段错误；若确认不安全，去掉 `@lru_cache`，每次新建 `fitz.Font`（已加载 buffer 廉价），或改 thread-local 缓存，或用 `threading.Lock` 包裹 `.text_length()`。
- **验证**: 并发压测 `PUT /preview` 无崩溃且度量一致。
- **工时**: S（取证）+ S（改）

### 1.5 H8 + H9 — 限流器语义确认 + httpx 连接池有界并关闭
- **位置**: `babeldoc_runner.py:49,58-65,96`、`queueing.py:9-11`、`worker_service.py:163`
- **修复动作**:
  1. H8 先取证：`inspect.getsource(set_translate_rate_limiter)` 确认是否模块级单例；若是全局，文档说明"QPS 为全局限额"，且 `qps` 未变时不重复调用（用模块级缓存上次值对比）。
  2. H9 `babeldoc_runner.py:58-65` `httpx.Limits(max_connections=64, max_keepalive_connections=16)`（有限值）；`finally` 中 `translator.client.close()`/`httpx_client.close()`。
  3. `queueing.py`/`worker_service.py` 的 `get_redis_client` 改进程级单例（`functools.lru_cache(maxsize=1)` 或模块级），复用连接池。
- **验证**: ① 并发多任务时 LLM QPS 被全局封顶（符合文档）；② `lsof` 无 socket 泄漏增长；③ Redis 连接数稳定。
- **工时**: M

---

## Tier 2 — 迭代优化（按主题）

建议拆成若干小 PR，每个主题独立可回归。

### 主题 A — 队列与状态一致性
- **M20/M21/M22/M26**（commit-before-enqueue、重复出队丢弃、多 worker 启动竞争、上传/重试 commit 后入队）：引入"入队后提交"或事务发件箱；重复出队时重新 rpush 而非丢弃；多 worker 启动用 Redis 逐任务锁协调恢复（或文档强制单 worker）。工时 M。
- **M23**（失败 future 异常未检查）：`_prune_finished` 调 `future.exception()` 并记日志；`translation.py:906` `SessionLocal()` 移入 try。工时 S。
- **M24**（清理单文件失败回滚全部）：逐文件 try/except + 逐文件 commit；删前 `is_relative_to(storage_root)` 守卫（L31）。工时 S。
- **M19**（executor 硬编码 16）：按启动 `max_concurrent_jobs` 设池大小或文档说明 16 为上限。工时 S。

### 主题 B — 错误处理与信息泄露
- **M7/M8**（进度提交失败杀翻译、失败路径审计丢状态）：进度 commit 包 try/except 续跑；失败路径 `record_audit`/commit 尽力而为吞错保留原始异常。工时 S。
- **M10/M11**（httpx 在 try 外无重试、OCR 失败）：`httpx.post` 移入 try 统一 `RuntimeError` + 有界退避重试；捕获 `TesseractNotFoundError` 给清晰提示、逐页失败跳过告警。工时 M。
- **M9**（split_text 不切超大单段）：单段长于 `max_chars` 按句/长度硬切。工时 S。
- **M30**（preview 500 泄露 `str(exc)`）：服务端记全量、客户端返通用消息。工时 S。
- **L23**（`BABELDOC_QPS` 非整数导入崩）：try/except 默认值。工时 S。

### 主题 C — API 鉴权与输入校验
- **M28**（admin 可自禁用/降级）：禁止最后活跃 admin 被禁/降级或禁止自禁/自降。工时 S。
- **M29**（test_model 同步阻塞最长 3600s）：测试端点固定 ≤10s 超时。工时 S。
- **M27**（list_jobs 无分页）：加 `offset`/`limit`（仿 `list_users`）。工时 S。
- **M31**（JWT 12h 无刷新无吊销）：缩短默认 15–60min + `iat`/`jti` + 用户 token 版本号（改密 bump）。工时 M。
- **M32**（`local_storage_path` 无校验）：校验在允许根内、`storage_mode` 枚举。工时 S。
- **L46/L47/L51**（文件名长度/字符、语言 allow-list、未用 role claim）：上传时校验。工时 S。

### 主题 D — 前端会话与健壮性
- **M36**（无 401 处理 + 轮询不停）：`apiRequest` 集中 401 → 登出/清会话/停轮询 + 提示。工时 M。
- **M35**（token 存 localStorage）：配合 Tier 0 后端改 HttpOnly cookie；过渡期用 `sessionStorage` + 严格 CSP（依赖 0.5 nginx CSP）。工时 M。
- **M34/M38/M37**（AppSelect 重复 id、多处异步无 catch/disabled、无导航守卫）：AppSelect 用 `useId()`；每调用点 try/catch + pending 标志；加 `router.beforeEach` + catch-all。工时 M。
- **M40**（`refreshAll` all-or-nothing）：改 `Promise.allSettled` 或拆分。工时 S。
- **M41/M42**（PreviewView async watcher/onUnmounted、fetch 无超时）：watcher try/catch；onUnmounted 同步逐个 try/catch destroy；`AbortController` + 超时。工时 M。
- **M46**（URL 路径段未 `encodeURIComponent`）：一律编码 + 校验 id 格式。工时 S。

### 主题 E — 预览与排版性能（工业大 PDF）
- **M16/M17/M18**（片段聚类 O(n³)、相似度 O(n²)、字体 stat 反复）：空间索引/按行列预分组；长度桶粗筛；按语言 profile 缓存字体文件路径。工时 L。
- **M44**（脏/溢出每按键全树扫描）：按页 memo + debounce + 变更 block id 集合；合并 store/view 重复溢出逻辑。工时 M。
- **M43**（时间线每秒重排）：稳定排序 memo + 仅运行中时长小 computed。工时 S。
- **M13/M14/M15**（sidecar 字段越界、字体缓存目录注入、译文替换破坏 run 格式）：显式 schema 校验返 400；限定字体目录在配置根内；逐 run 替换文本保留超链接。工时 M。

### 主题 F — 翻译质量与术语
- **L11/L12**（术语子串匹配无词边界、提示行数无上限）：加词边界 + 最小长度；cap top N 并净化换行。工时 M（影响工业译文质量，建议优先于其他 L）。

---

## Tier 3 — 长期清理（低风险，随改随清）

- **死代码删除**（L1）：`babeldoc_hooks.py:2018-2029,2094-2106`。
- **重复逻辑合并**（L17/L18/L58）：`_has_codepoint_in_ranges`/`_select_pdf_font` 抽共享模块；`_build_pdf_pages` 两路径抽 `_assemble_page_blocks`；store/view 溢出逻辑合并。
- **性能微优**（L2/L4/L5/L10/L25/L26/L27/L33）：`re.compile` 提模块级；deepcopy 仅复用项；`Counter.most_common`；luminance 用 numpy；OCR 决策按 checksum 缓存；并发上限带 TTL 缓存。
- **魔法数字命名**（L7）：提取 `babeldoc_hooks.py` 阈值为命名常量。
- **可访问性**（M47 及 L 系列）：可点击 `<article>` 加 `tabindex/role/keydown`；AppSelect 菜单翻折；type-ahead。
- **代码质量杂项**（L34–L44/L53–L68）：`record_audit` 契约文档化 + details 净化；worker `lifespan` 替换 `on_event`；`Path` import 上提；`pollHandle` 移出 reactive；`languageName` memoize；`storage_mode` 改 AppSelect 枚举等。
- **健壮性微调**（L14/L20/L21/L22/L24/L28/L29/L30）：白矩形采样背景色；`subset_fonts` try/except 回退；无更新早返回；`_pixmap_to_image` 按 colorspace 派生 mode；取消检查每 chunk；畸形乘号 `*` 限定上下文；TOC leader 仅匹配点符等。

---

## 建议修复顺序与依赖

```
Tier 0（并行可做，互不依赖）
 0.1 C1 ─┐
 0.2 C2/H7 ─┤   0.5 边缘加固（含 CSP）─┐
 0.3 H4 ──┼──> 上线安全基线            │
 0.4 H5 ──┘                             │
                                        ▼
Tier 1（建议顺序）
 1.1 H1（状态一致性）─> 1.2 C3/4/5（hooks fail-open，收益最大）
                  └─> 1.3 H10/H11（可靠性）
                  └─> 1.4 H2 / 1.5 H8/H9（先取证再改，可并行）

Tier 2（按主题分 PR，主题 A/B 先于 C/D/E/F）
  主题 A 队列一致性 ─> 主题 B 错误处理 ─> 主题 C 鉴权 ─> 主题 D 前端 ─> 主题 E 性能 ─> 主题 F 术语质量

Tier 3（随改随清，不阻塞）
```

**关键依赖**：
- 0.5（nginx CSP）是 M35（token 存 localStorage 过渡方案）的前置——CSP 落地后前端 token 风险才真正下降。
- 1.1 H1 的 API 侧守卫应与 worker 侧同 PR，否则单改一侧仍有暴露窗口。
- 1.2 的装饰器若先落地，1.3/1.5 的异常路径更安全（hook 异常不再杀整单）。
- 1.4/1.5 标注"先取证"——若团队确认上游安全，可降级并加注释，避免无效改动。

## 验证策略

- **安全类（Tier 0）**：每个修复先加失败用例测试（如伪造 content-type 上传应被拒、默认 secret 启动应失败）再改代码；上线前过一遍 `curl -I` 头检查 + `git log -- .env`。
- **可靠性类（Tier 1）**：构造异常段落 PDF、模拟 worker 崩溃/网络挂起，回归任务不卡死、不暴露旧译文。
- **性能类（主题 E）**：用真实工业 datasheet（百页、密集表格）对比修复前后预览构建耗时与内存。
- **回归基线**：维护一份"已知能正确翻译+预览"的 PDF 集合，每个 Tier 1/主题 PR 跑一遍，防止 fail-open 改动引入静默退化。
