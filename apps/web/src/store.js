import { computed, reactive } from "vue";
import { apiPath, apiRequest, contentDispositionFilename, triggerDownload } from "./api";
import { isJobExpired } from "./utils";

const TOKEN_STORAGE_KEY = "doc-translator.token";
const UI_LANGUAGE_STORAGE_KEY = "doc-translator.ui-language";
const MODEL_LIST_CACHE_STORAGE_KEY = "doc-translator.model-list-cache";
const MODEL_FORMAT_CACHE_STORAGE_KEY = "doc-translator.model-format-cache";
const MODEL_LIST_CACHE_TTL_MS = 60 * 60 * 1000;
const DEFAULT_SOURCE_LANGUAGE = "auto";
const DEFAULT_TARGET_LANGUAGE = "Chinese";
const POLL_INTERVAL_MS = 15000;
const JOB_PAGE_SIZE = 50;
const USER_PAGE_SIZE = 20;
const AUDIT_PAGE_SIZE = 10;

function defaultUiLanguage() {
  const language = window.navigator.language || "";
  return language.toLowerCase().startsWith("zh") ? "zh-CN" : "en";
}

export const state = reactive({
  token: window.localStorage.getItem(TOKEN_STORAGE_KEY) || "",
  uiLanguage: window.localStorage.getItem(UI_LANGUAGE_STORAGE_KEY) || defaultUiLanguage(),
  user: null,
  jobs: [],
  jobsPage: {
    total: 0,
    hasMore: false,
  },
  selectedJobId: null,
  selectedJob: null,
  settings: null,
  users: [],
  usersPage: {
    total: 0,
    offset: 0,
    limit: USER_PAGE_SIZE,
    hasMore: false,
  },
  storage: null,
  audit: [],
  auditPage: {
    total: 0,
    offset: 0,
    limit: AUDIT_PAGE_SIZE,
    hasMore: false,
    page: 1,
  },
  previewJob: null,
  previewData: null,
  previewDraft: null,
  previewMode: "view",
  previewDocuments: {
    sourceUrl: null,
    translatedUrl: null,
  },
  pending: {
    bootstrap: false,
    login: false,
    refresh: false,
    upload: false,
    preview: false,
    previewSave: false,
    settings: false,
    userCreate: false,
    userList: false,
    audit: false,
    modelTest: false,
    modelList: false,
  },
  modelTestResult: {
    connectionMessage: "",
    connectionLevel: "info",
    validationMessage: "",
    validationLevel: "info",
  },
  messages: {
    login: "",
    upload: "",
    jobs: "",
    preview: "",
    settings: "",
    users: "",
    audit: "",
  },
  messageLevels: {
    login: "info",
    upload: "info",
    jobs: "info",
    preview: "info",
    settings: "info",
    users: "info",
    audit: "info",
  },
  pollHandle: null,
});

export const isAuthenticated = computed(() => Boolean(state.user && state.token));
export const isAdmin = computed(() => state.user?.role === "admin");
export const previewDirty = computed(() => hasPreviewChanges(state.previewData, state.previewDraft));
export const previewLayoutOverflowCount = computed(() => countPreviewLayoutOverflows(state.previewDraft));

export function copy(zh, en) {
  return state.uiLanguage === "zh-CN" ? zh : en;
}

export function setMessage(scope, text = "", level = "info") {
  state.messages[scope] = text;
  state.messageLevels[scope] = level;
}

export function clearModelTestResult() {
  state.modelTestResult.connectionMessage = "";
  state.modelTestResult.connectionLevel = "info";
  state.modelTestResult.validationMessage = "";
  state.modelTestResult.validationLevel = "info";
}

export function setUiLanguage(value) {
  state.uiLanguage = value === "en" ? "en" : "zh-CN";
  window.localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, state.uiLanguage);
}

function setToken(token) {
  state.token = token || "";
  if (state.token) {
    window.localStorage.setItem(TOKEN_STORAGE_KEY, state.token);
    return;
  }
  window.localStorage.removeItem(TOKEN_STORAGE_KEY);
}

