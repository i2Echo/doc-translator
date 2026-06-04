const API_BASE = "/api/v1";
const STORAGE_KEY = "doc-translator-token";
const POLL_INTERVAL_MS = 5000;

const state = {
  token: window.localStorage.getItem(STORAGE_KEY),
  user: null,
  jobs: [],
  selectedJobId: null,
  pollHandle: null,
};

const els = {
  authPanel: document.getElementById("auth-panel"),
  dashboard: document.getElementById("dashboard"),
  adminArea: document.getElementById("admin-area"),
  loginForm: document.getElementById("login-form"),
  loginEmail: document.getElementById("login-email"),
  loginPassword: document.getElementById("login-password"),
  loginError: document.getElementById("login-error"),
  userBadge: document.getElementById("user-badge"),
  refreshButton: document.getElementById("refresh-button"),
  logoutButton: document.getElementById("logout-button"),
  uploadForm: document.getElementById("upload-form"),
  uploadFile: document.getElementById("upload-file"),
  sourceLanguage: document.getElementById("source-language"),
  targetLanguage: document.getElementById("target-language"),
  uploadMessage: document.getElementById("upload-message"),
  jobsList: document.getElementById("jobs-list"),
  jobCount: document.getElementById("job-count"),
  jobDetail: document.getElementById("job-detail"),
  detailStatus: document.getElementById("detail-status"),
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

function statusClass(status) {
  return `status-pill status-${status}`;
}

function setMessage(element, text, isError = false) {
  element.textContent = text || "";
  element.classList.toggle("error", Boolean(isError));
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
  renderAuthState();
}

function renderAuthState() {
  const signedIn = Boolean(state.user);
  els.authPanel.classList.toggle("hidden", signedIn);
  els.dashboard.classList.toggle("hidden", !signedIn);
  els.adminArea.classList.toggle("hidden", !signedIn || state.user.role !== "admin");
  if (signedIn) {
    els.userBadge.textContent = `${state.user.full_name} · ${state.user.role}`;
  }
}

function renderJobs() {
  els.jobCount.textContent = `${state.jobs.length} ${state.jobs.length === 1 ? "job" : "jobs"}`;
  if (!state.jobs.length) {
    els.jobsList.innerHTML = `<div class="empty-state">No jobs yet. Upload a PDF or DOCX to start.</div>`;
    return;
  }

  els.jobsList.innerHTML = state.jobs
    .map((job) => {
      const canCancel = ["queued", "parsing", "ocr_running", "translating", "rebuilding"].includes(job.status);
      const canRetry = ["failed", "cancelled"].includes(job.status);
      const canDownload = Boolean(job.output_file) && job.status === "completed";
      return `
        <article class="job-card">
          <div class="job-card-header">
            <div>
              <h4>${job.input_file.original_name}</h4>
              <div class="meta-line">${job.source_language} → ${job.target_language}</div>
            </div>
            <span class="${statusClass(job.status)}">${job.status.replace("_", " ")}</span>
          </div>
          <div class="progress-bar"><div class="progress-fill" style="width: ${job.progress}%"></div></div>
          <div class="meta-line">
            Progress ${job.progress}% · Created ${formatDate(job.created_at)} · ${job.created_by_user.full_name}
          </div>
          <div class="job-actions">
            <button data-action="view" data-job-id="${job.id}" class="ghost-button" type="button">View</button>
            ${canCancel ? `<button data-action="cancel" data-job-id="${job.id}" class="ghost-button" type="button">Cancel</button>` : ""}
            ${canRetry ? `<button data-action="retry" data-job-id="${job.id}" class="ghost-button" type="button">Retry</button>` : ""}
            ${canDownload ? `<button data-action="download" data-job-id="${job.id}" class="primary-button" type="button">Download</button>` : ""}
          </div>
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
  els.detailStatus.textContent = job.status.replace("_", " ");
  els.jobDetail.className = "job-detail detail-grid";
  els.jobDetail.innerHTML = `
    <div class="detail-topline">
      <div class="detail-meta">
        <strong>${job.input_file.original_name}</strong>
        <span class="${statusClass(job.status)}">${job.status.replace("_", " ")}</span>
      </div>
      <div class="meta-line">Progress ${job.progress}% · Model ${job.model_name_snapshot}</div>
      <div class="meta-line">
        Started ${formatDate(job.started_at)} · Completed ${formatDate(job.completed_at)} · Page count ${job.page_count ?? "n/a"}
      </div>
      ${
        job.error_message
          ? `<div class="privacy-note" style="background: rgba(157, 47, 47, 0.08); color: var(--danger);">${job.error_message}</div>`
          : ""
      }
    </div>
    <div class="timeline">
      ${events
        .map(
          (event) => `
        <div class="timeline-item">
          <div class="event-row">
            <strong>${event.message}</strong>
            <span class="meta-line">${formatDate(event.created_at)}</span>
          </div>
          <div class="event-copy">${event.details ? JSON.stringify(event.details) : ""}</div>
        </div>`
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
            <h4>${user.full_name}</h4>
            <div class="meta-line">${user.email}</div>
          </div>
          <span class="${statusClass(user.is_active ? "completed" : "failed")}">${user.role} · ${
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
        <span class="meta-line">${label}</span>
        <strong>${value}</strong>
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
          <strong>${log.action}</strong>
          <span class="meta-line">${formatDate(log.created_at)}</span>
        </div>
        <div class="audit-copy">
          ${log.actor ? `${log.actor.full_name} · ` : ""}${log.entity_type}${log.entity_id ? ` · ${log.entity_id}` : ""}
        </div>
        <div class="audit-copy">${log.details ? JSON.stringify(log.details) : ""}</div>
      </article>
    `
    )
    .join("");
}

function fillSettings(settings) {
  Object.entries(settingsFields).forEach(([key, element]) => {
    if (element.type === "checkbox") {
      element.checked = Boolean(settings[key]);
    } else {
      element.value = settings[key] ?? "";
    }
  });
  els.settingsPrivacy.textContent = settings.privacy_notice || "";
}

async function bootstrap() {
  renderAuthState();
  if (!state.token) {
    return;
  }
  try {
    state.user = await api("/auth/me");
    renderAuthState();
    await refreshAll();
    if (!state.pollHandle) {
      state.pollHandle = window.setInterval(refreshJobsOnly, POLL_INTERVAL_MS);
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
  const jobs = await api("/jobs");
  state.jobs = jobs;
  renderJobs();
  if (state.selectedJobId) {
    const job = await api(`/jobs/${state.selectedJobId}`);
    renderJobDetail(job);
  }
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
      state.pollHandle = window.setInterval(refreshJobsOnly, POLL_INTERVAL_MS);
    }
  } catch (error) {
    setMessage(els.loginError, error.message, true);
  }
}

async function handleUpload(event) {
  event.preventDefault();
  setMessage(els.uploadMessage, "");
  if (!els.uploadFile.files.length) {
    setMessage(els.uploadMessage, "Choose a PDF or DOCX file first.", true);
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
    els.targetLanguage.value = "English";
    setMessage(els.uploadMessage, "Job queued.");
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
    if (action === "view") {
      state.selectedJobId = jobId;
      const detail = await api(`/jobs/${jobId}`);
      renderJobDetail(detail);
      return;
    }
    if (action === "download") {
      const response = await api(`/jobs/${jobId}/download`);
      let blob;
      if (response.body) {
        const reader = response.body.getReader();
        const chunks = [];
        while (true) {
          const { done, value } = await reader.read();
          if (done) {
            break;
          }
          chunks.push(value);
        }
        blob = new Blob(chunks, {
          type: response.headers.get("content-type") || "application/octet-stream",
        });
      } else {
        blob = await response.blob();
      }
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
    setMessage(els.settingsMessage, "Settings saved.");
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
    setMessage(els.settingsMessage, `Connection OK in ${result.latency_ms} ms. Preview: ${result.preview}`);
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
    setMessage(els.userMessage, "User created.");
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

els.loginForm.addEventListener("submit", handleLogin);
els.uploadForm.addEventListener("submit", handleUpload);
els.jobsList.addEventListener("click", handleJobAction);
els.settingsForm.addEventListener("submit", handleSettingsSave);
els.testModelButton.addEventListener("click", handleModelTest);
els.createUserForm.addEventListener("submit", handleCreateUser);
els.usersList.addEventListener("click", handleUserAction);
els.refreshButton.addEventListener("click", refreshAll);
els.logoutButton.addEventListener("click", handleLogout);

bootstrap();
