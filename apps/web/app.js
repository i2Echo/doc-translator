const API_BASE = "/api/v1";
const STORAGE_KEY = "doc-translator-token";
const UI_LANGUAGE_KEY = "doc-translator-ui-language";
const POLL_INTERVAL_MS = 5000;
const ADMIN_PAGES = ["settings", "users", "storage", "audit"];
const PREVIEW_ZOOM_STEP = 25;
const PREVIEW_MIN_ZOOM = 50;
const PREVIEW_MAX_ZOOM = 200;
const PREVIEW_MAX_RENDER_DPR = 2;
const PREVIEW_TABLE_MIN_FONT_SIZE = 7;
const PREVIEW_TECHNICAL_FONT_STACK = '"Courier New", Arial, "SimSun", "Microsoft YaHei", sans-serif';
const customSelects = new Map();

const UI_COPY = {
  "zh-CN": {
    heroEyebrow: "私有部署文档翻译",
    heroTitle: "翻译文档，在线校对，并保持文件始终在你的控制之下。",
    heroCopy: "原文与译文保存在你自己的存储中。若模型端点位于外部，翻译时文本会按设计发送到该模型服务。",
    heroPillPreview: "预览 + 编辑",
    heroPillJobs: "异步任务",
    heroPillAudit: "审计记录",
    authKicker: "本地登录",
    authTitle: "进入翻译工作台",
    authCopy: "使用部署环境中创建的本地账号登录。",
    emailLabel: "邮箱",
    passwordLabel: "密码",
    signIn: "登录",
    workspace: "工作台",
    admin: "管理",
    refresh: "刷新",
    logout: "退出",
    dropTitle: "拖拽文件到这里",
    dropCopy: "支持 PDF 和 DOCX 上传。",
    browseFiles: "选择文件",
    sourceLanguage: "源语言:",
    targetLanguage: "目标语言:",
    model: "选择模型:",
    moreSettings: "更多设置",
    glossary: "术语表:",
    translationStyle: "翻译风格:",
    glossaryPlaceholder: "请选择",
    toggleImages: "翻译 PDF 图片",
    toggleFormula: "公式识别增强",
    toggleEmail: "邮件通知",
    togglePriority: "优先队列",
    clear: "清空",
    startTranslation: "开始翻译",
    noActiveTasks: "暂无活动任务",
    activeTasks: (count) => `${count} 个进行中的任务`,
    maxParallel: (count) => `最多 ${count} 个并行任务`,
    noJobs: "还没有任务，上传 PDF 或 DOCX 后会显示在这里。",
    preview: "预览",
    download: "下载",
    retryTranslation: "重试翻译",
    refreshProgress: "刷新进度",
    cancel: "取消",
    completedAt: (date) => `完成于 ${date}`,
    progressMeta: (progress, date) => `进度 ${progress}% · ${date}`,
    translationInProgress: "翻译进行中",
    pendingCleanup: "等待清理",
    hoursUntilDeletion: (hours) => `${hours} 小时后删除`,
    daysUntilDeletion: (days) => `${days} 天后删除`,
    selectedFile: "已选文件",
    back: "返回",
    edit: "编辑",
    close: "关闭",
    saveEdits: "保存修改",
    previewUnavailable: "当前浏览器无法显示 PDF 预览。",
    status: {
      queued: "排队中",
      uploaded: "已上传",
      parsing: "解析中",
      translating: "翻译中",
      rebuilding: "重建中",
      ocr_running: "OCR 中",
      completed: "已完成",
      failed: "失败",
      cancelled: "已取消",
    },
    languageOptions: {
      auto: "自动检测",
      English: "英语",
      Chinese: "中文",
      Japanese: "日语",
      Spanish: "西班牙语",
      French: "法语",
      German: "德语",
    },
    managedModel: "当前模型",
  },
  en: {
    heroEyebrow: "Private Deployment Document Translation",
    heroTitle: "Translate documents, review the result online, and keep the files under your control.",
    heroCopy: "Originals and translated outputs stay inside customer-controlled storage. If your model endpoint is external, text is sent there during translation by design.",
    heroPillPreview: "Preview + Edit",
    heroPillJobs: "Async Jobs",
    heroPillAudit: "Audit Trail",
    authKicker: "Local Sign-In",
    authTitle: "Access the translation workspace",
    authCopy: "Use the locally managed account created from your deployment environment.",
    emailLabel: "Email",
    passwordLabel: "Password",
    signIn: "Sign in",
    workspace: "Workspace",
    admin: "Admin",
    refresh: "Refresh",
    logout: "Log out",
    dropTitle: "Drag & drop files here",
    dropCopy: "Supports PDF and DOCX uploads.",
    browseFiles: "Browse files",
    sourceLanguage: "Source Language:",
    targetLanguage: "Target Language:",
    model: "Select Model:",
    moreSettings: "More Settings",
    glossary: "Glossary:",
    translationStyle: "Translation Style:",
    glossaryPlaceholder: "Please select",
    toggleImages: "Translate Images in PDF",
    toggleFormula: "Formula Recognition Enhancement",
    toggleEmail: "Email Notice",
    togglePriority: "Priority Queue",
    clear: "Clear",
    startTranslation: "Start Translation",
    noActiveTasks: "No active tasks",
    activeTasks: (count) => `${count} active tasks`,
    maxParallel: (count) => `Maximum ${count} parallel tasks`,
    noJobs: "No jobs yet. Upload a PDF or DOCX to start.",
    preview: "Preview",
    download: "Download",
    retryTranslation: "Retry translation",
    refreshProgress: "Refresh progress",
    cancel: "Cancel",
    completedAt: (date) => `Completed ${date}`,
    progressMeta: (progress, date) => `Progress ${progress}% · ${date}`,
    translationInProgress: "Translation in progress",
    pendingCleanup: "Pending cleanup",
    hoursUntilDeletion: (hours) => `${hours} hours until deletion`,
    daysUntilDeletion: (days) => `${days} days until deletion`,
    selectedFile: "Selected file",
    back: "Back",
    edit: "Edit",
    close: "Close",
    saveEdits: "Save edits",
    previewUnavailable: "PDF preview is unavailable in this browser.",
    status: {
      queued: "Queued",
      uploaded: "Uploaded",
      parsing: "Parsing",
      translating: "Translating",
      rebuilding: "Rebuilding",
      ocr_running: "OCR running",
      completed: "Completed",
      failed: "Failed",
      cancelled: "Cancelled",
    },
    languageOptions: {
      auto: "Auto detect",
      English: "English",
      Chinese: "Chinese",
      Japanese: "Japanese",
      Spanish: "Spanish",
      French: "French",
      German: "German",
    },
    managedModel: "Managed model",
  },
};

const state = {
  token: window.localStorage.getItem(STORAGE_KEY),
  uiLanguage: window.localStorage.getItem(UI_LANGUAGE_KEY) || "zh-CN",
  user: null,
  jobs: [],
  selectedJobId: null,
  pollHandle: null,
  previewJob: null,
  previewJobId: null,
  previewText: null,
  previewBlockPages: [],
  previewActivePageId: null,
  previewSearchQuery: "",
  previewReplaceValue: "",
  previewReplaceOpen: false,
  previewMode: "view",
  previewDirty: false,
  previewDocuments: {
    sourceUrl: null,
    translatedUrl: null,
    sourceData: null,
    translatedData: null,
  },
  previewPdfDocs: {
    source: null,
    translated: null,
  },
  previewPdfLoadingTasks: {
    source: null,
    translated: null,
  },
  previewRenderVersion: {
    source: 0,
    translated: 0,
  },
  previewScrollRatio: {
    source: 0,
    translated: 0,
  },
  previewScrollLock: null,
  previewZoom: {
    source: 100,
    translated: 100,
  },
  workspaceMoreSettingsOpen: true,
  runtimeProfile: {
    modelName: "",
    maxConcurrentJobs: 2,
    retentionDays: 7,
  },
  adminPage: "settings",
};

const els = {
  hero: document.getElementById("hero"),
  authPanel: document.getElementById("auth-panel"),
  dashboard: document.getElementById("dashboard"),
  appHeader: document.querySelector(".app-header"),
  workspaceHomeButton: document.getElementById("workspace-home-button"),
  adminEntryButton: document.getElementById("admin-entry-button"),
  workspaceView: document.getElementById("workspace-view"),
  previewView: document.getElementById("preview-view"),
  adminView: document.getElementById("admin-view"),
  loginForm: document.getElementById("login-form"),
  loginEmail: document.getElementById("login-email"),
  loginPassword: document.getElementById("login-password"),
  loginError: document.getElementById("login-error"),
  userBadge: document.getElementById("user-badge"),
  refreshButton: document.getElementById("refresh-button"),
  logoutButton: document.getElementById("logout-button"),
  uiLanguageSelect: document.getElementById("ui-language-select"),
  uploadForm: document.getElementById("upload-form"),
  uploadFile: document.getElementById("upload-file"),
  dropZone: document.getElementById("drop-zone"),
  browseFilesButton: document.getElementById("browse-files-button"),
  clearFileButton: document.getElementById("clear-file-button"),
  selectedFile: document.getElementById("selected-file"),
  selectedFileName: document.getElementById("selected-file-name"),
  selectedFileMeta: document.getElementById("selected-file-meta"),
  sourceLanguage: document.getElementById("source-language"),
  targetLanguage: document.getElementById("target-language"),
  moreSettingsButton: document.getElementById("more-settings-button"),
  workspaceMoreSettings: document.getElementById("workspace-more-settings"),
  uploadMessage: document.getElementById("upload-message"),
  queueSummary: document.getElementById("queue-summary"),
  parallelSummary: document.getElementById("parallel-summary"),
  workspaceModelName: document.getElementById("workspace-model-name"),
  jobsList: document.getElementById("jobs-list"),
  jobsScrollPrev: document.getElementById("jobs-scroll-prev"),
  jobsScrollNext: document.getElementById("jobs-scroll-next"),
  jobCount: document.getElementById("job-count"),
  jobDetail: document.getElementById("job-detail"),
  detailStatus: document.getElementById("detail-status"),
  previewBackButton: document.getElementById("preview-back-button"),
  previewFileKind: document.getElementById("preview-file-kind"),
  previewTitle: document.getElementById("preview-title"),
  previewSubtitle: document.getElementById("preview-subtitle"),
  previewEditToggle: document.getElementById("preview-edit-toggle"),
  previewSaveButton: document.getElementById("preview-save-button"),
  previewDownloadButton: document.getElementById("preview-download-button"),
  previewNote: document.getElementById("preview-note"),
  previewMessage: document.getElementById("preview-message"),
  previewStage: document.getElementById("preview-stage"),
  adminPageTitle: document.getElementById("admin-page-title"),
  adminPageCopy: document.getElementById("admin-page-copy"),
  settingsForm: document.getElementById("settings-form"),
  settingsMessage: document.getElementById("settings-message"),
  settingsPrivacy: document.getElementById("settings-privacy"),
  testModelButton: document.getElementById("test-model-button"),
  createUserForm: document.getElementById("create-user-form"),
  userMessage: document.getElementById("user-message"),
  usersList: document.getElementById("users-list"),
  storageSummary: document.getElementById("storage-summary"),
  auditList: document.getElementById("audit-list"),
};

const settingsFields = {
  model_base_url: document.getElementById("settings-model-base-url"),
  model_api_key: document.getElementById("settings-model-api-key"),
  model_name: document.getElementById("settings-model-name"),
  model_timeout_seconds: document.getElementById("settings-model-timeout"),
  storage_mode: document.getElementById("settings-storage-mode"),
  local_storage_path: document.getElementById("settings-storage-path"),
  file_retention_days: document.getElementById("settings-retention-days"),
  max_upload_mb: document.getElementById("settings-max-upload"),
  max_concurrent_jobs: document.getElementById("settings-max-concurrency"),
  ocr_language_hint: document.getElementById("settings-ocr-language"),
  ocr_enabled: document.getElementById("settings-ocr-enabled"),
};

const adminNavButtons = Array.from(document.querySelectorAll(".admin-nav-button"));
const adminPages = {
  settings: document.getElementById("admin-page-settings"),
  users: document.getElementById("admin-page-users"),
  storage: document.getElementById("admin-page-storage"),
  audit: document.getElementById("admin-page-audit"),
};

const adminPageMeta = {
  settings: {
    title: "Settings",
    copy: "Model endpoint, OCR behavior, retention, and concurrency controls.",
  },
  users: {
    title: "Users",
    copy: "Local account management without mixing it into the translation workspace.",
  },
  storage: {
    title: "Storage",
    copy: "Current capacity snapshot for source and translated files.",
  },
  audit: {
    title: "Audit",
    copy: "Recent activity across authentication, settings, jobs, and retention cleanup.",
  },
};

function t(key, ...args) {
  const dictionary = UI_COPY[state.uiLanguage] || UI_COPY.en;
  const value = key.split(".").reduce((current, part) => current?.[part], dictionary);
  if (typeof value === "function") {
    return value(...args);
  }
  return value ?? key;
}

function persistUiLanguage(language) {
  state.uiLanguage = language;
  window.localStorage.setItem(UI_LANGUAGE_KEY, language);
}

function updateLanguageOptions(select) {
  Array.from(select.options).forEach((option) => {
    if (option.value in t("languageOptions")) {
      option.textContent = t(`languageOptions.${option.value}`);
    }
  });
}

function closeAllCustomSelects() {
  customSelects.forEach((instance) => {
    instance.wrapper.classList.remove("is-open");
    instance.menu.classList.add("hidden");
  });
}

function renderCustomSelect(select) {
  const instance = customSelects.get(select.id);
  if (!instance) {
    return;
  }

  const selectedOption = select.options[select.selectedIndex];
  instance.value.textContent = selectedOption?.textContent || "";
  instance.trigger.disabled = select.disabled;
  instance.menu.innerHTML = Array.from(select.options)
    .map(
      (option) => `
        <button
          type="button"
          class="custom-select-option ${option.selected ? "is-selected" : ""}"
          data-value="${escapeHtml(option.value)}"
        >
          ${escapeHtml(option.textContent)}
        </button>
      `
    )
    .join("");
}