function stopPolling() {
  if (state.pollHandle) {
    window.clearInterval(state.pollHandle);
    state.pollHandle = null;
  }
}

function revokePreviewDocumentUrl(key) {
  const url = state.previewDocuments[key];
  if (!url) {
    return;
  }
  if (url.startsWith("blob:")) {
    URL.revokeObjectURL(url);
  }
  state.previewDocuments[key] = null;
}

function startPolling() {
  if (state.pollHandle || !state.user) {
    return;
  }
  state.pollHandle = window.setInterval(() => {
    refreshJobsOnly().catch((error) => {
      console.error(error);
    });
  }, POLL_INTERVAL_MS);
}

function revokePreviewDocumentUrls() {
  for (const key of ["sourceUrl", "translatedUrl"]) {
    revokePreviewDocumentUrl(key);
  }
}

export function clearPreviewState() {
  revokePreviewDocumentUrls();
  state.previewJob = null;
  state.previewData = null;
  state.previewDraft = null;
  state.previewMode = "view";
  setMessage("preview");
}

function clearSessionState() {
  stopPolling();
  clearPreviewState();
  state.user = null;
  state.jobs = [];
  state.jobsPage = {
    total: 0,
    hasMore: false,
  };
  state.selectedJobId = null;
  state.selectedJob = null;
  setMessage("jobs");
  state.settings = null;
  state.users = [];
  state.usersPage = {
    total: 0,
    offset: 0,
    limit: USER_PAGE_SIZE,
    hasMore: false,
  };
  state.storage = null;
  state.audit = [];
  state.auditPage = {
    total: 0,
    offset: 0,
    limit: AUDIT_PAGE_SIZE,
    hasMore: false,
    page: 1,
  };
}

function clonePreview(preview) {
  return preview ? structuredClone(preview) : null;
}

function hasPreviewChanges(original, draft) {
  if (!original || !draft) {
    return false;
  }
  if (original.document_kind === "pdf") {
    for (let pageIndex = 0; pageIndex < original.pages.length; pageIndex += 1) {
      const originalPage = original.pages[pageIndex];
      const draftPage = draft.pages[pageIndex];
      for (let blockIndex = 0; blockIndex < originalPage.blocks.length; blockIndex += 1) {
        const originalBlock = originalPage.blocks[blockIndex];
        const draftBlock = draftPage.blocks[blockIndex];
        if ((originalBlock.type || "text") === "table") {
          for (let cellIndex = 0; cellIndex < originalBlock.cells.length; cellIndex += 1) {
            if (originalBlock.cells[cellIndex].tgt_text !== draftBlock.cells[cellIndex].tgt_text) {
              return true;
            }
          }
          continue;
        }
        if (originalBlock.tgt_text !== draftBlock.tgt_text) {
          return true;
        }
      }
    }
    return false;
  }

  if (original.document_kind === "xlsx") {
    return original.sheets.some((sheet, sheetIndex) =>
      sheet.cells.some(
        (cell, cellIndex) => cell.translated_text !== draft.sheets[sheetIndex].cells[cellIndex].translated_text
      )
    );
  }

  return original.pages.some((page, index) => page.translated_text !== draft.pages[index].translated_text);
}

function countPreviewLayoutOverflows(preview) {
  if (!preview || preview.document_kind !== "pdf") {
    return 0;
  }

  return preview.pages.reduce((total, page) => {
    return (
      total +
      page.blocks.reduce((pageTotal, block) => {
        if ((block.type || "text") === "table") {
          return pageTotal + block.cells.filter((cell) => cell.layout_status === "overflow").length;
        }
        return pageTotal + (block.layout_status === "overflow" ? 1 : 0);
      }, 0)
    );
  }, 0);
}

