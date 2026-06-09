import { computed, reactive } from "vue";
import { apiPath, apiRequest, contentDispositionFilename, triggerDownload } from "./api";

const TOKEN_STORAGE_KEY = "doc-translator.token";
const UI_LANGUAGE_STORAGE_KEY = "doc-translator.ui-language";
const DEFAULT_SOURCE_LANGUAGE = "auto";
const DEFAULT_TARGET_LANGUAGE = "Chinese";
const POLL_INTERVAL_MS = 15000;
const USER_PAGE_SIZE = 20;
const AUDIT_PAGE_SIZE = 10;

export const state = reactive({
  token: window.localStorage.getItem(TOKEN_STORAGE_KEY) || "",
  uiLanguage: window.localStorage.getItem(UI_LANGUAGE_STORAGE_KEY) || "zh-CN",
  user: null,
  jobs: [],
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
  },
  messages: {
    login: "",
    upload: "",
    preview: "",
    settings: "",
    users: "",
    audit: "",
  },
  pollHandle: null,
});

export const isAuthenticated = computed(() => Boolean(state.user && state.token));
export const isAdmin = computed(() => state.user?.role === "admin");
export const previewDirty = computed(() => hasPreviewChanges(state.previewData, state.previewDraft));

export function copy(zh, en) {
  return state.uiLanguage === "zh-CN" ? zh : en;
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
  state.messages.preview = "";
}

function clearSessionState() {
  stopPolling();
  clearPreviewState();
  state.user = null;
  state.jobs = [];
  state.selectedJobId = null;
  state.selectedJob = null;
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

  return original.pages.some((page, index) => page.translated_text !== draft.pages[index].translated_text);
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
          if (originalCell.tgt_text !== draftCell.tgt_text) {
            updates.push({
              cell_id: draftCell.cell_id,
              tgt_text: draftCell.tgt_text,
              font_size_final: draftCell.font_size_current,
            });
          }
        });
        return;
      }

      if (originalBlock.tgt_text !== draftBlock.tgt_text) {
        updates.push({
          block_id: draftBlock.block_id,
          tgt_text: draftBlock.tgt_text,
          font_size_final: draftBlock.font_size_current,
        });
      }
    });
  });
  return updates;
}

async function authedRequest(path, options = {}, config = {}) {
  return apiRequest(path, options, { ...config, token: state.token });
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
    state.messages.login = error.message;
  } finally {
    state.pending.bootstrap = false;
  }
}

export async function login(email, password) {
  state.pending.login = true;
  state.messages.login = "";
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
  state.jobs = await authedRequest("/jobs");
}