function enhanceSelect(select) {
  if (!select.id || customSelects.has(select.id)) {
    return;
  }

  const wrapper = document.createElement("div");
  wrapper.className = "custom-select";

  const trigger = document.createElement("button");
  trigger.type = "button";
  trigger.className = "custom-select-trigger";
  trigger.innerHTML = `
    <span class="custom-select-value"></span>
    <span class="custom-select-chevron" aria-hidden="true">
      <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">
        <path d="m4 6 4 4 4-4"></path>
      </svg>
    </span>
  `;

  const menu = document.createElement("div");
  menu.className = "custom-select-menu hidden";

  const parent = select.parentNode;
  parent.insertBefore(wrapper, select);
  wrapper.append(select, trigger, menu);
  select.classList.add("custom-select-native");

  const value = trigger.querySelector(".custom-select-value");
  customSelects.set(select.id, { wrapper, trigger, menu, value, select });
  renderCustomSelect(select);

  trigger.addEventListener("click", (event) => {
    event.preventDefault();
    const shouldOpen = !wrapper.classList.contains("is-open");
    closeAllCustomSelects();
    wrapper.classList.toggle("is-open", shouldOpen);
    menu.classList.toggle("hidden", !shouldOpen);
  });

  menu.addEventListener("click", (event) => {
    const optionButton = event.target.closest("button[data-value]");
    if (!optionButton) {
      return;
    }

    if (select.value !== optionButton.dataset.value) {
      select.value = optionButton.dataset.value;
      select.dispatchEvent(new Event("change", { bubbles: true }));
    }
    closeAllCustomSelects();
  });

  select.addEventListener("change", () => {
    renderCustomSelect(select);
  });
}

function enhanceSelects() {
  Array.from(document.querySelectorAll("select")).forEach((select) => {
    enhanceSelect(select);
  });
}

function refreshCustomSelects() {
  customSelects.forEach(({ select }) => {
    renderCustomSelect(select);
  });
}

function applyUiLanguage() {
  document.documentElement.lang = state.uiLanguage === "zh-CN" ? "zh-CN" : "en";
  els.uiLanguageSelect.value = state.uiLanguage;
  document.getElementById("hero-eyebrow").textContent = t("heroEyebrow");
  document.getElementById("hero-title").textContent = t("heroTitle");
  document.getElementById("hero-copy").textContent = t("heroCopy");
  document.getElementById("hero-pill-preview").textContent = t("heroPillPreview");
  document.getElementById("hero-pill-jobs").textContent = t("heroPillJobs");
  document.getElementById("hero-pill-audit").textContent = t("heroPillAudit");
  document.getElementById("auth-kicker").textContent = t("authKicker");
  document.getElementById("auth-title").textContent = t("authTitle");
  document.getElementById("auth-copy").textContent = t("authCopy");
  document.getElementById("login-email-label").textContent = t("emailLabel");
  document.getElementById("login-password-label").textContent = t("passwordLabel");
  document.getElementById("login-submit-button").textContent = t("signIn");
  els.workspaceHomeButton.textContent = t("workspace");
  els.adminEntryButton.textContent = t("admin");
  els.refreshButton.textContent = t("refresh");
  els.logoutButton.textContent = t("logout");
  document.getElementById("drop-zone-title").textContent = t("dropTitle");
  document.getElementById("drop-zone-copy").textContent = t("dropCopy");
  els.browseFilesButton.textContent = t("browseFiles");
  document.getElementById("source-language-label").textContent = t("sourceLanguage");
  document.getElementById("target-language-label").textContent = t("targetLanguage");
  document.getElementById("model-label").textContent = t("model");
  document.getElementById("more-settings-text").textContent = t("moreSettings");
  document.getElementById("glossary-label").textContent = t("glossary");
  document.getElementById("translation-style-label").textContent = t("translationStyle");
  document.getElementById("toggle-images-label").textContent = t("toggleImages");
  document.getElementById("toggle-formula-label").textContent = t("toggleFormula");
  document.getElementById("toggle-email-label").textContent = t("toggleEmail");
  document.getElementById("toggle-priority-label").textContent = t("togglePriority");
  els.clearFileButton.textContent = t("clear");
  document.getElementById("start-translation-button").textContent = t("startTranslation");
  document.getElementById("selected-file").querySelector(".selected-file-label").textContent = t("selectedFile");
  els.previewBackButton.setAttribute("aria-label", t("back"));
  els.previewBackButton.title = t("back");
  els.previewDownloadButton.textContent = t("download");
  els.previewSaveButton.textContent = t("saveEdits");

  updateLanguageOptions(els.sourceLanguage);
  updateLanguageOptions(els.targetLanguage);
  const glossaryPlaceholder = els.workspaceMoreSettings.querySelector("#workspace-glossary option");
  const translationStylePlaceholder = els.workspaceMoreSettings.querySelector("#workspace-translation-style option");
  glossaryPlaceholder.textContent = t("glossaryPlaceholder");
  translationStylePlaceholder.textContent = t("glossaryPlaceholder");
  refreshCustomSelects();
  renderWorkspaceRuntime();
  renderJobs();
  syncPreviewToolbar();
  if (state.previewJob) {
    renderPreviewStage();
  }
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function formatDate(value) {
  if (!value) {
    return "Not yet";
  }
  return new Date(value).toLocaleString();
}

function formatBytes(value) {
  if (value < 1024) {
    return `${value} B`;
  }
  const units = ["KB", "MB", "GB", "TB"];
  let size = value;
  let unitIndex = -1;
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024;
    unitIndex += 1;
  }
  return `${size.toFixed(size >= 10 ? 0 : 1)} ${units[unitIndex]}`;
}

function formatRetentionCountdown(job) {
  if (!job.completed_at) {
    return t("translationInProgress");
  }

  const expiresAt =
    new Date(job.completed_at).getTime() + state.runtimeProfile.retentionDays * 24 * 60 * 60 * 1000;
  const remainingMs = expiresAt - Date.now();
  if (remainingMs <= 0) {
    return t("pendingCleanup");
  }

  const remainingHours = Math.max(1, Math.round(remainingMs / (60 * 60 * 1000)));
  if (remainingHours < 48) {
    return t("hoursUntilDeletion", remainingHours);
  }

  const remainingDays = Math.ceil(remainingMs / (24 * 60 * 60 * 1000));
  return t("daysUntilDeletion", remainingDays);
}

function statusClass(status) {
  return `status-pill status-${status}`;
}

function statusLabel(status) {
  return t(`status.${status}`);
}

function documentKind(fileName) {
  return fileName.toLowerCase().endsWith(".docx") ? "docx" : "pdf";
}

function formatLanguageName(value) {
  const translated = t(`languageOptions.${value}`);
  return translated === `languageOptions.${value}` ? value : translated;
}

function previewCopy(zh, en) {
  return state.uiLanguage === "zh-CN" ? zh : en;
}

function setMessage(element, text, isError = false) {
  element.textContent = text || "";
  element.classList.toggle("error", Boolean(isError));
  if (element === els.previewMessage) {
    syncPreviewInfoRow();
  }
}

function parseRoute() {
  const previewMatch = /^\/preview\/([^/]+)$/.exec(window.location.pathname);
  if (previewMatch) {
    return { view: "preview", jobId: decodeURIComponent(previewMatch[1]) };
  }

  const adminMatch = /^\/admin\/(settings|users|storage|audit)$/.exec(window.location.pathname);
  if (adminMatch) {
    return { view: "admin", adminPage: adminMatch[1] };
  }

  return { view: "workspace" };
}

function updateQueueSummary() {
  const activeCount = state.jobs.filter((job) =>
    ["queued", "parsing", "ocr_running", "translating", "rebuilding"].includes(job.status)
  ).length;
  els.queueSummary.textContent = activeCount ? t("activeTasks", activeCount) : t("noActiveTasks");
  els.parallelSummary.textContent = t("maxParallel", state.runtimeProfile.maxConcurrentJobs);
}

function renderWorkspaceRuntime() {
  const derivedModelName =
    state.runtimeProfile.modelName ||
    state.jobs.find((job) => job.model_name_snapshot)?.model_name_snapshot ||
    t("managedModel");
  els.workspaceModelName.textContent = derivedModelName;
}

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (state.token) {
    headers.set("Authorization", `Bearer ${state.token}`);
  }

  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers,
  });

  if (!response.ok) {
    let message = "Request failed";
    try {
      const data = await response.json();
      message = data.detail || JSON.stringify(data);
    } catch {
      message = response.statusText || message;
    }
    throw new Error(message);
  }

  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    return response.json();
  }
  return response;
}

function persistToken(token) {
  state.token = token;
  window.localStorage.setItem(STORAGE_KEY, token);
}

function revokePreviewDocuments() {
  resetPreviewPdfState();
  [state.previewDocuments.sourceUrl, state.previewDocuments.translatedUrl].forEach((url) => {
    if (url) {
      URL.revokeObjectURL(url);
    }
  });
  state.previewDocuments = {
    sourceUrl: null,
    translatedUrl: null,
    sourceData: null,
    translatedData: null,
  };
}

function clearPreviewState() {
  revokePreviewDocuments();
  if (previewResizeTimer) {
    window.clearTimeout(previewResizeTimer);
    previewResizeTimer = null;
  }
  state.previewJob = null;
  state.previewJobId = null;
  state.previewText = null;
  state.previewBlockPages = [];
  state.previewActivePageId = null;
  state.previewSearchQuery = "";
  state.previewReplaceValue = "";
  state.previewReplaceOpen = false;
  state.previewMode = "view";
  state.previewDirty = false;
  state.previewZoom = {
    source: 100,
    translated: 100,
  };
  els.previewStage.innerHTML = "";
  setMessage(els.previewMessage, "");
}

function clearSession() {
  state.token = null;
  state.user = null;
  state.jobs = [];
  state.selectedJobId = null;
  window.localStorage.removeItem(STORAGE_KEY);
  if (state.pollHandle) {
    window.clearInterval(state.pollHandle);
    state.pollHandle = null;
  }
  clearPreviewState();
  if (window.location.pathname !== "/") {
    window.history.replaceState({}, "", "/");
  }
  renderAuthState();
}

function renderSelectedFile() {
  const file = els.uploadFile.files?.[0];
  if (!file) {
    els.selectedFile.classList.add("hidden");
    els.selectedFileName.textContent = "";
    els.selectedFileMeta.textContent = "";
    return;
  }

  els.selectedFile.classList.remove("hidden");
  els.selectedFileName.textContent = file.name;
  els.selectedFileMeta.textContent = `${documentKind(file.name).toUpperCase()} · ${formatBytes(file.size)}`;
}

function renderAuthState() {
  const signedIn = Boolean(state.user);
  document.body.classList.toggle("is-authenticated", signedIn);
  els.hero.classList.toggle("hidden", signedIn);
  els.authPanel.classList.toggle("hidden", signedIn);
  els.dashboard.classList.toggle("hidden", !signedIn);
  if (signedIn) {
    els.userBadge.textContent = `${state.user.full_name} · ${state.user.role}`;
  }
}

function renderHeader(route) {
  const signedIn = Boolean(state.user);
  if (!signedIn) {
    els.appHeader.classList.add("hidden");
    return;
  }

  const isPreview = route.view === "preview";
  els.appHeader.classList.toggle("hidden", isPreview);
  els.workspaceHomeButton.classList.toggle("hidden", route.view === "workspace");
  els.adminEntryButton.classList.toggle("hidden", state.user.role !== "admin" || route.view === "admin");
}

function renderWorkspaceMoreSettings() {
  els.workspaceMoreSettings.classList.toggle("hidden", !state.workspaceMoreSettingsOpen);
  els.moreSettingsButton.setAttribute("aria-expanded", String(state.workspaceMoreSettingsOpen));
}

function renderIcon(name) {
  if (name === "preview") {
    return `
      <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
        <path d="M1.4 8s2.4-4 6.6-4 6.6 4 6.6 4-2.4 4-6.6 4-6.6-4-6.6-4Z"></path>
        <circle cx="8" cy="8" r="1.8"></circle>
      </svg>
    `;
  }
  if (name === "download") {
    return `
      <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
        <path d="M8 2.5v7"></path>
        <path d="m5.3 6.8 2.7 2.7 2.7-2.7"></path>
        <path d="M2.5 12.5h11"></path>
      </svg>
    `;
  }
  if (name === "cancel") {
    return `
      <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
        <path d="M4 4l8 8"></path>
        <path d="M12 4 4 12"></path>
      </svg>
    `;
  }
  if (name === "retry") {
    return `
      <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
        <path d="M13 7.2A5 5 0 1 0 8 13"></path>
        <path d="M13 3.5v3.7H9.3"></path>
      </svg>
    `;
  }
  return "";
}

function renderJobs() {
  els.jobCount.textContent = `${state.jobs.length} ${state.jobs.length === 1 ? "job" : "jobs"}`;
  updateQueueSummary();
  renderWorkspaceRuntime();

  if (!state.jobs.length) {
    els.jobsList.innerHTML = `<div class="empty-strip">${escapeHtml(t("noJobs"))}</div>`;
    return;
  }

  els.jobsList.innerHTML = state.jobs
    .map((job) => {
      const isCompleted = job.status === "completed";
      const canCancel = ["queued", "parsing", "ocr_running", "translating", "rebuilding"].includes(job.status);
      const canRetry = ["failed", "cancelled"].includes(job.status);
      const canDownload = Boolean(job.output_file) && isCompleted;
      const canPreview = canDownload;
      const kind = documentKind(job.input_file.original_name).toUpperCase();
      const primaryAction = canPreview ? "preview" : canRetry ? "retry" : "refresh";
      const primaryLabel = canPreview ? t("preview") : canRetry ? t("retryTranslation") : t("refreshProgress");
      const progressMarkup = isCompleted
        ? `<div class="job-card-meta">${escapeHtml(t("completedAt", formatDate(job.completed_at)))}</div>`
        : `
          <div class="progress-bar"><div class="progress-fill" style="width: ${job.progress}%"></div></div>
          <div class="job-card-meta">${escapeHtml(t("progressMeta", job.progress, formatDate(job.created_at)))}</div>
        `;

      return `
        <article class="job-card">
          <div class="job-card-status">
            <span class="${statusClass(job.status)}">${escapeHtml(statusLabel(job.status))}</span>
          </div>
          <div class="job-card-file">
            <div class="job-file-icon"><span>${kind}</span></div>
            <div class="job-card-copy">
              <h4 title="${escapeHtml(job.input_file.original_name)}">${escapeHtml(job.input_file.original_name)}</h4>
              <div class="meta-line">${escapeHtml(formatLanguageName(job.source_language))} → ${escapeHtml(formatLanguageName(job.target_language))}</div>
            </div>
          </div>
          ${progressMarkup}
          <div class="job-card-footer">
            <div class="job-card-retention">${escapeHtml(formatRetentionCountdown(job))}</div>
            <div class="job-card-actions">
              ${canPreview ? `<button data-action="preview" data-job-id="${job.id}" class="job-icon-button" type="button" aria-label="${escapeHtml(t("preview"))}">${renderIcon("preview")}</button>` : ""}
              ${canDownload ? `<button data-action="download" data-job-id="${job.id}" class="job-icon-button" type="button" aria-label="${escapeHtml(t("download"))}">${renderIcon("download")}</button>` : ""}
              ${canCancel ? `<button data-action="cancel" data-job-id="${job.id}" class="job-icon-button" type="button" aria-label="${escapeHtml(t("cancel"))}">${renderIcon("cancel")}</button>` : ""}
              ${canRetry ? `<button data-action="retry" data-job-id="${job.id}" class="job-icon-button" type="button" aria-label="${escapeHtml(t("retryTranslation"))}">${renderIcon("retry")}</button>` : ""}
            </div>
          </div>
          <button data-action="${primaryAction}" data-job-id="${job.id}" class="job-primary-button" type="button">${escapeHtml(primaryLabel)}</button>
        </article>
      `;
    })
    .join("");
}