function previewEditablePayload() {
  if (!state.previewData || !state.previewDraft || state.previewData.document_kind !== "pdf") {
    return [];
  }

  const updates = [];
  state.previewData.pages.forEach((originalPage, pageIndex) => {
    const draftPage = state.previewDraft.pages[pageIndex];
    originalPage.blocks.forEach((originalBlock, blockIndex) => {
      const draftBlock = draftPage.blocks[blockIndex];
      if ((originalBlock.type || "text") === "table") {
        originalBlock.cells.forEach((originalCell, cellIndex) => {
          const draftCell = draftBlock.cells[cellIndex];
          if (originalCell.tgt_text !== draftCell.tgt_text && draftCell.layout_status !== "overflow") {
            updates.push({
              cell_id: draftCell.cell_id,
              tgt_text: draftCell.tgt_text,
              font_size_final: originalCell.font_size_current || originalCell.font_size_original,
              layout_status: draftCell.layout_status || "ok",
            });
          }
        });
        return;
      }

      if (originalBlock.tgt_text !== draftBlock.tgt_text && draftBlock.layout_status !== "overflow") {
        updates.push({
          block_id: draftBlock.block_id,
          tgt_text: draftBlock.tgt_text,
          font_size_final: originalBlock.font_size_current || originalBlock.font_size_original,
          layout_status: draftBlock.layout_status || "ok",
        });
      }
    });
  });
  return updates;
}

function xlsxEditablePayload() {
  if (!state.previewData || !state.previewDraft || state.previewData.document_kind !== "xlsx") {
    return [];
  }

  const updates = [];
  state.previewData.sheets.forEach((originalSheet, sheetIndex) => {
    const draftSheet = state.previewDraft.sheets[sheetIndex];
    originalSheet.cells.forEach((originalCell, cellIndex) => {
      const draftCell = draftSheet.cells[cellIndex];
      if (originalCell.editable && originalCell.translated_text !== draftCell.translated_text) {
        updates.push({
          sheet_id: originalSheet.id,
          coordinate: originalCell.coordinate,
          translated_text: draftCell.translated_text,
        });
      }
    });
  });
  return updates;
}

function collectQuarantinedPdfEdits(original, draft) {
  if (!original || !draft || original.document_kind !== "pdf") {
    return new Map();
  }

  const quarantined = new Map();
  original.pages.forEach((originalPage, pageIndex) => {
    const draftPage = draft.pages[pageIndex];
    originalPage.blocks.forEach((originalBlock, blockIndex) => {
      const draftBlock = draftPage.blocks[blockIndex];
      if ((originalBlock.type || "text") === "table") {
        originalBlock.cells.forEach((originalCell, cellIndex) => {
          const draftCell = draftBlock.cells[cellIndex];
          if (originalCell.tgt_text !== draftCell.tgt_text && draftCell.layout_status === "overflow") {
            quarantined.set(draftCell.cell_id, {
              font_size_current: draftCell.font_size_current,
              layout_status: draftCell.layout_status,
              tgt_text: draftCell.tgt_text,
            });
          }
        });
        return;
      }

      if (originalBlock.tgt_text !== draftBlock.tgt_text && draftBlock.layout_status === "overflow") {
        quarantined.set(draftBlock.block_id, {
          font_size_current: draftBlock.font_size_current,
          layout_status: draftBlock.layout_status,
          tgt_text: draftBlock.tgt_text,
        });
      }
    });
  });
  return quarantined;
}

function restoreQuarantinedPdfEdits(draft, quarantined) {
  if (!draft || draft.document_kind !== "pdf" || quarantined.size === 0) {
    return draft;
  }

  draft.pages.forEach((page) => {
    page.blocks.forEach((block) => {
      if ((block.type || "text") === "table") {
        block.cells.forEach((cell) => {
          Object.assign(cell, quarantined.get(cell.cell_id) || {});
        });
        return;
      }
      Object.assign(block, quarantined.get(block.block_id) || {});
    });
  });
  return draft;
}