export async function refreshAll() {
  if (!state.user) {
    return;
  }

  state.pending.refresh = true;
  try {
    const jobsPromise = authedRequest("/jobs");
    const adminPromise = isAdmin.value
      ? Promise.all([
          authedRequest("/settings"),
          authedRequest(`/users?offset=0&limit=${USER_PAGE_SIZE}`),
          authedRequest("/storage/summary"),
          authedRequest(`/audit-logs?offset=0&limit=${AUDIT_PAGE_SIZE}`),
        ])
      : Promise.resolve(null);

    const [jobs, adminData] = await Promise.all([jobsPromise, adminPromise]);
    state.jobs = jobs;

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

export async function loadMoreUsers() {
  if (state.pending.userList || !state.usersPage.hasMore) {
    return;
  }

  state.pending.userList = true;
  state.messages.users = "";
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
  state.messages.users = "";
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
  state.messages.audit = "";
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

export async function uploadJob(file, sourceLanguage, targetLanguage) {
  const formData = new FormData();
  formData.set("file", file);
  formData.set("source_language", sourceLanguage || DEFAULT_SOURCE_LANGUAGE);
  formData.set("target_language", targetLanguage || DEFAULT_TARGET_LANGUAGE);

  state.pending.upload = true;
  state.messages.upload = "";
  try {
    await authedRequest("/jobs/upload", {
      method: "POST",
      body: formData,
    });
    state.messages.upload = copy("任务已加入队列。", "Job queued.");
    await refreshAll();
  } finally {
    state.pending.upload = false;
  }
}

export async function cancelJob(jobId) {
  await authedRequest(`/jobs/${jobId}/cancel`, { method: "POST" });
  await refreshAll();
}

export async function retryJob(jobId) {
  await authedRequest(`/jobs/${jobId}/retry`, { method: "POST" });
  await refreshAll();
}

export async function downloadJob(jobId) {
  const response = await authedRequest(`/jobs/${jobId}/download`, {}, { raw: true });
  const blob = await response.blob();
  const filename = contentDispositionFilename(response.headers.get("content-disposition"), `translated-${jobId}`);
  triggerDownload(blob, filename);
}

export async function saveSettings(payload) {
  state.pending.settings = true;
  state.messages.settings = "";
  try {
    state.settings = await authedRequest(`/settings`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    state.messages.settings = copy("设置已保存。", "Settings saved.");
  } finally {
    state.pending.settings = false;
  }
}

export async function testModel(payload) {
  state.pending.modelTest = true;
  state.messages.settings = "";
  try {
    const result = await authedRequest(`/settings/test-model`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    state.messages.settings = copy(
      `连接成功，耗时 ${result.latency_ms} ms。返回示例：${result.preview}`,
      `Connection OK in ${result.latency_ms} ms. Preview: ${result.preview}`
    );
  } finally {
    state.pending.modelTest = false;
  }
}

export async function createUser(payload) {
  state.pending.userCreate = true;
  state.messages.users = "";
  try {
    await authedRequest("/users", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    await loadUsersPage();
    state.messages.users = copy("用户已创建。", "User created.");
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

function loadPreviewDocuments(jobId, revision) {
  const version = revision ? `?rev=${encodeURIComponent(revision)}` : "";
  revokePreviewDocumentUrls();
  state.previewDocuments.sourceUrl = apiPath(`/jobs/${jobId}/documents/source`);
  state.previewDocuments.translatedUrl = apiPath(`/jobs/${jobId}/documents/translated${version}`);
}

function refreshTranslatedPreviewDocument(jobId, revision) {
  const version = revision ? `?rev=${encodeURIComponent(revision)}` : "";
  revokePreviewDocumentUrl("translatedUrl");
  state.previewDocuments.translatedUrl = apiPath(`/jobs/${jobId}/documents/translated${version}`);
}

export async function loadPreview(jobId) {
  state.pending.preview = true;
  state.messages.preview = "";
  try {
    clearPreviewState();
    const job = await authedRequest(`/jobs/${jobId}`);
    if (!job.output_file || job.status !== "completed") {
      throw new Error(copy("翻译完成后才可预览。", "Preview is available after translation completes."));
    }

    const preview = await authedRequest(`/jobs/${jobId}/preview`);
    state.previewJob = job;
    state.previewData = preview;
    state.previewDraft = clonePreview(preview);
    state.previewMode = "view";

    if (preview.document_kind === "pdf") {
      loadPreviewDocuments(jobId, preview.updated_at);
    }
  } finally {
    state.pending.preview = false;
  }
}

export function setPreviewMode(mode) {
  state.previewMode = mode;
  state.messages.preview = "";
}

export async function savePreview() {
  if (!state.previewJob || !state.previewDraft || !previewDirty.value) {
    return;
  }

  state.pending.previewSave = true;
  state.messages.preview = "";
  try {
    const payload =
      state.previewDraft.document_kind === "pdf"
        ? {
            status: "validated",
            payload: previewEditablePayload(),
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
    state.previewDraft = clonePreview(preview);
    if (preview.document_kind === "pdf") {
      refreshTranslatedPreviewDocument(state.previewJob.id, preview.updated_at);
    }
    state.messages.preview = copy("修改已保存。", "Edits saved.");
  } finally {
    state.pending.previewSave = false;
  }
}

export function defaultUploadState() {
  return {
    sourceLanguage: DEFAULT_SOURCE_LANGUAGE,
    targetLanguage: DEFAULT_TARGET_LANGUAGE,
  };
}