function renderJobDetail(job) {
  if (!job) {
    els.detailStatus.textContent = "No selection";
    els.jobDetail.className = "job-detail empty-state";
    els.jobDetail.textContent = "Pick a job to inspect progress, events, and download availability.";
    return;
  }

  const events = [...job.events].sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
  const canPreview = Boolean(job.output_file) && job.status === "completed";
  const canDownload = canPreview;

  els.detailStatus.textContent = statusLabel(job.status);
  els.jobDetail.className = "job-detail detail-layout";
  els.jobDetail.innerHTML = `
    <div class="detail-summary">
      <div class="detail-heading">
        <strong>${escapeHtml(job.input_file.original_name)}</strong>
        <span class="${statusClass(job.status)}">${escapeHtml(statusLabel(job.status))}</span>
      </div>
      <div class="meta-line">${escapeHtml(job.source_language)} → ${escapeHtml(job.target_language)} · Model ${escapeHtml(job.model_name_snapshot)}</div>
      <div class="meta-line">Started ${escapeHtml(formatDate(job.started_at))} · Completed ${escapeHtml(formatDate(job.completed_at))}</div>
      <div class="detail-actions">
        ${canPreview ? `<button data-action="preview" data-job-id="${job.id}" class="primary-button" type="button">Preview</button>` : ""}
        ${canDownload ? `<button data-action="download" data-job-id="${job.id}" class="ghost-button" type="button">Download</button>` : ""}
      </div>
      ${
        job.error_message
          ? `<div class="detail-error">${escapeHtml(job.error_message)}</div>`
          : ""
      }
    </div>
    <div class="timeline">
      ${events
        .map(
          (event) => `
        <div class="timeline-item">
          <div class="timeline-row">
            <strong>${escapeHtml(event.message)}</strong>
            <span class="meta-line">${escapeHtml(formatDate(event.created_at))}</span>
          </div>
          <div class="event-copy">${escapeHtml(event.details ? JSON.stringify(event.details) : "")}</div>
        </div>
      `
        )
        .join("")}
    </div>
  `;
}

function renderUsers(users) {
  if (!users.length) {
    els.usersList.innerHTML = `<div class="empty-state">No users found.</div>`;
    return;
  }

  els.usersList.innerHTML = users
    .map(
      (user) => `
      <article class="user-card">
        <div class="user-card-header">
          <div>
            <h4>${escapeHtml(user.full_name)}</h4>
            <div class="meta-line">${escapeHtml(user.email)}</div>
          </div>
          <span class="${statusClass(user.is_active ? "completed" : "failed")}">${escapeHtml(user.role)} · ${
            user.is_active ? "active" : "inactive"
          }</span>
        </div>
        <div class="user-actions">
          <button type="button" class="ghost-button" data-user-action="toggle-active" data-user-id="${user.id}" data-user-active="${user.is_active}">
            ${user.is_active ? "Disable" : "Enable"}
          </button>
          <button type="button" class="ghost-button" data-user-action="toggle-role" data-user-id="${user.id}" data-user-role="${user.role}">
            ${user.role === "admin" ? "Make user" : "Make admin"}
          </button>
        </div>
      </article>
    `
    )
    .join("");
}

function renderStorage(summary) {
  const items = [
    ["Active files", summary.active_file_count],
    ["Input files", summary.input_file_count],
    ["Output files", summary.output_file_count],
    ["Deleted files", summary.deleted_file_count],
    ["Stored bytes", formatBytes(summary.total_bytes)],
  ];

  els.storageSummary.innerHTML = items
    .map(
      ([label, value]) => `
      <div class="metric-card">
        <span class="meta-line">${escapeHtml(label)}</span>
        <strong>${escapeHtml(value)}</strong>
      </div>
    `
    )
    .join("");
}

function renderAudit(logs) {
  if (!logs.length) {
    els.auditList.innerHTML = `<div class="empty-state">No audit activity yet.</div>`;
    return;
  }

  els.auditList.innerHTML = logs
    .map(
      (log) => `
      <article class="audit-card-item">
        <div class="audit-row">
          <strong>${escapeHtml(log.action)}</strong>
          <span class="meta-line">${escapeHtml(formatDate(log.created_at))}</span>
        </div>
        <div class="audit-copy">
          ${escapeHtml(log.actor ? `${log.actor.full_name} · ` : "")}${escapeHtml(log.entity_type)}${
            log.entity_id ? ` · ${escapeHtml(log.entity_id)}` : ""
          }
        </div>
        <div class="audit-copy">${escapeHtml(log.details ? JSON.stringify(log.details) : "")}</div>
      </article>
    `
    )
    .join("");
}

function fillSettings(settings) {
  state.runtimeProfile = {
    modelName: settings.model_name || state.runtimeProfile.modelName,
    maxConcurrentJobs: settings.max_concurrent_jobs || state.runtimeProfile.maxConcurrentJobs,
    retentionDays: settings.file_retention_days || state.runtimeProfile.retentionDays,
  };
  Object.entries(settingsFields).forEach(([key, element]) => {
    if (element.type === "checkbox") {
      element.checked = Boolean(settings[key]);
    } else {
      element.value = settings[key] ?? "";
    }
  });
  els.settingsPrivacy.textContent = settings.privacy_notice || "";
  renderWorkspaceRuntime();
  updateQueueSummary();
}

function renderAdminPage(page) {
  state.adminPage = page;
  const meta = adminPageMeta[page];
  els.adminPageTitle.textContent = meta.title;
  els.adminPageCopy.textContent = meta.copy;

  ADMIN_PAGES.forEach((name) => {
    adminPages[name].classList.toggle("hidden", name !== page);
  });
  adminNavButtons.forEach((button) => {
    button.classList.toggle("active", button.dataset.adminRoute === page);
  });
}

function syncPreviewInfoRow() {
  const infoRow = els.previewNote.parentElement;
  const hasNote = !els.previewNote.classList.contains("hidden") && Boolean(els.previewNote.textContent.trim());
  const hasMessage = Boolean(els.previewMessage.textContent.trim());
  infoRow.classList.toggle("hidden", !hasNote && !hasMessage);
}

function syncPreviewToolbar() {
  const editing = state.previewMode === "edit";
  els.previewEditToggle.textContent = editing ? t("close") : t("edit");
  els.previewSaveButton.classList.toggle("hidden", !editing);
  els.previewSaveButton.disabled = !editing || !state.previewDirty;
  els.previewNote.classList.add("hidden");
  els.previewNote.textContent = "";
  els.previewBackButton.setAttribute("aria-label", t("back"));
  els.previewBackButton.title = t("back");
  els.previewDownloadButton.textContent = t("download");
  els.previewSaveButton.textContent = t("saveEdits");
  if (state.previewJob) {
    els.previewFileKind.textContent = documentKind(state.previewJob.input_file.original_name).toUpperCase();
  }
  if (editing && state.previewJob && documentKind(state.previewJob.input_file.original_name) === "pdf") {
    const totalOverflowCount = countPreviewOverflowBlocks();
    if (totalOverflowCount) {
      const activePage = getActivePreviewBlockPage();
      const activeOverflowCount = activePage ? countPreviewOverflowBlocks([activePage]) : totalOverflowCount;
      const warningCount = activeOverflowCount || totalOverflowCount;
      els.previewNote.textContent = previewCopy(
        `仍有 ${warningCount} 个编辑区域超出边界，请缩短译文后再保存。`,
        `${warningCount} editable area${warningCount === 1 ? "" : "s"} still overflow. Shorten the translation before saving.`
      );
      els.previewNote.classList.remove("hidden");
      els.previewSaveButton.disabled = true;
    }
  }
  syncPreviewInfoRow();
}

function resetPreviewPdfState() {
  Object.values(state.previewPdfLoadingTasks).forEach((task) => {
    task?.destroy?.();
  });
  Object.values(state.previewPdfDocs).forEach((doc) => {
    doc?.destroy?.();
  });

  state.previewPdfLoadingTasks = {
    source: null,
    translated: null,
  };
  state.previewPdfDocs = {
    source: null,
    translated: null,
  };
  state.previewRenderVersion = {
    source: 0,
    translated: 0,
  };
  state.previewScrollRatio = {
    source: 0,
    translated: 0,
  };
  state.previewScrollLock = null;
}

function renderZoomControl(kind) {
  return `
    <div class="zoom-control" data-zoom-kind="${kind}">
      <button data-preview-zoom-kind="${kind}" data-preview-zoom-step="-1" type="button" aria-label="Zoom out">−</button>
      <span class="zoom-control-value" data-preview-zoom-value="${kind}">${state.previewZoom[kind]}%</span>
      <button data-preview-zoom-kind="${kind}" data-preview-zoom-step="1" type="button" aria-label="Zoom in">+</button>
    </div>
  `;
}

function renderPdfPane(kind, title) {
  return `
    <section class="pdf-pane">
      <div class="pdf-pane-toolbar">
        <span class="pdf-pane-title">${escapeHtml(title)}</span>
        ${renderZoomControl(kind)}
      </div>
      <div class="pdf-pane-body" data-pdf-scroll-kind="${kind}">
        <div class="pdf-page-stack" data-pdf-pages="${kind}">
          <div class="empty-state">${escapeHtml(previewCopy("正在加载 PDF…", "Loading PDF..."))}</div>
        </div>
      </div>
    </section>
  `;
}

let previewPdfLibPromise = null;

async function getPdfJsLib() {
  if (window.pdfjsLib?.getDocument) {
    window.pdfjsLib.GlobalWorkerOptions.workerSrc = "/vendor/pdf.worker.js";
    return window.pdfjsLib;
  }

  if (!previewPdfLibPromise) {
    previewPdfLibPromise = new Promise((resolve, reject) => {
      const finishWithLibrary = () => {
        if (!window.pdfjsLib?.getDocument) {
          return false;
        }
        window.clearTimeout(timeoutId);
        window.pdfjsLib.GlobalWorkerOptions.workerSrc = "/vendor/pdf.worker.js";
        resolve(window.pdfjsLib);
        return true;
      };

      const scriptError = () => {
        window.clearTimeout(timeoutId);
        previewPdfLibPromise = null;
        reject(new Error(previewCopy("PDF 渲染库加载失败。", "PDF renderer failed to load.")));
      };

      const pollForLibrary = () => {
        if (finishWithLibrary()) {
          return;
        }
        window.setTimeout(pollForLibrary, 80);
      };

      const timeoutId = window.setTimeout(() => {
        previewPdfLibPromise = null;
        reject(new Error(previewCopy("PDF 渲染初始化超时。", "PDF renderer initialization timed out.")));
      }, 12000);

      if (finishWithLibrary()) {
        return;
      }

      const existingScript = document.querySelector("script[data-preview-pdfjs='true']");
      if (!existingScript) {
        const script = document.createElement("script");
        script.type = "module";
        script.dataset.previewPdfjs = "true";
        script.addEventListener("error", scriptError, { once: true });
        script.textContent = `
          import * as pdfjsLib from "/vendor/pdf.js";
          window.pdfjsLib = pdfjsLib;
        `;
        document.head.append(script);
      }

      pollForLibrary();
    });
  }
  return previewPdfLibPromise;
}

async function ensurePreviewPdfLoaded(kind) {
  if (state.previewPdfDocs[kind]) {
    return state.previewPdfDocs[kind];
  }

  const data = state.previewDocuments[`${kind}Data`];
  if (!data) {
    return null;
  }

  if (!state.previewPdfLoadingTasks[kind]) {
    const pdfjs = await getPdfJsLib();
    state.previewPdfLoadingTasks[kind] = pdfjs.getDocument({
      data,
      cMapUrl: "/vendor/cmaps/",
      cMapPacked: true,
      standardFontDataUrl: "/vendor/standard_fonts/",
      disableWorker: true,
    });
  }

  const pdfDoc = await state.previewPdfLoadingTasks[kind].promise;
  state.previewPdfDocs[kind] = pdfDoc;
  return pdfDoc;
}

function getPdfPaneBody(kind) {
  return els.previewStage.querySelector(`[data-pdf-scroll-kind="${kind}"]`);
}

function getPdfPaneStack(kind) {
  return els.previewStage.querySelector(`[data-pdf-pages="${kind}"]`);
}

function updateZoomValue(kind) {
  const zoomValue = els.previewStage.querySelector(`[data-preview-zoom-value="${kind}"]`);
  if (zoomValue) {
    zoomValue.textContent = `${state.previewZoom[kind]}%`;
  }
}

function currentScrollRatio(element) {
  const maxScrollTop = element.scrollHeight - element.clientHeight;
  if (maxScrollTop <= 0) {
    return 0;
  }
  return element.scrollTop / maxScrollTop;
}

function applyScrollRatio(element, ratio) {
  const maxScrollTop = element.scrollHeight - element.clientHeight;
  if (maxScrollTop <= 0) {
    element.scrollTop = 0;
    return;
  }
  element.scrollTop = maxScrollTop * ratio;
}

function rememberPreviewScrollRatios() {
  ["source", "translated"].forEach((kind) => {
    const body = getPdfPaneBody(kind);
    if (body) {
      state.previewScrollRatio[kind] = currentScrollRatio(body);
    }
  });
}