async function authedRequest(path, options = {}, config = {}) {
  try {
    return await apiRequest(path, options, { ...config, token: state.token });
  } catch (error) {
    if (error?.status === 401) {
      setToken("");
      clearSessionState();
      setMessage("login", copy("登录已过期，请重新登录。", "Your session expired. Please sign in again."), "warning");
    }
    throw error;
  }
}

async function refreshSelectedJob() {
  if (!state.selectedJobId) {
    state.selectedJob = null;
    return;
  }

  try {
    state.selectedJob = await authedRequest(`/jobs/${state.selectedJobId}`);
  } catch {
    state.selectedJobId = null;
    state.selectedJob = null;
  }
}

function modelListCacheKey(payload) {
  const baseUrl = String(payload.model_base_url || "").trim().replace(/\/+$/, "");
  return JSON.stringify([state.user?.id || "", payload.model_api_format, baseUrl]);
}

function readModelListCache() {
  try {
    return JSON.parse(window.sessionStorage.getItem(MODEL_LIST_CACHE_STORAGE_KEY) || "{}");
  } catch {
    return {};
  }
}

export function cachedModels(payload) {
  const entry = readModelListCache()[modelListCacheKey(payload)];
  if (
    !entry ||
    !Array.isArray(entry.models) ||
    !entry.models.every((model) => typeof model === "string") ||
    typeof entry.cachedAt !== "number" ||
    Date.now() - entry.cachedAt >= MODEL_LIST_CACHE_TTL_MS
  ) {
    return [];
  }
  return entry.models;
}

export function cachedModelMappings(payload) {
  const requestedBaseUrl = String(payload.model_base_url || "").trim().replace(/\/+$/, "");
  const mappings = [];
  let cache;
  try {
    cache = JSON.parse(window.sessionStorage.getItem(MODEL_FORMAT_CACHE_STORAGE_KEY) || "{}");
  } catch {
    return mappings;
  }
  for (const [key, entry] of Object.entries(cache)) {
    let cacheIdentity;
    try {
      cacheIdentity = JSON.parse(key);
    } catch {
      continue;
    }
    const [userId, baseUrl, modelName] = cacheIdentity;
    if (
      userId !== (state.user?.id || "") ||
      baseUrl !== requestedBaseUrl ||
      !entry ||
      !["anthropic_messages", "chat_completions", "responses"].includes(entry.apiFormat) ||
      typeof entry.cachedAt !== "number" ||
      Date.now() - entry.cachedAt >= MODEL_LIST_CACHE_TTL_MS
    ) {
      continue;
    }
    mappings.push({ modelName, apiFormat: entry.apiFormat });
  }
  return mappings;
}

export function clearCachedModels() {
  try {
    window.sessionStorage.removeItem(MODEL_LIST_CACHE_STORAGE_KEY);
    window.sessionStorage.removeItem(MODEL_FORMAT_CACHE_STORAGE_KEY);
  } catch {
    // There is no cache to invalidate when browser storage is unavailable.
  }
}

function cacheModelFormat(payload) {
  const baseUrl = String(payload.model_base_url || "").trim().replace(/\/+$/, "");
  const key = JSON.stringify([state.user?.id || "", baseUrl, payload.model_name]);
  let cache;
  try {
    cache = JSON.parse(window.sessionStorage.getItem(MODEL_FORMAT_CACHE_STORAGE_KEY) || "{}");
    cache[key] = { apiFormat: payload.model_api_format, cachedAt: Date.now() };
    window.sessionStorage.setItem(MODEL_FORMAT_CACHE_STORAGE_KEY, JSON.stringify(cache));
  } catch {
    // A successful connection test does not depend on browser storage.
  }
}

function cacheModels(payload, models) {
  const cache = readModelListCache();
  cache[modelListCacheKey(payload)] = { cachedAt: Date.now(), models };
  try {
    window.sessionStorage.setItem(MODEL_LIST_CACHE_STORAGE_KEY, JSON.stringify(cache));
  } catch {
    // Model discovery still succeeds when browser storage is unavailable.
  }
}