function restorePreviewScrollRatios(kinds) {
  window.requestAnimationFrame(() => {
    kinds.forEach((kind) => {
      const body = getPdfPaneBody(kind);
      if (body) {
        applyScrollRatio(body, state.previewScrollRatio[kind]);
      }
    });
  });
}

function splitPreviewTextIntoBlocks(text, options = {}) {
  const normalized = normalizePreviewTextForBlocks(text, options);
  if (!normalized) {
    return [];
  }

  const paragraphs = normalized
    .split(/\n\s*\n+/)
    .map((part) => part.trim())
    .filter(Boolean);
  if (paragraphs.length > 1) {
    return paragraphs;
  }

  const lines = normalized
    .split("\n")
    .map((part) => part.trim())
    .filter(Boolean);
  if (lines.length <= 1) {
    return [normalized];
  }

  const segments = [];
  let current = [];
  let currentLength = 0;

  lines.forEach((line) => {
    current.push(line);
    currentLength += line.length;

    const shouldBreak =
      current.length >= 6 ||
      currentLength >= 420 ||
      (/[。！？.!?;；:]$/.test(line) && currentLength >= 260);
    if (shouldBreak) {
      segments.push(current.join("\n"));
      current = [];
      currentLength = 0;
    }
  });

  if (current.length) {
    segments.push(current.join("\n"));
  }

  return segments;
}

function previewPageNumber(page, index) {
  const match = /(\d+)/.exec(page.label || page.id || "");
  return match ? Number(match[1]) : index + 1;
}

function formatPreviewBlockPageLabel(page) {
  return previewCopy(`第 ${page.pageNumber} 页`, `Page ${page.pageNumber}`);
}

function buildPreviewPaginationItems(pageCount, activePageIndex) {
  if (pageCount <= 7) {
    return Array.from({ length: pageCount }, (_, index) => ({ type: "page", pageIndex: index + 1 }));
  }

  if (activePageIndex <= 4) {
    return [
      { type: "page", pageIndex: 1 },
      { type: "page", pageIndex: 2 },
      { type: "page", pageIndex: 3 },
      { type: "page", pageIndex: 4 },
      { type: "ellipsis", key: "after-start" },
      { type: "page", pageIndex: pageCount },
    ];
  }

  if (activePageIndex >= pageCount - 3) {
    return [
      { type: "page", pageIndex: 1 },
      { type: "ellipsis", key: "before-end" },
      { type: "page", pageIndex: pageCount - 3 },
      { type: "page", pageIndex: pageCount - 2 },
      { type: "page", pageIndex: pageCount - 1 },
      { type: "page", pageIndex: pageCount },
    ];
  }

  return [
    { type: "page", pageIndex: 1 },
    { type: "ellipsis", key: "before-active" },
    { type: "page", pageIndex: activePageIndex - 1 },
    { type: "page", pageIndex: activePageIndex },
    { type: "page", pageIndex: activePageIndex + 1 },
    { type: "ellipsis", key: "after-active" },
    { type: "page", pageIndex: pageCount },
  ];
}

function isCjkCharacter(value) {
  return /[\u3400-\u9fff]/.test(value || "");
}

function normalizePreviewTextForBlocks(text, options = {}) {
  const { preserveCompactLineBreaks = false } = options;
  const normalized = String(text || "").replaceAll("\r\n", "\n").trim();
  if (!normalized) {
    return "";
  }

  return normalized
    .split(/\n\s*\n+/)
    .map((paragraph) => {
      const lines = paragraph
        .split("\n")
        .map((part) => part.trim())
        .filter(Boolean);
      if (!lines.length) {
        return "";
      }
      if (lines.length === 1) {
        return lines[0];
      }

      const merged = [lines[0]];
      lines.slice(1).forEach((line) => {
        const previous = merged[merged.length - 1];
        const keepCompactLineBreak =
          preserveCompactLineBreaks &&
          previous.length <= 56 &&
          line.length <= 56 &&
          !/[。！？.!?;；:]$/.test(previous) &&
          !/[。！？.!?;；:]$/.test(line);
        const keepLineBreak =
          keepCompactLineBreak ||
          /^[-*•]/.test(line) ||
          /^[([{（]?\d+[)\]}.、:：-]?\s/.test(line) ||
          /[:：]$/.test(previous) ||
          /\s{3,}/.test(previous) ||
          /\s{3,}/.test(line);

        if (keepLineBreak) {
          merged.push(line);
          return;
        }

        const hyphenated = previous.endsWith("-");
        const joinWithoutSpace =
          hyphenated || (isCjkCharacter(previous.slice(-1)) && isCjkCharacter(line.charAt(0)));
        merged[merged.length - 1] = hyphenated
          ? `${previous.slice(0, -1)}${line}`
          : `${previous}${joinWithoutSpace ? "" : " "}${line}`;
      });

      return merged.join("\n");
    })
    .filter(Boolean)
    .join("\n\n");
}

function compactPreviewText(text) {
  return String(text || "").replaceAll("\r\n", "\n").replace(/\s+/g, " ").trim();
}

function previewSegmentWeight(segment) {
  return Math.max(compactPreviewText(segment).length, 1);
}

function buildPreviewBreakCandidates(text) {
  const normalized = String(text || "").replaceAll("\r\n", "\n");
  const candidates = new Set([0, normalized.length]);
  let match = null;

  const paragraphBreakPattern = /\n\s*\n+/g;
  while ((match = paragraphBreakPattern.exec(normalized))) {
    candidates.add(match.index + match[0].length);
  }

  const lineBreakPattern = /\n/g;
  while ((match = lineBreakPattern.exec(normalized))) {
    candidates.add(match.index + 1);
  }

  const sentenceBreakPattern = /[。！？.!?;；:：](?:\s+|$)/g;
  while ((match = sentenceBreakPattern.exec(normalized))) {
    candidates.add(match.index + match[0].length);
  }

  return Array.from(candidates).sort((left, right) => left - right);
}

function findNearestPreviewTextBreak(text, desiredIndex, minIndex, maxIndex) {
  const normalized = String(text || "").replaceAll("\r\n", "\n");
  const lowerBound = Math.max(minIndex + 1, 1);
  const upperBound = Math.min(maxIndex, normalized.length - 1);

  if (lowerBound > upperBound) {
    return Math.min(normalized.length, Math.max(lowerBound, minIndex + 1));
  }

  const candidates = buildPreviewBreakCandidates(normalized).filter(
    (candidate) => candidate >= lowerBound && candidate <= upperBound
  );
  if (candidates.length) {
    return candidates.reduce((closest, candidate) =>
      Math.abs(candidate - desiredIndex) < Math.abs(closest - desiredIndex) ? candidate : closest
    );
  }

  const clampedTarget = Math.min(upperBound, Math.max(lowerBound, desiredIndex));
  for (let offset = 0; offset <= 36; offset += 1) {
    const left = clampedTarget - offset;
    if (left >= lowerBound && /[\s,，、/()[\]{}-]/.test(normalized.charAt(left))) {
      return left;
    }

    const right = clampedTarget + offset;
    if (right <= upperBound && /[\s,，、/()[\]{}-]/.test(normalized.charAt(right))) {
      return right;
    }
  }

  return clampedTarget;
}

function slicePreviewTextByRatios(text, ratios) {
  const normalized = String(text || "").replaceAll("\r\n", "\n").trim();
  if (!normalized) {
    return Array.from({ length: ratios.length + 1 }, () => "");
  }
  if (!ratios.length) {
    return [normalized];
  }

  const breakpoints = [];
  let cursor = 0;

  ratios.forEach((ratio, index) => {
    const remainingSegments = ratios.length - index;
    const desiredIndex = Math.round(normalized.length * ratio);
    const maxIndex = normalized.length - remainingSegments;
    const nextIndex = findNearestPreviewTextBreak(normalized, desiredIndex, cursor, maxIndex);
    breakpoints.push(nextIndex);
    cursor = nextIndex;
  });

  const boundaries = [0, ...breakpoints, normalized.length];
  return boundaries.slice(0, -1).map((start, index) => normalized.slice(start, boundaries[index + 1]).trim());
}

function buildPreviewSearchText(sourceText, translatedText) {
  return `${sourceText || ""}\n${translatedText || ""}`.replaceAll("\r\n", "\n").replaceAll("\n", " ").toLocaleLowerCase();
}

function findPreviewSegmentBoundary(cumulativeRatios, targetRatio, startIndex, maxEndIndex) {
  let bestEndIndex = Math.min(maxEndIndex, startIndex + 1);
  let bestDistance = Number.POSITIVE_INFINITY;

  for (let candidate = startIndex + 1; candidate <= maxEndIndex; candidate += 1) {
    const distance = Math.abs(cumulativeRatios[candidate - 1] - targetRatio);
    if (distance <= bestDistance) {
      bestDistance = distance;
      bestEndIndex = candidate;
    }
    if (cumulativeRatios[candidate - 1] >= targetRatio && distance > bestDistance) {
      break;
    }
  }

  return bestEndIndex;
}

function applySourceLineBreakFallback(sourceText, translatedText) {
  const normalizedSource = String(sourceText || "").replaceAll("\r\n", "\n").trim();
  const normalizedTranslated = String(translatedText || "").replaceAll("\r\n", "\n").trim();
  if (!normalizedSource || !normalizedTranslated) {
    return normalizedTranslated;
  }

  const sourceParagraphs = normalizedSource.split(/\n\s*\n+/).map((part) => part.trim()).filter(Boolean);
  const translatedParagraphs = normalizedTranslated.split(/\n\s*\n+/).map((part) => part.trim()).filter(Boolean);
  if (sourceParagraphs.length !== 1 || translatedParagraphs.length !== 1) {
    return normalizedTranslated;
  }

  const sourceLines = sourceParagraphs[0].split("\n").map((part) => part.trim()).filter(Boolean);
  const translatedLines = translatedParagraphs[0].split("\n").map((part) => part.trim()).filter(Boolean);
  if (sourceLines.length < 2 || sourceLines.length > 4 || translatedLines.length > 1) {
    return normalizedTranslated;
  }
  if (sourceLines.some((line) => line.length > 56)) {
    return normalizedTranslated;
  }

  const totalSourceWeight = sourceLines.reduce((sum, line) => sum + previewSegmentWeight(line), 0);
  let consumedSourceWeight = 0;
  const sourceLineRatios = sourceLines.slice(0, -1).map((line) => {
    consumedSourceWeight += previewSegmentWeight(line);
    return consumedSourceWeight / totalSourceWeight;
  });

  return slicePreviewTextByRatios(translatedParagraphs[0], sourceLineRatios).join("\n");
}

function alignTranslatedSegmentsToSource(sourceSegments, translatedSegments, normalizedTranslatedText = "") {
  const targetCount = sourceSegments.length;
  if (!targetCount) {
    return translatedSegments;
  }

  if (!translatedSegments.length) {
    return Array.from({ length: targetCount }, () => "");
  }

  if (translatedSegments.length === targetCount) {
    return translatedSegments;
  }

  const sourceWeights = sourceSegments.map(previewSegmentWeight);
  const totalSourceWeight = sourceWeights.reduce((sum, weight) => sum + weight, 0);
  let consumedSourceWeight = 0;
  const sourceBoundaries = sourceWeights.map((weight) => {
    consumedSourceWeight += weight;
    return consumedSourceWeight / totalSourceWeight;
  });

  if (translatedSegments.length < targetCount) {
    const translatedText = normalizedTranslatedText || normalizePreviewTextForBlocks(translatedSegments.join("\n\n"));
    return slicePreviewTextByRatios(translatedText, sourceBoundaries.slice(0, -1));
  }

  const translatedWeights = translatedSegments.map(previewSegmentWeight);
  const totalTranslatedWeight = translatedWeights.reduce((sum, weight) => sum + weight, 0);
  let consumedTranslatedWeight = 0;
  const translatedBoundaries = translatedWeights.map((weight) => {
    consumedTranslatedWeight += weight;
    return consumedTranslatedWeight / totalTranslatedWeight;
  });

  const aligned = [];
  let startIndex = 0;
  for (let index = 0; index < targetCount; index += 1) {
    if (index === targetCount - 1) {
      aligned.push(translatedSegments.slice(startIndex).join("\n\n"));
      break;
    }

    const remainingTargets = targetCount - index - 1;
    const maxEndIndex = translatedSegments.length - remainingTargets;
    const endIndex = findPreviewSegmentBoundary(
      translatedBoundaries,
      sourceBoundaries[index],
      startIndex,
      maxEndIndex
    );

    aligned.push(translatedSegments.slice(startIndex, endIndex).join("\n\n"));
    startIndex = endIndex;
  }
  return aligned;
}

function getPreviewBlockCount() {
  return getPreviewEditableBlocks().length;
}

function getActivePreviewBlockPage() {
  if (!state.previewBlockPages.length) {
    return null;
  }
  return state.previewBlockPages.find((page) => page.id === state.previewActivePageId) || state.previewBlockPages[0];
}

function getPreviewEditableBlocksFromBlock(block) {
  return block?.kind === "table" ? block.cells : [block];
}

function getPreviewEditableBlocks(pages = state.previewBlockPages) {
  return pages.flatMap((page) => page.blocks.flatMap((block) => getPreviewEditableBlocksFromBlock(block)));
}

function findPreviewBlock(blockId) {
  for (const page of state.previewBlockPages) {
    for (const block of page.blocks) {
      if (block.id === blockId) {
        return block;
      }
      if (block.kind === "table") {
        const cell = block.cells.find((item) => item.id === blockId);
        if (cell) {
          return cell;
        }
      }
    }
  }
  return null;
}

function countPreviewOverflowBlocks(pages = state.previewBlockPages) {
  return getPreviewEditableBlocks(pages).reduce((total, block) => total + (block.isOverflowing ? 1 : 0), 0);
}