async function fetchJobsThrough(requestedCount = JOB_PAGE_SIZE) {
  const items = [];
  let total = 0;
  let hasMore = false;
  do {
    const limit = Math.min(100, Math.max(JOB_PAGE_SIZE, requestedCount - items.length));
    const page = await authedRequest(`/jobs?offset=${items.length}&limit=${limit}`);
    items.push(...page.items);
    total = page.total;
    hasMore = page.has_more;
  } while (hasMore && items.length < requestedCount);
  return { items, total, hasMore };
}

export async function bootstrapSession() {
  if (!state.token) {
    return;
  }

  state.pending.bootstrap = true;
  try {
    state.user = await authedRequest("/auth/me");
    await refreshAll();
    startPolling();
  } catch (error) {
    setToken("");
    clearSessionState();
    setMessage("login", error.message, "error");
  } finally {
    state.pending.bootstrap = false;
  }
}

export async function login(email, password) {
  state.pending.login = true;
  setMessage("login");
  try {
    const body = new URLSearchParams({
      username: email.trim(),
      password,
    });
    const result = await apiRequest(
      "/auth/login",
      {
        method: "POST",
        body,
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
      },
      {}
    );
    setToken(result.access_token);
    state.user = result.user;
    await refreshAll();
    startPolling();
  } catch (error) {
    setToken("");
    clearSessionState();
    setMessage("login", error.message, "error");
    throw error;
  } finally {
    state.pending.login = false;
  }
}

export function logout() {
  setToken("");
  clearSessionState();
}

export async function refreshJobsOnly() {
  if (!state.user) {
    return;
  }
  const jobsPage = await fetchJobsThrough(Math.max(state.jobs.length, JOB_PAGE_SIZE));
  state.jobs = jobsPage.items;
  state.jobsPage = { total: jobsPage.total, hasMore: jobsPage.hasMore };
  await refreshSelectedJob();
}

export async function refreshJobs() {
  if (!state.user || state.pending.refresh) {
    return;
  }
  state.pending.refresh = true;
  setMessage("jobs");
  try {
    await refreshJobsOnly();
  } catch (error) {
    setMessage("jobs", error.message, "error");
  } finally {
    state.pending.refresh = false;
  }
}

export async function refreshAll() {
  if (!state.user) {
    return;
  }

  state.pending.refresh = true;
  try {
    const jobsPromise = fetchJobsThrough(Math.max(state.jobs.length, JOB_PAGE_SIZE));
    const adminPromise = isAdmin.value
      ? Promise.all([
          authedRequest("/settings"),
          authedRequest(`/users?offset=0&limit=${USER_PAGE_SIZE}`),
          authedRequest("/storage/summary"),
          authedRequest(`/audit-logs?offset=0&limit=${AUDIT_PAGE_SIZE}`),
        ])
      : Promise.resolve(null);

    const [jobsPage, adminData] = await Promise.all([jobsPromise, adminPromise]);
    const jobs = jobsPage.items;
    state.jobs = jobs;
    state.jobsPage = { total: jobsPage.total, hasMore: jobsPage.hasMore };

    if (!state.selectedJobId && jobs[0]) {
      state.selectedJobId = jobs[0].id;
    }
    await refreshSelectedJob();

    if (adminData) {
      const [settings, usersPage, storage, auditPage] = adminData;
      state.settings = settings;
      state.users = usersPage.items;
      state.usersPage = {
        total: usersPage.total,
        offset: usersPage.offset,
        limit: usersPage.limit,
        hasMore: usersPage.has_more,
      };
      state.storage = storage;
      state.audit = auditPage.items;
      state.auditPage = {
        total: auditPage.total,
        offset: auditPage.offset,
        limit: auditPage.limit,
        hasMore: auditPage.has_more,
        page: Math.floor(auditPage.offset / auditPage.limit) + 1,
      };
    }
  } finally {
    state.pending.refresh = false;
  }
}