function sanitizePreviewEditableText(text) {
  return String(text || "")
    .replaceAll("\r\n", "\n")
    .replace(/\u00a0/g, " ")
    .replace(/\u200b/g, "")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

function previewPdfFontFamily(text, fontName) {
  const normalizedFontName = String(fontName || "").toLocaleLowerCase();
  const preferredFont = fontName ? `"${String(fontName).replaceAll('"', '\\"')}", ` : "";
  if (/cour|mono|code/.test(normalizedFontName)) {
    return `${preferredFont}"Courier New", Consolas, Arial, "SimSun", "Microsoft YaHei", sans-serif`;
  }
  if (/times|serif|song|mincho|ming/.test(normalizedFontName)) {
    return `${preferredFont}"SimSun", "Source Han Serif SC", Georgia, ${PREVIEW_TECHNICAL_FONT_STACK}`;
  }
  if (/[\u3040-\u30ff]/.test(text || "")) {
    return `${preferredFont}"Hiragino Sans", "Yu Gothic", Meiryo, ${PREVIEW_TECHNICAL_FONT_STACK}`;
  }
  if (/[\uac00-\ud7af]/.test(text || "")) {
    return `${preferredFont}"Malgun Gothic", "Apple SD Gothic Neo", ${PREVIEW_TECHNICAL_FONT_STACK}`;
  }
  if (/[\u3400-\u9fff]/.test(text || "")) {
    return `${preferredFont}"Microsoft YaHei", "PingFang SC", "Noto Sans SC", "SimSun", Arial, sans-serif`;
  }
  return `${preferredFont}${PREVIEW_TECHNICAL_FONT_STACK}`;
}

function syncPreviewDirtyState() {
  if (!state.previewText || state.previewText.document_kind !== "pdf") {
    return;
  }
  state.previewDirty = getPreviewEditableBlocks().some((block) => block.isDirty);
}

function buildPreviewTableTrackSizes(tableRect, cells, axis) {
  const startIndex = axis === "x" ? 0 : 1;
  const endIndex = axis === "x" ? 2 : 3;
  const positions = Array.from(
    new Set([
      Number(tableRect[startIndex]) || 0,
      Number(tableRect[endIndex]) || 0,
      ...cells.flatMap((cell) => [Number(cell.rect[startIndex]) || 0, Number(cell.rect[endIndex]) || 0]),
    ])
  ).sort((left, right) => left - right);

  if (positions.length < 2) {
    return [Math.max((Number(tableRect[endIndex]) || 0) - (Number(tableRect[startIndex]) || 0), 1)];
  }

  return positions.slice(1).map((position, index) => Math.max(position - positions[index], 1));
}

function buildPreviewBlockPages() {
  if (!state.previewText) {
    state.previewBlockPages = [];
    state.previewActivePageId = null;
    return;
  }

  const activePage = getActivePreviewBlockPage();
  if (state.previewText.document_kind === "pdf") {
    state.previewBlockPages = state.previewText.pages.map((page, index) => {
      const pageNumber = Number(page.page_num) || index + 1;
      const pageId = `page-${pageNumber}`;
      return {
        id: pageId,
        pageId,
        pageNumber,
        pageWidth: Number(page.page_width) || 0,
        pageHeight: Number(page.page_height) || 0,
        blocks: (page.blocks || []).map((block, blockIndex) => {
          if ((block.type || "text") === "table") {
            const tableRect = Array.isArray(block.table_rect) ? block.table_rect.map((value) => Number(value) || 0) : [0, 0, 0, 0];
            const cells = (block.cells || []).map((cell, cellIndex) => {
              const fontSizeOriginal = Number(cell.font_size_original) || 11;
              const fontSizeCurrent = Number(cell.font_size_current) || fontSizeOriginal;
              const translatedText = cell.tgt_text || "";
              const sourceText = cell.src_text || "";
              return {
                id: cell.cell_id,
                kind: "table_cell",
                payloadKey: "cell_id",
                pageId,
                parentTableId: block.block_id,
                blockIndex: cellIndex + 1,
                rect: Array.isArray(cell.rect) ? cell.rect.map((value) => Number(value) || 0) : [0, 0, 0, 0],
                rowIndex: Number(cell.row_index) || 1,
                colIndex: Number(cell.col_index) || 1,
                rowSpan: Math.max(Number(cell.row_span) || 1, 1),
                colSpan: Math.max(Number(cell.col_span) || 1, 1),
                fontName: "",
                fontSizeOriginal,
                fontSizeCurrent,
                savedFontSize: fontSizeCurrent,
                sourceText,
                translatedText,
                savedText: translatedText,
                searchText: buildPreviewSearchText(sourceText, translatedText),
                isDirty: false,
                isOverflowing: false,
              };
            });

            return {
              id: block.block_id,
              kind: "table",
              pageId,
              blockIndex: blockIndex + 1,
              rect: tableRect,
              rowsCount: Number(block.rows_count) || 1,
              colsCount: Number(block.cols_count) || 1,
              columnTracks: buildPreviewTableTrackSizes(tableRect, cells, "x"),
              rowTracks: buildPreviewTableTrackSizes(tableRect, cells, "y"),
              cells,
            };
          }

          const fontSizeOriginal = Number(block.font_size_original) || 12;
          const fontSizeCurrent = Number(block.font_size_current) || fontSizeOriginal;
          const translatedText = block.tgt_text || "";
          const sourceText = block.src_text || "";
          return {
            id: block.block_id,
            kind: "text",
            payloadKey: "block_id",
            pageId,
            blockIndex: blockIndex + 1,
            rect: Array.isArray(block.rect) ? block.rect.map((value) => Number(value) || 0) : [0, 0, 0, 0],
            fontName: block.font_name || "",
            fontSizeOriginal,
            fontSizeCurrent,
            savedFontSize: fontSizeCurrent,
            sourceText,
            translatedText,
            savedText: translatedText,
            searchText: buildPreviewSearchText(sourceText, translatedText),
            isDirty: false,
            isOverflowing: false,
          };
        }),
      };
    });
    state.previewActivePageId = activePage?.id || state.previewBlockPages[0]?.id || null;
    state.previewDirty = false;
    return;
  }

  let displayIndex = 1;
  state.previewBlockPages = state.previewText.pages.map((page, index) => {
    const sourceSegments = splitPreviewTextIntoBlocks(page.source_text, { preserveCompactLineBreaks: true });
    const normalizedTranslatedText = normalizePreviewTextForBlocks(page.translated_text);
    const translatedSegments = splitPreviewTextIntoBlocks(page.translated_text);
    const needsSourceFallback = Boolean(sourceSegments.length) && translatedSegments.length !== sourceSegments.length;
    const alignedTranslatedSegments = sourceSegments.length
      ? alignTranslatedSegmentsToSource(sourceSegments, translatedSegments, normalizedTranslatedText)
      : translatedSegments;
    const previewTranslatedSegments = needsSourceFallback
      ? alignedTranslatedSegments.map((segment, blockIndex) =>
          applySourceLineBreakFallback(sourceSegments[blockIndex] || "", segment)
        )
      : alignedTranslatedSegments;
    const blockCount = Math.max(sourceSegments.length, previewTranslatedSegments.length, 1);

    return {
      id: page.id,
      pageId: page.id,
      pageNumber: previewPageNumber(page, index),
      blocks: Array.from({ length: blockCount }, (_, blockIndex) => ({
        id: `${page.id}-block-${blockIndex + 1}`,
        pageId: page.id,
        blockIndex: blockIndex + 1,
        displayIndex: displayIndex++,
        sourceText: sourceSegments[blockIndex] || "",
        translatedText: previewTranslatedSegments[blockIndex] || "",
        searchText: buildPreviewSearchText(sourceSegments[blockIndex] || "", previewTranslatedSegments[blockIndex] || ""),
      })),
    };
  });

  state.previewActivePageId = activePage?.id || state.previewBlockPages[0]?.id || null;
}

function syncPreviewBlocksToPages() {
  if (!state.previewText) {
    return;
  }

  if (state.previewText.document_kind === "pdf") {
    const blockPageLookup = new Map(state.previewBlockPages.map((page) => [page.pageNumber, page]));
    state.previewText.pages.forEach((page) => {
      const blockPage = blockPageLookup.get(page.page_num);
      if (!blockPage) {
        return;
      }
      page.blocks = blockPage.blocks.map((block) => ({
        block_id: block.id,
        rect: block.rect,
        font_name: block.fontName,
        font_size_original: block.fontSizeOriginal,
        font_size_current: block.fontSizeCurrent,
        src_text: block.sourceText,
        tgt_text: block.translatedText,
      }));
    });
    return;
  }

  const blockPageLookup = new Map(state.previewBlockPages.map((page) => [page.id, page]));
  state.previewText.pages.forEach((page) => {
    const blockPage = blockPageLookup.get(page.id);
    if (!blockPage) {
      return;
    }
    page.translated_text = blockPage.blocks.map((block) => block.translatedText.trim()).filter(Boolean).join("\n\n");
  });
}

function renderPdfOverlayEditor() {
  const activePage = getActivePreviewBlockPage();
  const activePageIndex = activePage ? state.previewBlockPages.findIndex((page) => page.id === activePage.id) + 1 : 0;
  const paginationItems = buildPreviewPaginationItems(state.previewBlockPages.length, activePageIndex || 1);
  const pageLabel = activePage ? formatPreviewBlockPageLabel(activePage) : previewCopy("暂无页面", "No pages");

  return `
    <section class="pdf-pane pdf-overlay-pane">
      <div class="pdf-pane-toolbar pdf-overlay-toolbar">
        <div class="pdf-overlay-toolbar-copy">
          <span class="pdf-pane-title">${escapeHtml(previewCopy("译文编辑图层", "Translation overlay editor"))}</span>
          <span class="pdf-overlay-page-label">${escapeHtml(pageLabel)}</span>
        </div>
        <div class="pdf-overlay-toolbar-actions">
          ${
            state.previewBlockPages.length > 1
              ? `
                <nav class="pdf-overlay-pagination" aria-label="${escapeHtml(previewCopy("分页导航", "Pagination"))}">
                  ${paginationItems
                    .map((item) => {
                      if (item.type === "ellipsis") {
                        return `<span class="pdf-overlay-pagination-ellipsis" aria-hidden="true">…</span>`;
                      }
                      const page = state.previewBlockPages[item.pageIndex - 1];
                      return `
                        <button
                          class="pdf-overlay-page-button ${item.pageIndex === activePageIndex ? "is-active" : ""}"
                          data-preview-page-id="${page.id}"
                          type="button"
                          ${item.pageIndex === activePageIndex ? 'aria-current="page"' : ""}
                        >
                          ${page.pageNumber}
                        </button>
                      `;
                    })
                    .join("")}
                </nav>
              `
              : ""
          }
          ${renderZoomControl("translated")}
        </div>
      </div>
      <div class="pdf-pane-body pdf-overlay-body" data-pdf-scroll-kind="translated">
        <div class="pdf-page-stack pdf-overlay-stage" data-pdf-pages="translated">
          <div class="empty-state">${escapeHtml(previewCopy("正在加载编辑器…", "Loading editor..."))}</div>
        </div>
      </div>
    </section>
  `;
}

function renderDocxPreviewPages(readOnly) {
  return state.previewText.pages
    .map(
      (page) => `
      <article class="text-preview-card">
        <div class="text-preview-head">${escapeHtml(page.label)}</div>
        <div class="text-preview-columns">
          <section class="text-preview-pane">
            <pre>${escapeHtml(page.source_text || "No source text available for this section.")}</pre>
          </section>
          <section class="text-preview-pane ${readOnly ? "" : "is-editable"}">
            ${
              readOnly
                ? `<pre>${escapeHtml(page.translated_text || "No translated text available for this section.")}</pre>`
                : `<textarea data-preview-page-id="${page.id}">${escapeHtml(page.translated_text)}</textarea>`
            }
          </section>
        </div>
      </article>
    `
    )
    .join("");
}

function autosizePreviewTextareas() {
  els.previewStage.querySelectorAll("textarea").forEach((textarea) => {
    textarea.style.height = "auto";
    textarea.style.height = `${Math.max(textarea.scrollHeight, 120)}px`;
  });
}

function commitPreviewEditableState(block, normalizedText, fontSize, isOverflowing) {
  block.fontSizeCurrent = fontSize;
  block.translatedText = normalizedText;
  block.searchText = buildPreviewSearchText(block.sourceText, block.translatedText);
  block.isOverflowing = isOverflowing;
  block.isDirty = block.translatedText !== block.savedText || Math.abs(block.fontSizeCurrent - block.savedFontSize) > 0.01;
}

function fitPreviewPdfBlockEditor(editor, block) {
  const overlay = editor.closest("[data-preview-pdf-overlay]");
  const measure = overlay?.querySelector("[data-preview-pdf-measure]");
  if (!measure) {
    return;
  }

  const maxWidth = editor.clientWidth;
  const maxHeight = editor.clientHeight;
  const normalizedText = sanitizePreviewEditableText(editor.innerText);
  const fontFamily = previewPdfFontFamily(normalizedText || block.sourceText, block.fontName);
  const lineHeight = 1.28;
  let fontSize = Number(block.fontSizeOriginal) || Number(block.fontSizeCurrent) || 12;

  editor.style.fontFamily = fontFamily;
  editor.style.lineHeight = lineHeight;
  editor.style.whiteSpace = "pre-wrap";
  editor.style.overflowWrap = "anywhere";
  editor.style.textOverflow = "clip";
  editor.style.overflow = "hidden";

  measure.style.width = `${maxWidth}px`;
  measure.style.fontFamily = fontFamily;
  measure.style.lineHeight = lineHeight;
  measure.style.whiteSpace = "pre-wrap";
  measure.style.overflowWrap = "anywhere";
  measure.textContent = normalizedText || " ";

  while (fontSize >= 8) {
    const roundedFontSize = Number(fontSize.toFixed(2));
    editor.style.fontSize = `${roundedFontSize}pt`;
    measure.style.fontSize = `${roundedFontSize}pt`;
    const fits =
      measure.scrollWidth <= maxWidth + 1 &&
      measure.scrollHeight <= maxHeight + 1 &&
      measure.getBoundingClientRect().height <= maxHeight + 1;
    if (fits) {
      commitPreviewEditableState(block, normalizedText, roundedFontSize, false);
      editor.classList.remove("is-overflowing");
      editor.classList.remove("is-truncated");
      editor.dataset.previewOverflow = "false";
      return;
    }
    fontSize -= 0.5;
  }

  const minimumFontSize = 8;
  editor.style.fontSize = `${minimumFontSize}pt`;
  measure.style.fontSize = `${minimumFontSize}pt`;
  commitPreviewEditableState(block, normalizedText, minimumFontSize, true);
  editor.classList.add("is-overflowing");
  editor.classList.remove("is-truncated");
  editor.dataset.previewOverflow = "true";
}

function fitPreviewPdfTableCellEditor(editor, block) {
  const overlay = editor.closest("[data-preview-pdf-overlay]");
  const measure = overlay?.querySelector("[data-preview-pdf-measure]");
  if (!measure) {
    return;
  }

  const maxWidth = editor.clientWidth;
  const maxHeight = editor.clientHeight;
  const normalizedText = sanitizePreviewEditableText(editor.innerText);
  const fontFamily = previewPdfFontFamily(normalizedText || block.sourceText, block.fontName);
  const lineHeight = 1.18;
  let fontSize = Number(block.fontSizeOriginal) || Number(block.fontSizeCurrent) || 11;

  editor.style.fontFamily = fontFamily;
  editor.style.lineHeight = lineHeight;
  editor.style.overflow = "hidden";
  editor.style.overflowWrap = "anywhere";

  measure.style.fontFamily = fontFamily;
  measure.style.lineHeight = lineHeight;
  measure.textContent = normalizedText || " ";

  while (fontSize >= PREVIEW_TABLE_MIN_FONT_SIZE) {
    const roundedFontSize = Number(fontSize.toFixed(2));
    editor.style.fontSize = `${roundedFontSize}pt`;
    measure.style.fontSize = `${roundedFontSize}pt`;

    measure.style.width = "auto";
    measure.style.whiteSpace = "nowrap";
    measure.style.overflowWrap = "normal";
    const singleLineFits =
      measure.scrollWidth <= maxWidth + 1 &&
      measure.getBoundingClientRect().height <= maxHeight + 1;
    if (singleLineFits) {
      editor.style.whiteSpace = "nowrap";
      editor.style.textOverflow = "clip";
      commitPreviewEditableState(block, normalizedText, roundedFontSize, false);
      editor.classList.remove("is-overflowing", "is-truncated");
      editor.dataset.previewOverflow = "false";
      editor.title = block.sourceText || previewCopy("可编辑表格单元格", "Editable table cell");
      return;
    }

    measure.style.width = `${maxWidth}px`;
    measure.style.whiteSpace = "pre-wrap";
    measure.style.overflowWrap = "anywhere";
    const wrappedFits =
      measure.scrollWidth <= maxWidth + 1 &&
      measure.scrollHeight <= maxHeight + 1 &&
      measure.getBoundingClientRect().height <= maxHeight + 1;
    if (wrappedFits) {
      editor.style.whiteSpace = "pre-wrap";
      editor.style.textOverflow = "clip";
      commitPreviewEditableState(block, normalizedText, roundedFontSize, false);
      editor.classList.remove("is-overflowing", "is-truncated");
      editor.dataset.previewOverflow = "false";
      editor.title = block.sourceText || previewCopy("可编辑表格单元格", "Editable table cell");
      return;
    }

    fontSize -= 0.5;
  }

  editor.style.fontSize = `${PREVIEW_TABLE_MIN_FONT_SIZE}pt`;
  editor.style.whiteSpace = "nowrap";
  editor.style.textOverflow = "ellipsis";
  commitPreviewEditableState(block, normalizedText, PREVIEW_TABLE_MIN_FONT_SIZE, true);
  editor.classList.add("is-overflowing", "is-truncated");
  editor.dataset.previewOverflow = "true";
  editor.title = normalizedText || block.sourceText || previewCopy("可编辑表格单元格", "Editable table cell");
}

function fitPreviewPdfEditableEditor(editor, block) {
  if (block.kind === "table_cell") {
    fitPreviewPdfTableCellEditor(editor, block);
    return;
  }
  fitPreviewPdfBlockEditor(editor, block);
}

function hydratePreviewPdfEditorPage(activePage, overlay) {
  const measure = document.createElement("span");
  measure.className = "pdf-edit-measure";
  measure.dataset.previewPdfMeasure = "true";
  overlay.append(measure);

  overlay.querySelectorAll("[data-preview-block-id]").forEach((editor) => {
    const block = activePage.blocks.find((item) => item.id === editor.dataset.previewBlockId);
    if (block) {
      fitPreviewPdfEditableEditor(editor, block);
      return;
    }
    const nestedBlock = findPreviewBlock(editor.dataset.previewBlockId);
    if (!nestedBlock) {
      return;
    }
    fitPreviewPdfEditableEditor(editor, nestedBlock);
  });
  syncPreviewDirtyState();
  syncPreviewToolbar();
}

function renderPreviewPdfTableEditor(table, scaleX, scaleY) {
  const [x0, y0, x1, y1] = table.rect;
  const tableShell = document.createElement("div");
  tableShell.className = "pdf-table-block";
  tableShell.style.left = `${x0 * scaleX}px`;
  tableShell.style.top = `${y0 * scaleY}px`;
  tableShell.style.width = `${Math.max((x1 - x0) * scaleX, 12)}px`;
  tableShell.style.height = `${Math.max((y1 - y0) * scaleY, 12)}px`;

  const tableGrid = document.createElement("div");
  tableGrid.className = "pdf-table-grid";
  tableGrid.style.gridTemplateColumns = table.columnTracks.map((size) => `${Math.max(size * scaleX, 1)}px`).join(" ");
  tableGrid.style.gridTemplateRows = table.rowTracks.map((size) => `${Math.max(size * scaleY, 1)}px`).join(" ");

  table.cells.forEach((cell) => {
    const editor = document.createElement("div");
    editor.className = "pdf-table-cell";
    editor.contentEditable = "true";
    editor.spellcheck = false;
    editor.setAttribute("role", "textbox");
    editor.setAttribute("aria-multiline", "true");
    editor.dataset.previewBlockId = cell.id;
    editor.dataset.previewPayloadKey = cell.payloadKey;
    editor.dataset.previewTableId = table.id;
    editor.style.gridColumn = `${cell.colIndex} / span ${cell.colSpan}`;
    editor.style.gridRow = `${cell.rowIndex} / span ${cell.rowSpan}`;
    editor.style.fontSize = `${cell.fontSizeCurrent}pt`;
    editor.style.fontFamily = previewPdfFontFamily(cell.translatedText || cell.sourceText, cell.fontName);
    editor.textContent = cell.translatedText;
    editor.title = cell.sourceText || previewCopy("可编辑表格单元格", "Editable table cell");
    tableGrid.append(editor);
  });

  tableShell.append(tableGrid);
  return tableShell;
}

function isPreviewPdfEditMode() {
  return Boolean(
    state.previewJob &&
      state.previewMode === "edit" &&
      documentKind(state.previewJob.input_file.original_name) === "pdf"
  );
}

async function renderPdfPages(kind, options = {}) {
  const body = getPdfPaneBody(kind);
  const stack = getPdfPaneStack(kind);
  if (!body || !stack) {
    return;
  }

  stack.innerHTML = `<div class="empty-state">${escapeHtml(previewCopy("正在加载 PDF…", "Loading PDF..."))}</div>`;
  body.classList.add("is-loading");

  const version = state.previewRenderVersion[kind] + 1;
  state.previewRenderVersion[kind] = version;

  try {
    const pdfDoc = await ensurePreviewPdfLoaded(kind);
    if (!pdfDoc || state.previewRenderVersion[kind] !== version) {
      return;
    }

    const availableWidth = Math.max(body.clientWidth - 48, 240);
    const pageNodes = [];
    const requestedPageNumbers =
      Array.isArray(options.pageNumbers) && options.pageNumbers.length
        ? Array.from(
            new Set(
              options.pageNumbers
                .map((pageNumber) => Number(pageNumber))
                .filter((pageNumber) => Number.isInteger(pageNumber) && pageNumber >= 1 && pageNumber <= pdfDoc.numPages)
            )
          )
        : Array.from({ length: pdfDoc.numPages }, (_, index) => index + 1);

    for (const pageNumber of requestedPageNumbers) {
      if (state.previewRenderVersion[kind] !== version) {
        return;
      }

      const page = await pdfDoc.getPage(pageNumber);
      const baseViewport = page.getViewport({ scale: 1 });
      const fitScale = availableWidth / baseViewport.width;
      const viewport = page.getViewport({ scale: fitScale * (state.previewZoom[kind] / 100) });
      const outputScale = Math.min(window.devicePixelRatio || 1, PREVIEW_MAX_RENDER_DPR);

      const pageShell = document.createElement("article");
      pageShell.className = "pdf-page-shell";
      pageShell.style.width = `${viewport.width}px`;

      const canvas = document.createElement("canvas");
      canvas.className = "pdf-page-canvas";
      canvas.width = Math.floor(viewport.width * outputScale);
      canvas.height = Math.floor(viewport.height * outputScale);
      canvas.style.width = `${viewport.width}px`;
      canvas.style.height = `${viewport.height}px`;

      const context = canvas.getContext("2d", { alpha: false });
      context.fillStyle = "#ffffff";
      context.fillRect(0, 0, canvas.width, canvas.height);

      const transform = outputScale === 1 ? null : [outputScale, 0, 0, outputScale, 0, 0];
      const renderTask = page.render({
        canvasContext: context,
        viewport,
        transform,
      });
      await renderTask.promise;

      if (state.previewRenderVersion[kind] !== version) {
        return;
      }

      pageShell.append(canvas);
      pageNodes.push(pageShell);
    }

    stack.replaceChildren(...pageNodes);
  } catch (error) {
    stack.innerHTML = `<div class="empty-state">${escapeHtml(error.message || t("previewUnavailable"))}</div>`;
  } finally {
    body.classList.remove("is-loading");
  }
}

async function renderPdfOverlayPage() {
  const body = getPdfPaneBody("translated");
  const stack = getPdfPaneStack("translated");
  const activePage = getActivePreviewBlockPage();
  if (!body || !stack || !activePage) {
    return;
  }

  stack.innerHTML = `<div class="empty-state">${escapeHtml(previewCopy("正在加载编辑器…", "Loading editor..."))}</div>`;
  body.classList.add("is-loading");

  const version = state.previewRenderVersion.translated + 1;
  state.previewRenderVersion.translated = version;

  try {
    const pdfDoc = await ensurePreviewPdfLoaded("translated");
    if (!pdfDoc || state.previewRenderVersion.translated !== version) {
      return;
    }

    const page = await pdfDoc.getPage(activePage.pageNumber);
    const availableWidth = Math.max(body.clientWidth - 48, 240);
    const baseViewport = page.getViewport({ scale: 1 });
    const fitScale = availableWidth / baseViewport.width;
    const viewport = page.getViewport({ scale: fitScale * (state.previewZoom.translated / 100) });
    const outputScale = Math.min(window.devicePixelRatio || 1, PREVIEW_MAX_RENDER_DPR);

    const pageShell = document.createElement("article");
    pageShell.className = "pdf-edit-page-shell";
    pageShell.style.width = `${viewport.width}px`;
    pageShell.style.height = `${viewport.height}px`;

    const canvas = document.createElement("canvas");
    canvas.className = "pdf-page-canvas";
    canvas.width = Math.floor(viewport.width * outputScale);
    canvas.height = Math.floor(viewport.height * outputScale);
    canvas.style.width = `${viewport.width}px`;
    canvas.style.height = `${viewport.height}px`;

    const context = canvas.getContext("2d", { alpha: false });
    context.fillStyle = "#ffffff";
    context.fillRect(0, 0, canvas.width, canvas.height);

    const transform = outputScale === 1 ? null : [outputScale, 0, 0, outputScale, 0, 0];
    const renderTask = page.render({
      canvasContext: context,
      viewport,
      transform,
    });
    await renderTask.promise;

    if (state.previewRenderVersion.translated !== version) {
      return;
    }

    const overlay = document.createElement("div");
    overlay.className = "pdf-edit-overlay";
    overlay.dataset.previewPdfOverlay = "true";
    overlay.style.width = `${viewport.width}px`;
    overlay.style.height = `${viewport.height}px`;

    const scaleX = activePage.pageWidth > 0 ? viewport.width / activePage.pageWidth : 1;
    const scaleY = activePage.pageHeight > 0 ? viewport.height / activePage.pageHeight : 1;
    activePage.blocks.forEach((block) => {
      if (block.kind === "table") {
        overlay.append(renderPreviewPdfTableEditor(block, scaleX, scaleY));
        return;
      }

      const [x0, y0, x1, y1] = block.rect;
      const editor = document.createElement("div");
      editor.className = "pdf-edit-block";
      editor.contentEditable = "true";
      editor.spellcheck = false;
      editor.setAttribute("role", "textbox");
      editor.setAttribute("aria-multiline", "true");
      editor.dataset.previewBlockId = block.id;
      editor.dataset.previewPayloadKey = block.payloadKey;
      editor.title = block.sourceText || previewCopy("可编辑译文块", "Editable translation block");
      editor.style.left = `${x0 * scaleX}px`;
      editor.style.top = `${y0 * scaleY}px`;
      editor.style.width = `${Math.max((x1 - x0) * scaleX, 12)}px`;
      editor.style.height = `${Math.max((y1 - y0) * scaleY, 12)}px`;
      editor.style.fontSize = `${block.fontSizeCurrent}pt`;
      editor.style.fontFamily = previewPdfFontFamily(block.translatedText || block.sourceText, block.fontName);
      editor.textContent = block.translatedText;
      overlay.append(editor);
    });

    pageShell.append(canvas, overlay);
    stack.replaceChildren(pageShell);
    hydratePreviewPdfEditorPage(activePage, overlay);
  } catch (error) {
    stack.innerHTML = `<div class="empty-state">${escapeHtml(error.message || t("previewUnavailable"))}</div>`;
  } finally {
    body.classList.remove("is-loading");
  }
}

async function renderPdfPaneContent(kind, options = {}) {
  if (kind === "translated" && isPreviewPdfEditMode()) {
    await renderPdfOverlayPage(options);
    return;
  }
  await renderPdfPages(kind, options);
}

async function renderActivePdfPanes(kinds, options = {}) {
  const visibleKinds = kinds.filter((kind) => getPdfPaneStack(kind));
  if (!visibleKinds.length) {
    return;
  }

  if (options.preserveScroll) {
    rememberPreviewScrollRatios();
  }

  await Promise.all(visibleKinds.map((kind) => renderPdfPaneContent(kind, options)));

  if (options.preserveScroll) {
    restorePreviewScrollRatios(visibleKinds);
  }
}

function renderPreviewStage() {
  if (!state.previewJob) {
    els.previewStage.innerHTML = `<div class="empty-state">${escapeHtml(previewCopy("预览尚未加载。", "Preview is not loaded yet."))}</div>`;
    syncPreviewToolbar();
    return;
  }

  const kind = documentKind(state.previewJob.input_file.original_name);
  const outputName = state.previewJob.output_file?.original_name || state.previewJob.input_file.original_name;

  els.previewFileKind.textContent = kind.toUpperCase();
  els.previewTitle.textContent = outputName;
  els.previewSubtitle.textContent = `${formatLanguageName(state.previewJob.source_language)} → ${formatLanguageName(state.previewJob.target_language)}`;

  if (kind === "pdf" && state.previewMode === "view") {
    if (!state.previewDocuments.sourceUrl || !state.previewDocuments.translatedUrl) {
      els.previewStage.innerHTML = `<div class="empty-state">${escapeHtml(previewCopy("正在加载 PDF 预览…", "Loading PDF preview..."))}</div>`;
      syncPreviewToolbar();
      return;
    }

    els.previewStage.innerHTML = `
      <div class="pdf-preview-grid">
        ${renderPdfPane("source", state.previewJob.input_file.original_name)}
        ${renderPdfPane("translated", outputName)}
      </div>
    `;
    syncPreviewToolbar();
    void renderActivePdfPanes(["source", "translated"], { preserveScroll: true });
    return;
  }

  if (kind === "pdf" && state.previewMode === "edit") {
    if (!state.previewDocuments.sourceUrl || !state.previewDocuments.translatedUrl || !state.previewText) {
      els.previewStage.innerHTML = `<div class="empty-state">${escapeHtml(previewCopy("正在加载编辑器…", "Loading editor..."))}</div>`;
      syncPreviewToolbar();
      return;
    }

    const activePage = getActivePreviewBlockPage();
    els.previewStage.innerHTML = `
      <div class="pdf-edit-grid">
        ${renderPdfPane("source", state.previewJob.input_file.original_name)}
        ${renderPdfOverlayEditor()}
      </div>
    `;
    syncPreviewToolbar();
    void renderActivePdfPanes(["source", "translated"], {
      preserveScroll: true,
      pageNumbers: activePage ? [activePage.pageNumber] : [1],
    });
    return;
  }

  if (!state.previewText) {
    els.previewStage.innerHTML = `<div class="empty-state">${escapeHtml(previewCopy("正在加载文档预览…", "Loading document preview..."))}</div>`;
    syncPreviewToolbar();
    return;
  }

  els.previewStage.innerHTML =
    state.previewMode === "edit" ? renderDocxPreviewPages(false) : renderDocxPreviewPages(true);
  syncPreviewToolbar();
  if (state.previewMode === "edit") {
    autosizePreviewTextareas();
  }
}

async function fetchPreviewDocument(path) {
  const response = await api(path);
  const blob = await response.blob();
  return {
    url: URL.createObjectURL(blob),
    data: new Uint8Array(await blob.arrayBuffer()),
  };
}

async function refreshTranslatedPreviewDocument() {
  if (!state.previewJobId) {
    return;
  }

  const translatedDocument = await fetchPreviewDocument(`/jobs/${state.previewJobId}/documents/translated`);
  if (state.previewPdfLoadingTasks.translated?.destroy) {
    state.previewPdfLoadingTasks.translated.destroy();
  }
  if (state.previewPdfDocs.translated?.destroy) {
    state.previewPdfDocs.translated.destroy();
  }
  if (state.previewDocuments.translatedUrl) {
    URL.revokeObjectURL(state.previewDocuments.translatedUrl);
  }

  state.previewDocuments.translatedUrl = translatedDocument.url;
  state.previewDocuments.translatedData = translatedDocument.data;
  state.previewPdfLoadingTasks.translated = null;
  state.previewPdfDocs.translated = null;
  state.previewRenderVersion.translated = 0;
}

async function ensurePreviewTextLoaded() {
  if (state.previewText) {
    return;
  }
  setMessage(els.previewMessage, previewCopy("正在加载编辑器…", "Loading editor..."));
  state.previewText = await api(`/jobs/${state.previewJobId}/preview`);
  buildPreviewBlockPages();
  setMessage(els.previewMessage, "");
}

async function loadPreviewJob(jobId) {
  if (state.previewJobId !== jobId) {
    clearPreviewState();
  }

  setMessage(els.previewMessage, previewCopy("正在加载预览…", "Loading preview..."));

  const job = await api(`/jobs/${jobId}`);
  if (!job.output_file || job.status !== "completed") {
    throw new Error(state.uiLanguage === "zh-CN" ? "翻译完成后才可预览。" : "Preview is available after translation completes.");
  }

  state.previewJob = job;
  state.previewJobId = jobId;
  state.previewMode = "view";
  state.previewDirty = false;
  state.previewBlockPages = [];
  state.previewActivePageId = null;
  state.previewSearchQuery = "";
  state.previewReplaceValue = "";
  state.previewReplaceOpen = false;
  state.previewZoom = {
    source: 100,
    translated: 100,
  };

  if (documentKind(job.input_file.original_name) === "pdf") {
    const [sourceDocument, translatedDocument] = await Promise.all([
      fetchPreviewDocument(`/jobs/${jobId}/documents/source`),
      fetchPreviewDocument(`/jobs/${jobId}/documents/translated`),
    ]);
    revokePreviewDocuments();
    state.previewDocuments = {
      sourceUrl: sourceDocument.url,
      translatedUrl: translatedDocument.url,
      sourceData: sourceDocument.data,
      translatedData: translatedDocument.data,
    };
  } else {
    state.previewText = await api(`/jobs/${jobId}/preview`);
    buildPreviewBlockPages();
  }

  renderPreviewStage();
  setMessage(els.previewMessage, "");
}

async function renderRoute() {
  const route = parseRoute();
  const signedIn = Boolean(state.user);
  document.body.dataset.view = route.view;

  renderHeader(route);

  if (!signedIn) {
    els.workspaceView.classList.add("hidden");
    els.previewView.classList.add("hidden");
    els.adminView.classList.add("hidden");
    return;
  }

  if (route.view === "admin" && state.user.role !== "admin") {
    await navigateTo("/", { replace: true });
    return;
  }

  els.workspaceView.classList.toggle("hidden", route.view !== "workspace");
  els.previewView.classList.toggle("hidden", route.view !== "preview");
  els.adminView.classList.toggle("hidden", route.view !== "admin");

  if (route.view === "admin") {
    renderAdminPage(route.adminPage);
    return;
  }

  if (route.view === "preview") {
    try {
      if (state.previewJobId !== route.jobId || !state.previewJob) {
        await loadPreviewJob(route.jobId);
      } else {
        renderPreviewStage();
      }
    } catch (error) {
      els.previewStage.innerHTML = `<div class="empty-state">${escapeHtml(error.message)}</div>`;
      setMessage(els.previewMessage, error.message, true);
    }
    return;
  }
}

async function bootstrap() {
  enhanceSelects();
  applyUiLanguage();
  renderAuthState();
  renderSelectedFile();
  renderWorkspaceMoreSettings();
  syncPreviewToolbar();
  if (!state.token) {
    return;
  }

  try {
    state.user = await api("/auth/me");
    renderAuthState();
    await refreshAll();
    if (!state.pollHandle) {
      state.pollHandle = window.setInterval(() => {
        refreshJobsOnly().catch((error) => {
          console.error(error);
        });
      }, POLL_INTERVAL_MS);
    }
  } catch (error) {
    clearSession();
    setMessage(els.loginError, error.message, true);
  }
}

async function refreshJobsOnly() {
  if (!state.user) {
    return;
  }
  state.jobs = await api("/jobs");
  renderJobs();
}

async function refreshAll() {
  const jobsPromise = api("/jobs");
  const adminPromises =
    state.user.role === "admin"
      ? Promise.all([api("/settings"), api("/users"), api("/storage/summary"), api("/audit-logs")])
      : Promise.resolve([]);

  const [jobs, adminData] = await Promise.all([jobsPromise, adminPromises]);
  state.jobs = jobs;
  renderJobs();

  if (state.selectedJobId) {
    try {
      const detail = await api(`/jobs/${state.selectedJobId}`);
      renderJobDetail(detail);
    } catch {
      state.selectedJobId = null;
      renderJobDetail(null);
    }
  } else {
    renderJobDetail(null);
  }

  if (state.user.role === "admin") {
    const [settings, users, storage, audit] = adminData;
    fillSettings(settings);
    renderUsers(users);
    renderStorage(storage);
    renderAudit(audit);
  }

  await renderRoute();
}

function setUploadFile(file) {
  const transfer = new DataTransfer();
  transfer.items.add(file);
  els.uploadFile.files = transfer.files;
  renderSelectedFile();
}

async function navigateTo(path, options = {}) {
  const method = options.replace ? "replaceState" : "pushState";
  if (window.location.pathname !== path) {
    window.history[method]({}, "", path);
  }
  await renderRoute();
}

async function downloadJob(jobId) {
  const response = await api(`/jobs/${jobId}/download`);
  const blob = await response.blob();
  const downloadUrl = URL.createObjectURL(blob);
  const contentDisposition = response.headers.get("content-disposition") || "";
  const match = /filename="?([^"]+)"?/.exec(contentDisposition);
  const filename = match?.[1] || `translated-${jobId}`;

  const link = document.createElement("a");
  link.href = downloadUrl;
  link.download = filename;
  link.style.display = "none";
  document.body.append(link);
  link.click();

  window.setTimeout(() => {
    link.remove();
    URL.revokeObjectURL(downloadUrl);
  }, 1000);
}

async function handleLogin(event) {
  event.preventDefault();
  setMessage(els.loginError, "");

  const body = new URLSearchParams({
    username: els.loginEmail.value.trim(),
    password: els.loginPassword.value,
  });

  try {
    const result = await api("/auth/login", {
      method: "POST",
      body,
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
    });
    persistToken(result.access_token);
    state.user = result.user;
    renderAuthState();
    els.loginForm.reset();
    await refreshAll();
    if (!state.pollHandle) {
      state.pollHandle = window.setInterval(() => {
        refreshJobsOnly().catch((error) => {
          console.error(error);
        });
      }, POLL_INTERVAL_MS);
    }
  } catch (error) {
    setMessage(els.loginError, error.message, true);
  }
}

async function handleUpload(event) {
  event.preventDefault();
  setMessage(els.uploadMessage, "");
  if (!els.uploadFile.files.length) {
    setMessage(els.uploadMessage, state.uiLanguage === "zh-CN" ? "请先选择 PDF 或 DOCX 文件。" : "Choose a PDF or DOCX file first.", true);
    return;
  }

  const formData = new FormData();
  formData.set("file", els.uploadFile.files[0]);
  formData.set("source_language", els.sourceLanguage.value);
  formData.set("target_language", els.targetLanguage.value);

  try {
    await api("/jobs/upload", { method: "POST", body: formData });
    els.uploadForm.reset();
    els.sourceLanguage.value = "auto";
    els.targetLanguage.value = "Chinese";
    refreshCustomSelects();
    renderSelectedFile();
    setMessage(els.uploadMessage, state.uiLanguage === "zh-CN" ? "任务已加入队列。" : "Job queued.");
    await refreshAll();
  } catch (error) {
    setMessage(els.uploadMessage, error.message, true);
  }
}