export async function loadMoreJobs() {
  if (!state.jobsPage.hasMore) {
    return;
  }
  const page = await authedRequest(`/jobs?offset=${state.jobs.length}&limit=${JOB_PAGE_SIZE}`);
  state.jobs = [...state.jobs, ...page.items];
  state.jobsPage = { total: page.total, hasMore: page.has_more };
}

export async function loadMoreUsers() {
  if (state.pending.userList || !state.usersPage.hasMore) {
    return;
  }

  state.pending.userList = true;
  setMessage("users");
  try {
    const result = await authedRequest(`/users?offset=${state.users.length}&limit=${USER_PAGE_SIZE}`);
    state.users = [...state.users, ...result.items];
    state.usersPage = {
      total: result.total,
      offset: result.offset,
      limit: result.limit,
      hasMore: result.has_more,
    };
  } finally {
    state.pending.userList = false;
  }
}

export async function loadUsersPage() {
  state.pending.userList = true;
  setMessage("users");
  try {
    const result = await authedRequest(`/users?offset=0&limit=${USER_PAGE_SIZE}`);
    state.users = result.items;
    state.usersPage = {
      total: result.total,
      offset: result.offset,
      limit: result.limit,
      hasMore: result.has_more,
    };
  } finally {
    state.pending.userList = false;
  }
}

export async function loadAuditPage(page = state.auditPage.page) {
  const nextPage = Math.max(1, page);
  const offset = (nextPage - 1) * AUDIT_PAGE_SIZE;

  state.pending.audit = true;
  setMessage("audit");
  try {
    const result = await authedRequest(`/audit-logs?offset=${offset}&limit=${AUDIT_PAGE_SIZE}`);
    state.audit = result.items;
    state.auditPage = {
      total: result.total,
      offset: result.offset,
      limit: result.limit,
      hasMore: result.has_more,
      page: Math.floor(result.offset / result.limit) + 1,
    };
  } finally {
    state.pending.audit = false;
  }
}

export async function selectJob(jobId) {
  state.selectedJobId = jobId;
  await refreshSelectedJob();
}

export async function uploadJobs(files, sourceLanguage, targetLanguage, modelName, modelApiFormat) {
  const queue = Array.from(files);
  state.pending.upload = true;
  setMessage("upload");
  try {
    for (const file of queue) {
      const formData = new FormData();
      formData.set("file", file);
      formData.set("source_language", sourceLanguage || DEFAULT_SOURCE_LANGUAGE);
      formData.set("target_language", targetLanguage || DEFAULT_TARGET_LANGUAGE);
      if (modelName) {
        formData.set("model_name", modelName);
      }
      if (modelApiFormat) {
        formData.set("model_api_format", modelApiFormat);
      }

      await authedRequest("/jobs/upload", {
        method: "POST",
        body: formData,
      });
    }
    setMessage(
      "upload",
      queue.length === 1 ? copy("任务已加入队列。", "Job queued.") : copy(`${queue.length} 个任务已加入队列。`, `${queue.length} jobs queued.`),
      "success"
    );
    await refreshAll();
  } finally {
    state.pending.upload = false;
  }
}

export async function cancelJob(jobId) {
  const previousJob = state.jobs.find((job) => job.id === jobId);
  const previousSelectedJob = state.selectedJob?.id === jobId ? state.selectedJob : null;
  setMessage("jobs");
  state.jobs = state.jobs.map((job) => (job.id === jobId ? { ...job, cancel_requested: true } : job));
  if (previousSelectedJob) {
    state.selectedJob = { ...previousSelectedJob, cancel_requested: true };
  }
  try {
    const updatedJob = await authedRequest(`/jobs/${jobId}/cancel`, { method: "POST" });
    state.jobs = state.jobs.map((job) => (job.id === updatedJob.id ? updatedJob : job));
    if (state.selectedJob?.id === updatedJob.id) {
      state.selectedJob = { ...state.selectedJob, ...updatedJob };
      await refreshSelectedJob();
    }
  } catch (error) {
    if (previousJob) {
      state.jobs = state.jobs.map((job) => (job.id === jobId ? previousJob : job));
    }
    if (previousSelectedJob) {
      state.selectedJob = previousSelectedJob;
    }
    setMessage("jobs", error.message, "error");
    throw error;
  }
}