async function handleJobAction(event) {
  const button = event.target.closest("button[data-action]");
  if (!button) {
    return;
  }

  const { action, jobId } = button.dataset;
  try {
    if (action === "refresh") {
      await refreshAll();
      return;
    }
    if (action === "view") {
      state.selectedJobId = jobId;
      const detail = await api(`/jobs/${jobId}`);
      renderJobDetail(detail);
      return;
    }
    if (action === "preview") {
      await navigateTo(`/preview/${jobId}`);
      return;
    }
    if (action === "download") {
      await downloadJob(jobId);
      return;
    }
    if (action === "cancel") {
      await api(`/jobs/${jobId}/cancel`, { method: "POST" });
    }
    if (action === "retry") {
      await api(`/jobs/${jobId}/retry`, { method: "POST" });
    }
    await refreshAll();
  } catch (error) {
    window.alert(error.message);
  }
}

async function handleSettingsSave(event) {
  event.preventDefault();
  setMessage(els.settingsMessage, "");

  const payload = {
    model_base_url: settingsFields.model_base_url.value.trim(),
    model_api_key: settingsFields.model_api_key.value,
    model_name: settingsFields.model_name.value.trim(),
    model_timeout_seconds: Number(settingsFields.model_timeout_seconds.value),
    storage_mode: settingsFields.storage_mode.value.trim(),
    local_storage_path: settingsFields.local_storage_path.value.trim(),
    file_retention_days: Number(settingsFields.file_retention_days.value),
    max_upload_mb: Number(settingsFields.max_upload_mb.value),
    max_concurrent_jobs: Number(settingsFields.max_concurrent_jobs.value),
    ocr_language_hint: settingsFields.ocr_language_hint.value.trim(),
    ocr_enabled: settingsFields.ocr_enabled.checked,
  };

  try {
    const updated = await api("/settings", {
      method: "PUT",
      body: JSON.stringify(payload),
      headers: { "Content-Type": "application/json" },
    });
    fillSettings(updated);
    setMessage(els.settingsMessage, state.uiLanguage === "zh-CN" ? "设置已保存。" : "Settings saved.");
  } catch (error) {
    setMessage(els.settingsMessage, error.message, true);
  }
}

async function handleModelTest() {
  setMessage(els.settingsMessage, "");

  const payload = {
    model_base_url: settingsFields.model_base_url.value.trim(),
    model_api_key: settingsFields.model_api_key.value,
    model_name: settingsFields.model_name.value.trim(),
    model_timeout_seconds: Number(settingsFields.model_timeout_seconds.value),
  };

  try {
    const result = await api("/settings/test-model", {
      method: "POST",
      body: JSON.stringify(payload),
      headers: { "Content-Type": "application/json" },
    });
    setMessage(
      els.settingsMessage,
      state.uiLanguage === "zh-CN"
        ? `连接成功，耗时 ${result.latency_ms} ms。返回示例：${result.preview}`
        : `Connection OK in ${result.latency_ms} ms. Preview: ${result.preview}`
    );
  } catch (error) {
    setMessage(els.settingsMessage, error.message, true);
  }
}