export async function retryJob(jobId) {
  const updatedJob = await authedRequest(`/jobs/${jobId}/retry`, { method: "POST" });
  state.jobs = state.jobs.map((job) => (job.id === updatedJob.id ? updatedJob : job));
  if (state.selectedJob?.id === updatedJob.id) {
    state.selectedJob = updatedJob;
  }
  await refreshAll();
}

export async function downloadJob(jobId) {
  const response = await authedRequest(`/jobs/${jobId}/download`, {}, { raw: true });
  const blob = await response.blob();
  const job = state.jobs.find((candidate) => candidate.id === jobId) || (state.previewJob?.id === jobId ? state.previewJob : null);
  const outputName = job?.output_file?.original_name || "";
  const fallback = outputName || `translated-${jobId}`;
  const filename = contentDispositionFilename(response.headers.get("content-disposition"), fallback);
  triggerDownload(blob, filename);
}

export async function saveSettings(payload) {
  state.pending.settings = true;
  setMessage("settings");
  try {
    state.settings = await authedRequest(`/settings`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    setMessage("settings", copy("设置已保存。", "Settings saved."), "success");
  } finally {
    state.pending.settings = false;
  }
}

export async function testModel(payload) {
  state.pending.modelTest = true;
  setMessage("settings");
  clearModelTestResult();
  try {
    const result = await authedRequest(`/settings/test-model`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    state.modelTestResult.connectionMessage = copy(
      `模型连接成功，API 响应时间 ${result.latency_ms} ms。`,
      `Model connected. API response time: ${result.latency_ms} ms.`
    );
    state.modelTestResult.connectionLevel = "success";
    state.modelTestResult.validationMessage = copy(
      "正在验证 response 合法性…",
      "Validating the response format…"
    );

    try {
      await authedRequest(`/settings/validate-model-response`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      cacheModelFormat(payload);
      state.modelTestResult.validationMessage = copy(
        "Response 合法性验证通过。",
        "Response format validation passed."
      );
      state.modelTestResult.validationLevel = "success";
    } catch (error) {
      state.modelTestResult.validationMessage = copy(
        `Response 合法性验证失败：${error.message}`,
        `Response format validation failed: ${error.message}`
      );
      state.modelTestResult.validationLevel = "error";
    }
  } finally {
    state.pending.modelTest = false;
  }
}

export async function listModels(payload) {
  state.pending.modelList = true;
  setMessage("settings");
  try {
    const result = await authedRequest(`/settings/models`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    cacheModels(payload, result.models);
    setMessage(
      "settings",
      copy(`已加载 ${result.models.length} 个模型。`, `Loaded ${result.models.length} models.`),
      "info"
    );
    return result.models;
  } finally {
    state.pending.modelList = false;
  }
}

export async function createUser(payload) {
  state.pending.userCreate = true;
  setMessage("users");
  try {
    await authedRequest("/users", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    await loadUsersPage();
    setMessage("users", copy("用户已创建。", "User created."), "success");
  } finally {
    state.pending.userCreate = false;
  }
}

export async function toggleUserState(userId, payload) {
  const updatedUser = await authedRequest(`/users/${userId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  state.users = state.users.map((user) => (user.id === updatedUser.id ? updatedUser : user));
}

function loadPreviewDocuments(jobId, revision, documentKind) {
  const version = revision ? `?rev=${encodeURIComponent(revision)}` : "";
  revokePreviewDocumentUrls();
  if (documentKind === "pptx") {
    state.previewDocuments.sourceUrl = apiPath(`/jobs/${jobId}/documents/source-preview${version}`);
    state.previewDocuments.translatedUrl = apiPath(`/jobs/${jobId}/documents/translated-preview${version}`);
    return;
  }
  state.previewDocuments.sourceUrl = apiPath(`/jobs/${jobId}/documents/source`);
  state.previewDocuments.translatedUrl = apiPath(`/jobs/${jobId}/documents/translated${version}`);
}

function refreshTranslatedPreviewDocument(jobId, revision, documentKind) {
  const version = revision ? `?rev=${encodeURIComponent(revision)}` : "";
  revokePreviewDocumentUrl("translatedUrl");
  state.previewDocuments.translatedUrl =
    documentKind === "pptx"
      ? apiPath(`/jobs/${jobId}/documents/translated-preview${version}`)
      : apiPath(`/jobs/${jobId}/documents/translated${version}`);
}

export async function loadPreview(jobId) {
  state.pending.preview = true;
  setMessage("preview");
  try {
    clearPreviewState();
    const job = await authedRequest(`/jobs/${jobId}`);
    if (isJobExpired(job)) {
      throw new Error(copy("译文文件已过期，无法查看预览。", "The translated file expired and can no longer be previewed."));
    }
    if (!job.output_file || job.status !== "completed") {
      throw new Error(copy("翻译完成后才可预览。", "Preview is available after translation completes."));
    }

    const preview = await authedRequest(`/jobs/${jobId}/preview`);
    state.previewJob = job;
    state.previewData = preview;
    state.previewDraft = clonePreview(preview);
    state.previewMode = "view";

    if (preview.document_kind === "pdf" || preview.document_kind === "docx" || preview.document_kind === "pptx") {
      loadPreviewDocuments(jobId, preview.updated_at, preview.document_kind);
    }
  } finally {
    state.pending.preview = false;
  }
}

export function setPreviewMode(mode) {
  state.previewMode = mode;
  setMessage("preview");
}

export async function savePreview() {
  if (!state.previewJob || !state.previewDraft || !previewDirty.value) {
    return;
  }

  state.pending.previewSave = true;
  setMessage("preview");
  try {
    const pdfPayload = state.previewDraft.document_kind === "pdf" ? previewEditablePayload() : [];
    const quarantined =
      state.previewDraft.document_kind === "pdf" ? collectQuarantinedPdfEdits(state.previewData, state.previewDraft) : new Map();
    if (state.previewDraft.document_kind === "pdf" && pdfPayload.length === 0) {
      setMessage(
        "preview",
        previewLayoutOverflowCount.value > 0
          ? copy("红框溢出块已隔离，没有可安全保存的修改。", "Overflow blocks were quarantined; there are no safe edits to save.")
          : copy("没有可保存的修改。", "No edits to save."),
        "warning"
      );
      return;
    }

    const payload =
      state.previewDraft.document_kind === "pdf"
        ? {
            status: "validated",
            payload: pdfPayload,
          }
        : state.previewDraft.document_kind === "xlsx"
          ? {
              cells: xlsxEditablePayload(),
            }
        : {
            pages: state.previewDraft.pages.map((page) => ({
              id: page.id,
              translated_text: page.translated_text,
            })),
          };

    const preview = await authedRequest(`/jobs/${state.previewJob.id}/preview`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    state.previewData = preview;
    state.previewDraft = restoreQuarantinedPdfEdits(clonePreview(preview), quarantined);
    if (preview.document_kind === "pdf" || preview.document_kind === "docx" || preview.document_kind === "pptx") {
      refreshTranslatedPreviewDocument(state.previewJob.id, preview.updated_at, preview.document_kind);
    }
    setMessage(
      "preview",
      quarantined.size > 0
        ? copy("安全修改已保存，红框溢出块已保留在草稿中。", "Safe edits saved; overflow blocks remain quarantined in the draft.")
        : copy("修改已保存。", "Edits saved."),
      quarantined.size > 0 ? "warning" : "success"
    );
  } finally {
    state.pending.previewSave = false;
  }
}

export function defaultUploadState() {
  return {
    sourceLanguage: DEFAULT_SOURCE_LANGUAGE,
    targetLanguage: DEFAULT_TARGET_LANGUAGE,
    modelName: "",
    modelApiFormat: "",
  };
}