async function handleCreateUser(event) {
  event.preventDefault();
  setMessage(els.userMessage, "");

  const payload = {
    full_name: document.getElementById("new-user-name").value.trim(),
    email: document.getElementById("new-user-email").value.trim(),
    password: document.getElementById("new-user-password").value,
    role: document.getElementById("new-user-role").value,
    is_active: true,
  };

  try {
    await api("/users", {
      method: "POST",
      body: JSON.stringify(payload),
      headers: { "Content-Type": "application/json" },
    });
    els.createUserForm.reset();
    setMessage(els.userMessage, state.uiLanguage === "zh-CN" ? "用户已创建。" : "User created.");
    await refreshAll();
  } catch (error) {
    setMessage(els.userMessage, error.message, true);
  }
}

async function handleUserAction(event) {
  const button = event.target.closest("button[data-user-action]");
  if (!button) {
    return;
  }

  const userId = button.dataset.userId;
  const action = button.dataset.userAction;
  let payload = {};

  if (action === "toggle-active") {
    payload = { is_active: button.dataset.userActive !== "true" };
  }
  if (action === "toggle-role") {
    payload = { role: button.dataset.userRole === "admin" ? "user" : "admin" };
  }

  try {
    await api(`/users/${userId}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
      headers: { "Content-Type": "application/json" },
    });
    await refreshAll();
  } catch (error) {
    window.alert(error.message);
  }
}

function handleLogout() {
  clearSession();
}

function handleDropZoneClick() {
  els.uploadFile.click();
}

function handleDropZoneKeydown(event) {
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    els.uploadFile.click();
  }
}

function handleFileChange() {
  renderSelectedFile();
}

function handleDragOver(event) {
  event.preventDefault();
  els.dropZone.classList.add("is-dragging");
}

function handleDragLeave(event) {
  if (event.currentTarget.contains(event.relatedTarget)) {
    return;
  }
  els.dropZone.classList.remove("is-dragging");
}

function handleDrop(event) {
  event.preventDefault();
  els.dropZone.classList.remove("is-dragging");
  const [file] = event.dataTransfer.files;
  if (file) {
    setUploadFile(file);
  }
}

function handleClearFile() {
  els.uploadForm.reset();
  els.sourceLanguage.value = "auto";
  els.targetLanguage.value = "Chinese";
  refreshCustomSelects();
  renderSelectedFile();
  setMessage(els.uploadMessage, "");
}

function handlePreviewInput(event) {
  const searchField = event.target.closest("input[data-preview-search-input]");
  if (searchField) {
    state.previewSearchQuery = searchField.value;
    return;
  }

  const replaceField = event.target.closest("input[data-preview-replace-input]");
  if (replaceField) {
    state.previewReplaceValue = replaceField.value;
    return;
  }

  const blockField = event.target.closest("[data-preview-block-id][contenteditable='true']");
  if (blockField && state.previewBlockPages.length) {
    const block = findPreviewBlock(blockField.dataset.previewBlockId);
    if (!block) {
      return;
    }

    fitPreviewPdfBlockEditor(blockField, block);
    syncPreviewDirtyState();
    syncPreviewToolbar();
    return;
  }

  const pageField = event.target.closest("textarea[data-preview-page-id]");
  if (!pageField || !state.previewText) {
    return;
  }

  const page = state.previewText.pages.find((item) => item.id === pageField.dataset.previewPageId);
  if (!page) {
    return;
  }

  page.translated_text = pageField.value;
  state.previewDirty = true;
  pageField.style.height = "auto";
  pageField.style.height = `${Math.max(pageField.scrollHeight, 120)}px`;
  syncPreviewToolbar();
}

function handlePreviewPageSwitch(event) {
  const pageButton = event.target.closest("button[data-preview-page-id]");
  if (!pageButton || !pageButton.dataset.previewPageId || !state.previewBlockPages.length || state.previewMode !== "edit") {
    return false;
  }
  if (pageButton.dataset.previewPageId === state.previewActivePageId) {
    return true;
  }
  state.previewActivePageId = pageButton.dataset.previewPageId;
  renderPreviewStage();
  return true;
}

function handlePreviewBatchReplaceToggle() {
  state.previewReplaceOpen = !state.previewReplaceOpen;
  if (!state.previewReplaceOpen) {
    state.previewReplaceValue = "";
  }
  renderPreviewStage();
  return true;
}

function handlePreviewBatchReplaceCancel() {
  state.previewReplaceOpen = false;
  state.previewReplaceValue = "";
  renderPreviewStage();
  return true;
}

function handlePreviewBatchReplaceApply() {
  const searchQuery = state.previewSearchQuery.trim();
  if (!searchQuery) {
    setMessage(els.previewMessage, previewCopy("请先输入要搜索的术语。", "Enter a term to search first."), true);
    return true;
  }

  let replacedCount = 0;
  state.previewBlockPages.forEach((page) => {
    getPreviewEditableBlocks([page]).forEach((block) => {
      const occurrences = block.translatedText.split(searchQuery).length - 1;
      if (!occurrences) {
        return;
      }
      block.translatedText = block.translatedText.replaceAll(searchQuery, state.previewReplaceValue);
      block.searchText = buildPreviewSearchText(block.sourceText, block.translatedText);
      replacedCount += occurrences;
    });
  });

  if (!replacedCount) {
    setMessage(els.previewMessage, previewCopy("没有匹配到可替换的术语。", "No matching terms were found to replace."), true);
    return true;
  }

  state.previewDirty = true;
  state.previewReplaceOpen = false;
  state.previewReplaceValue = "";
  syncPreviewToolbar();
  renderPreviewStage();
  setMessage(
    els.previewMessage,
    previewCopy(`已批量替换 ${replacedCount} 处术语。`, `Replaced ${replacedCount} term occurrences.`)
  );
  return true;
}

async function handlePreviewEditToggle() {
  if (!state.previewJob) {
    return;
  }

  if (state.previewMode === "view") {
    try {
      const alreadyLoaded = Boolean(state.previewText);
      await ensurePreviewTextLoaded();
      state.previewMode = "edit";
      if (!alreadyLoaded) {
        state.previewDirty = false;
      }
      renderPreviewStage();
    } catch (error) {
      setMessage(els.previewMessage, error.message, true);
    }
    return;
  }

  state.previewMode = "view";
  renderPreviewStage();
}

async function handlePreviewSave() {
  if (!state.previewJob || state.previewMode !== "edit" || !state.previewText) {
    return;
  }

  setMessage(els.previewMessage, "");
  try {
    let payload = null;
    if (documentKind(state.previewJob.input_file.original_name) === "pdf") {
      const overflowCount = countPreviewOverflowBlocks();
      if (overflowCount) {
        setMessage(
          els.previewMessage,
          previewCopy("仍有编辑区域超出边界，请先缩短译文。", "Some editable areas still overflow. Shorten the translation first."),
          true
        );
        return;
      }

      payload = {
        status: "validated",
        payload: state.previewBlockPages.flatMap((page) =>
          getPreviewEditableBlocks([page])
            .filter((block) => block.isDirty)
            .map((block) => ({
              [block.payloadKey]: block.id,
              tgt_text: block.translatedText,
              font_size_final: block.fontSizeCurrent,
            }))
        ),
      };
    } else {
      payload = {
        pages: state.previewText.pages.map((page) => ({
          id: page.id,
          translated_text: page.translated_text,
        })),
      };
    }

    state.previewText = await api(`/jobs/${state.previewJobId}/preview`, {
      method: "PUT",
      body: JSON.stringify(payload),
      headers: { "Content-Type": "application/json" },
    });
    buildPreviewBlockPages();
    if (documentKind(state.previewJob.input_file.original_name) === "pdf") {
      await refreshTranslatedPreviewDocument();
    }
    state.previewDirty = false;
    renderPreviewStage();
    setMessage(els.previewMessage, previewCopy("修改已保存。", "Edits saved."));
  } catch (error) {
    setMessage(els.previewMessage, error.message, true);
  }
}

async function handlePreviewDownload() {
  if (!state.previewJobId) {
    return;
  }
  try {
    await downloadJob(state.previewJobId);
  } catch (error) {
    setMessage(els.previewMessage, error.message, true);
  }
}

async function handlePreviewBack() {
  clearPreviewState();
  await navigateTo("/");
}

function handlePreviewStagePaste(event) {
  const blockEditor = event.target.closest("[data-preview-block-id][contenteditable='true']");
  if (!blockEditor) {
    return;
  }

  event.preventDefault();
  const pastedText = event.clipboardData?.getData("text/plain") || "";
  document.execCommand("insertText", false, pastedText);
}

function handlePreviewStageClick(event) {
  if (event.target.closest("button[data-preview-batch-replace-toggle]")) {
    handlePreviewBatchReplaceToggle();
    return;
  }

  if (event.target.closest("button[data-preview-batch-replace-cancel]")) {
    handlePreviewBatchReplaceCancel();
    return;
  }

  if (event.target.closest("button[data-preview-batch-replace-apply]")) {
    handlePreviewBatchReplaceApply();
    return;
  }

  if (handlePreviewPageSwitch(event)) {
    return;
  }

  const button = event.target.closest("button[data-preview-zoom-kind]");
  if (!button) {
    return;
  }

  const kind = button.dataset.previewZoomKind;
  const step = Number(button.dataset.previewZoomStep);
  const nextZoom = state.previewZoom[kind] + step * PREVIEW_ZOOM_STEP;
  state.previewZoom[kind] = Math.min(PREVIEW_MAX_ZOOM, Math.max(PREVIEW_MIN_ZOOM, nextZoom));
  updateZoomValue(kind);
  void renderActivePdfPanes([kind], { preserveScroll: true });
}

function handlePreviewPaneScroll(event) {
  const body = event.target.closest?.("[data-pdf-scroll-kind]");
  if (!body || !state.previewJob || state.previewMode !== "view" || documentKind(state.previewJob.input_file.original_name) !== "pdf") {
    return;
  }

  const kind = body.dataset.pdfScrollKind;
  const ratio = currentScrollRatio(body);
  state.previewScrollRatio[kind] = ratio;

  if (state.previewScrollLock === kind) {
    return;
  }

  const otherKind = kind === "source" ? "translated" : "source";
  const otherBody = getPdfPaneBody(otherKind);
  if (!otherBody) {
    return;
  }

  state.previewScrollLock = kind;
  state.previewScrollRatio[otherKind] = ratio;
  applyScrollRatio(otherBody, ratio);
  window.requestAnimationFrame(() => {
    state.previewScrollLock = null;
  });
}

let previewResizeTimer = null;

function handleWindowResize() {
  if (!state.previewJob || documentKind(state.previewJob.input_file.original_name) !== "pdf") {
    return;
  }

  window.clearTimeout(previewResizeTimer);
  previewResizeTimer = window.setTimeout(() => {
    const kinds = ["source", "translated"];
    const options =
      state.previewMode === "edit"
        ? {
            preserveScroll: true,
            pageNumbers: [getActivePreviewBlockPage()?.pageNumber || 1],
          }
        : { preserveScroll: true };
    void renderActivePdfPanes(kinds, options);
  }, 120);
}

function handleMoreSettingsToggle() {
  state.workspaceMoreSettingsOpen = !state.workspaceMoreSettingsOpen;
  renderWorkspaceMoreSettings();
}

function handleUiLanguageChange(event) {
  persistUiLanguage(event.target.value);
  applyUiLanguage();
}

function scrollJobs(direction) {
  els.jobsList.scrollBy({
    left: direction * 360,
    behavior: "smooth",
  });
}

async function handleWorkspaceHome() {
  await navigateTo("/");
}

async function handleAdminEntry() {
  await navigateTo("/admin/settings");
}

async function handleAdminNavClick(event) {
  const button = event.target.closest("button[data-admin-route]");
  if (!button) {
    return;
  }
  await navigateTo(`/admin/${button.dataset.adminRoute}`);
}

els.loginForm.addEventListener("submit", handleLogin);
els.uploadForm.addEventListener("submit", handleUpload);
els.jobsList.addEventListener("click", handleJobAction);
els.jobDetail.addEventListener("click", handleJobAction);
els.settingsForm.addEventListener("submit", handleSettingsSave);
els.testModelButton.addEventListener("click", handleModelTest);
els.createUserForm.addEventListener("submit", handleCreateUser);
els.usersList.addEventListener("click", handleUserAction);
els.refreshButton.addEventListener("click", refreshAll);
els.logoutButton.addEventListener("click", handleLogout);
els.workspaceHomeButton.addEventListener("click", handleWorkspaceHome);
els.adminEntryButton.addEventListener("click", handleAdminEntry);
els.dropZone.addEventListener("click", handleDropZoneClick);
els.dropZone.addEventListener("keydown", handleDropZoneKeydown);
els.dropZone.addEventListener("dragover", handleDragOver);
els.dropZone.addEventListener("dragleave", handleDragLeave);
els.dropZone.addEventListener("drop", handleDrop);
els.browseFilesButton.addEventListener("click", (event) => {
  event.stopPropagation();
  els.uploadFile.click();
});
els.clearFileButton.addEventListener("click", handleClearFile);
els.uploadFile.addEventListener("change", handleFileChange);
els.moreSettingsButton.addEventListener("click", handleMoreSettingsToggle);
els.uiLanguageSelect.addEventListener("change", handleUiLanguageChange);
els.jobsScrollPrev.addEventListener("click", () => {
  scrollJobs(-1);
});
els.jobsScrollNext.addEventListener("click", () => {
  scrollJobs(1);
});
els.previewEditToggle.addEventListener("click", handlePreviewEditToggle);
els.previewSaveButton.addEventListener("click", handlePreviewSave);
els.previewDownloadButton.addEventListener("click", handlePreviewDownload);
els.previewBackButton.addEventListener("click", handlePreviewBack);
els.previewStage.addEventListener("click", handlePreviewStageClick);
els.previewStage.addEventListener("input", handlePreviewInput);
els.previewStage.addEventListener("paste", handlePreviewStagePaste);
els.previewStage.addEventListener("scroll", handlePreviewPaneScroll, true);
els.adminView.addEventListener("click", handleAdminNavClick);
window.addEventListener("popstate", () => {
  renderRoute().catch((error) => {
    console.error(error);
  });
});
window.addEventListener("resize", handleWindowResize);
document.addEventListener("click", (event) => {
  if (!event.target.closest(".custom-select")) {
    closeAllCustomSelects();
  }
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    closeAllCustomSelects();
  }
});

bootstrap();
