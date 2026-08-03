<script setup>
import { computed, reactive, ref, watch } from "vue";
import { useRouter } from "vue-router";
import AppSelect from "../components/AppSelect.vue";
import {
  cachedModels,
  clearCachedModels,
  clearModelTestResult,
  copy,
  createUser,
  isAdmin,
  loadAuditPage,
  listModels,
  loadMoreUsers,
  refreshAll,
  saveSettings,
  setMessage,
  state,
  testModel,
  toggleUserState,
} from "../store";
import { formatBytes, formatDate, formatRole } from "../utils";

const props = defineProps({
  page: {
    type: String,
    default: "settings",
  },
});

const router = useRouter();
const pages = ["settings", "users", "storage", "audit"];

const settingsForm = reactive({
  storage_mode: "local",
  local_storage_path: "",
  file_retention_days: 30,
  model_api_format: "chat_completions",
  model_base_url: "",
  model_api_key: "",
  model_name: "",
  model_timeout_seconds: 120,
  ocr_enabled: true,
  ocr_language_hint: "chi_sim+eng",
  max_upload_mb: 100,
  max_concurrent_jobs: 10,
});
const availableModels = ref([]);

const userForm = reactive({
  full_name: "",
  email: "",
  password: "",
  role: "user",
});
const roleOptions = computed(() => [
  { value: "user", label: copy("标准用户", "Standard user") },
  { value: "admin", label: copy("管理员", "Admin") },
]);
const modelApiFormatOptions = computed(() => [
  { value: "anthropic_messages", label: "Anthropic Messages (/v1/messages)" },
  { value: "chat_completions", label: "Chat Completions (/chat/completions)" },
  { value: "responses", label: "Responses (/responses)" },
]);
const storageModeOptions = computed(() => [
  { value: "local", label: copy("本地存储（local）", "Local storage (local)") },
]);
const modelNameOptions = computed(() =>
  [...new Set([settingsForm.model_name, ...availableModels.value].filter(Boolean))].map((model) => ({
    value: model,
    label: model,
  }))
);

const activePage = computed(() => (pages.includes(props.page) ? props.page : "settings"));
const visibleUserCount = computed(() => state.users.length);
const auditTotalPages = computed(() => Math.max(1, Math.ceil(state.auditPage.total / state.auditPage.limit)));
const auditPageStart = computed(() => (state.auditPage.total ? state.auditPage.offset + 1 : 0));
const auditPageEnd = computed(() => Math.min(state.auditPage.offset + state.audit.length, state.auditPage.total));

watch(
  () => state.settings,
  (value) => {
    if (!value) {
      return;
    }
    // Copy every field except model_api_key: the stored value is masked
    // (****<last4>) and must not be echoed back on save, or it would overwrite
    // the real key. The key field stays blank until the admin types a new one.
    const { model_api_key, ...rest } = value;
    Object.assign(settingsForm, rest);
    settingsForm.model_api_key = "";
  },
  { immediate: true }
);

watch(
  () => [settingsForm.model_api_format, settingsForm.model_base_url, settingsForm.model_api_key],
  () => {
    availableModels.value = settingsForm.model_api_key ? [] : cachedModels(modelRequestPayload());
  },
  { immediate: true }
);

watch(
  () => [
    settingsForm.model_api_format,
    settingsForm.model_base_url,
    settingsForm.model_api_key,
    settingsForm.model_name,
    settingsForm.model_timeout_seconds,
  ],
  clearModelTestResult
);

if (isAdmin.value && !state.settings) {
  void refreshAll();
}

function navigate(page) {
  router.replace(`/admin/${page}`);
}

function modelRequestPayload() {
  const payload = {
    model_api_format: settingsForm.model_api_format,
    model_base_url: settingsForm.model_base_url,
    model_name: settingsForm.model_name,
    model_timeout_seconds: Number(settingsForm.model_timeout_seconds),
  };
  if (settingsForm.model_api_key && settingsForm.model_api_key.trim()) {
    payload.model_api_key = settingsForm.model_api_key.trim();
  }
  return payload;
}

async function submitSettings() {
  try {
    // Partial update: omit model_api_key when blank so the backend keeps the
    // existing key. Only send it when the admin entered a new value.
    const payload = {
      storage_mode: settingsForm.storage_mode,
      local_storage_path: settingsForm.local_storage_path,
      file_retention_days: Number(settingsForm.file_retention_days),
      model_api_format: settingsForm.model_api_format,
      model_base_url: settingsForm.model_base_url,
      model_name: settingsForm.model_name,
      model_timeout_seconds: Number(settingsForm.model_timeout_seconds),
      ocr_enabled: settingsForm.ocr_enabled,
      ocr_language_hint: settingsForm.ocr_language_hint,
      max_upload_mb: Number(settingsForm.max_upload_mb),
      max_concurrent_jobs: Number(settingsForm.max_concurrent_jobs),
    };
    if (settingsForm.model_api_key && settingsForm.model_api_key.trim()) {
      payload.model_api_key = settingsForm.model_api_key.trim();
    }
    await saveSettings(payload);
  } catch (error) {
    setMessage("settings", error.message, "error");
  }
}

async function runModelTest() {
  try {
    await testModel(modelRequestPayload());
  } catch (error) {
    setMessage("settings", error.message, "error");
  }
}

async function loadModelList() {
  try {
    availableModels.value = await listModels(modelRequestPayload());
  } catch (error) {
    setMessage("settings", error.message, "error");
  }
}

function clearModelListCache() {
  clearCachedModels();
  availableModels.value = [];
}

async function submitUser() {
  try {
    await createUser({
      ...userForm,
      is_active: true,
    });
    userForm.full_name = "";
    userForm.email = "";
    userForm.password = "";
    userForm.role = "user";
  } catch (error) {
    setMessage("users", error.message, "error");
  }
}

function handleUserListScroll(event) {
  const element = event.currentTarget;
  if (!element || state.pending.userList || !state.usersPage.hasMore) {
    return;
  }
  const remaining = element.scrollHeight - element.scrollTop - element.clientHeight;
  if (remaining <= 120) {
    loadMoreUsers().catch((error) => {
      setMessage("users", error.message, "error");
    });
  }
}

function requestMoreUsers() {
  loadMoreUsers().catch((error) => {
    setMessage("users", error.message, "error");
  });
}

function changeAuditPage(page) {
  if (page < 1 || page > auditTotalPages.value || page === state.auditPage.page || state.pending.audit) {
    return;
  }
  loadAuditPage(page).catch((error) => {
    setMessage("audit", error.message, "error");
  });
}
</script>

<template>
  <main class="admin-layout">
    <section v-if="!isAdmin" class="panel empty-state">
      {{ copy("只有管理员可以访问此页面。", "Only admins can access this page.") }}
    </section>

    <template v-else>
      <section class="panel admin-nav-panel">
        <div class="panel-heading">
          <p class="eyebrow">{{ copy("管理后台", "Admin") }}</p>
          <h2>{{ copy("系统设置与运营数据", "Settings and operations") }}</h2>
        </div>

        <div class="button-row tight">
          <button
            v-for="pageName in pages"
            :key="pageName"
            class="ghost-button"
            :class="{ active: activePage === pageName }"
            type="button"
            @click="navigate(pageName)"
          >
            {{
              pageName === "settings"
                ? copy("设置", "Settings")
                : pageName === "users"
                  ? copy("用户", "Users")
                  : pageName === "storage"
                    ? copy("存储", "Storage")
                    : copy("审计", "Audit")
            }}
          </button>
        </div>
      </section>

      <section v-if="activePage === 'settings'" class="panel">
        <div class="panel-heading">
          <p class="eyebrow">{{ copy("模型与存储", "Model and storage") }}</p>
          <h2>{{ copy("修改运行时配置", "Adjust runtime configuration") }}</h2>
        </div>

        <form class="form-stack" @submit.prevent="submitSettings">
          <div class="compact-grid two-up">
            <label class="field">
              <span>Base URL</span>
              <span class="control-shell">
                <input v-model="settingsForm.model_base_url" type="url" required @input="clearModelListCache" />
              </span>
            </label>
            <label class="field">
              <span>{{ copy("API 格式", "API format") }}</span>
              <AppSelect
                v-model="settingsForm.model_api_format"
                :options="modelApiFormatOptions"
                :aria-label="copy('API 格式', 'API format')"
              />
            </label>
            <label class="field">
              <span>API Key</span>
              <span class="control-shell">
                <input
                  v-model="settingsForm.model_api_key"
                  type="password"
                  autocomplete="new-password"
                  :placeholder="state.settings?.model_api_key ? copy('已设置（当前：', 'Set (current: ') + state.settings.model_api_key + ')' : copy('未设置', 'Not set')"
                  @input="clearModelListCache"
                />
              </span>
            </label>
            <label class="field">
              <span>{{ copy("模型列表", "Model list") }}</span>
              <span class="model-list-control">
                <AppSelect
                  v-model="settingsForm.model_name"
                  :options="modelNameOptions"
                  :placeholder="copy('先获取模型列表', 'Load model list first')"
                  :aria-label="copy('模型列表', 'Model list')"
                />
                <button class="ghost-button" type="button" :disabled="state.pending.modelList" @click="loadModelList">
                  {{ state.pending.modelList ? copy("加载中…", "Loading...") : copy("获取列表", "Load") }}
                </button>
              </span>
            </label>
            <label class="field">
              <span>{{ copy("超时（秒）", "Timeout (seconds)") }}</span>
              <span class="control-shell">
                <input v-model="settingsForm.model_timeout_seconds" type="number" min="1" max="3600" required />
              </span>
            </label>
            <label class="field">
              <span>{{ copy("存储模式", "Storage mode") }}</span>
              <AppSelect
                v-model="settingsForm.storage_mode"
                :options="storageModeOptions"
                :aria-label="copy('存储模式', 'Storage mode')"
              />
            </label>
            <label class="field">
              <span>{{ copy("本地存储路径", "Local storage path") }}</span>
              <span class="control-shell">
                <input v-model="settingsForm.local_storage_path" type="text" required />
              </span>
            </label>
            <label class="field">
              <span>{{ copy("保留天数", "Retention days") }}</span>
              <span class="control-shell">
                <input v-model="settingsForm.file_retention_days" type="number" min="1" max="3650" required />
              </span>
            </label>
            <label class="field">
              <span>{{ copy("上传上限（MB）", "Max upload (MB)") }}</span>
              <span class="control-shell">
                <input v-model="settingsForm.max_upload_mb" type="number" min="1" max="2048" required />
              </span>
            </label>
            <label class="field">
              <span>{{ copy("最大并发任务", "Max concurrent jobs") }}</span>
              <span class="control-shell">
                <input v-model="settingsForm.max_concurrent_jobs" type="number" min="1" max="16" required />
              </span>
            </label>
            <label class="field">
              <span>OCR language hint</span>
              <span class="control-shell">
                <input v-model="settingsForm.ocr_language_hint" type="text" required />
              </span>
            </label>
          </div>

          <div class="switch-field">
            <label class="switch-control" :aria-label="copy('为扫描 PDF 启用 OCR', 'Enable OCR for scanned PDFs')">
              <input v-model="settingsForm.ocr_enabled" class="switch-input" type="checkbox" />
              <span class="switch-indicator" aria-hidden="true">
                <span class="switch-thumb"></span>
              </span>
            </label>
            <span class="switch-copy">{{ copy("为扫描 PDF 启用 OCR", "Enable OCR for scanned PDFs") }}</span>
          </div>

          <div class="button-row">
            <button class="primary-button" type="submit" :disabled="state.pending.settings">
              {{ state.pending.settings ? copy("保存中…", "Saving...") : copy("保存设置", "Save settings") }}
            </button>
            <button class="ghost-button" type="button" :disabled="state.pending.modelTest" @click="runModelTest">
              {{ state.pending.modelTest ? copy("测试中…", "Testing...") : copy("测试连接", "Test connection") }}
            </button>
          </div>
          <p v-if="state.messages.settings" class="message" :class="state.messageLevels.settings">
            {{ state.messages.settings }}
          </p>
          <p
            v-if="state.modelTestResult.connectionMessage"
            class="message"
            :class="state.modelTestResult.connectionLevel"
          >
            {{ state.modelTestResult.connectionMessage }}
          </p>
          <p
            v-if="state.modelTestResult.validationMessage"
            class="message"
            :class="state.modelTestResult.validationLevel"
          >
            {{ state.modelTestResult.validationMessage }}
          </p>
          <p v-if="state.settings?.privacy_notice" class="subtle">{{ state.settings.privacy_notice }}</p>
        </form>
      </section>

      <section v-else-if="activePage === 'users'" class="admin-users-panel">
        <aside class="panel admin-user-sidebar">
          <div class="panel-heading">
            <p class="eyebrow">{{ copy("用户管理", "Users") }}</p>
            <h2>{{ copy("新增账号", "Create account") }}</h2>
          </div>

          <form class="form-stack" @submit.prevent="submitUser">
            <label class="field">
              <span>{{ copy("姓名", "Full name") }}</span>
              <span class="control-shell">
                <input v-model="userForm.full_name" type="text" required />
              </span>
            </label>
            <label class="field">
              <span>{{ copy("邮箱", "Email") }}</span>
              <span class="control-shell">
                <input v-model="userForm.email" type="email" required />
              </span>
            </label>
            <label class="field">
              <span>{{ copy("密码", "Password") }}</span>
              <span class="control-shell">
                <input v-model="userForm.password" type="password" minlength="8" required />
              </span>
            </label>
            <label class="field">
              <span>{{ copy("角色", "Role") }}</span>
              <AppSelect
                v-model="userForm.role"
                :options="roleOptions"
                :aria-label="copy('角色', 'Role')"
              />
            </label>
            <button class="primary-button" type="submit" :disabled="state.pending.userCreate">
              {{ state.pending.userCreate ? copy("创建中…", "Creating...") : copy("创建用户", "Create user") }}
            </button>
            <p v-if="state.messages.users" class="message" :class="state.messageLevels.users">
              {{ state.messages.users }}
            </p>
          </form>
        </aside>

        <section class="panel admin-user-list-panel">
          <div class="admin-list-heading">
            <div>
              <p class="eyebrow">{{ copy("账号列表", "Accounts") }}</p>
              <h2>{{ copy("权限与状态", "Access and status") }}</h2>
            </div>
            <span class="status-pill">{{ visibleUserCount }} / {{ state.usersPage.total }}</span>
          </div>

          <div class="user-list admin-scroll-list" @scroll="handleUserListScroll">
            <article v-for="user in state.users" :key="user.id" class="user-card user-card--row">
              <div class="user-card-main">
                <div>
                  <strong>{{ user.full_name }}</strong>
                  <p class="subtle">{{ user.email }}</p>
                </div>
                <div class="user-meta">
                  <span class="status-pill">{{ formatRole(user.role, copy) }}</span>
                  <span class="status-pill" :data-status="user.is_active ? 'completed' : 'cancelled'">
                    {{ user.is_active ? copy("启用中", "Active") : copy("已停用", "Disabled") }}
                  </span>
                </div>
              </div>
              <div class="button-row tight user-card-actions">
                <button class="ghost-button" type="button" @click="toggleUserState(user.id, { is_active: !user.is_active })">
                  {{ user.is_active ? copy("停用", "Disable") : copy("启用", "Enable") }}
                </button>
                <button
                  class="ghost-button"
                  type="button"
                  @click="toggleUserState(user.id, { role: user.role === 'admin' ? 'user' : 'admin' })"
                >
                  {{ user.role === "admin" ? copy("降为用户", "Make user") : copy("提升管理员", "Make admin") }}
                </button>
              </div>
            </article>

            <div v-if="state.pending.userList" class="list-footer">{{ copy("加载中…", "Loading...") }}</div>
            <button
              v-else-if="state.usersPage.hasMore"
              class="ghost-button list-footer-button"
              type="button"
              @click="requestMoreUsers"
            >
              {{ copy("加载更多", "Load more") }}
            </button>
          </div>
        </section>
      </section>

      <section v-else-if="activePage === 'storage'" class="panel">
        <div class="panel-heading">
          <p class="eyebrow">{{ copy("存储概览", "Storage summary") }}</p>
          <h2>{{ copy("文件体量与保留情况", "Files and retention footprint") }}</h2>
        </div>

        <div v-if="!state.storage" class="empty-state">{{ copy("正在加载存储信息…", "Loading storage metrics...") }}</div>
        <div v-else class="compact-grid three-up">
          <div class="meta-card">
            <span>{{ copy("总占用", "Total size") }}</span>
            <strong>{{ formatBytes(state.storage.total_bytes) }}</strong>
          </div>
          <div class="meta-card">
            <span>{{ copy("有效文件", "Active files") }}</span>
            <strong>{{ state.storage.active_file_count }}</strong>
          </div>
          <div class="meta-card">
            <span>{{ copy("输出文件", "Output files") }}</span>
            <strong>{{ state.storage.output_file_count }}</strong>
          </div>
        </div>
      </section>

      <section v-else class="panel admin-audit-panel">
        <div class="admin-list-heading">
          <div>
            <p class="eyebrow">{{ copy("审计日志", "Audit log") }}</p>
            <h2>{{ copy("最近操作记录", "Recent actions") }}</h2>
          </div>
          <span class="status-pill">{{ auditPageStart }}-{{ auditPageEnd }} / {{ state.auditPage.total }}</span>
        </div>

        <div class="timeline admin-scroll-list">
          <article v-for="entry in state.audit" :key="entry.id" class="timeline-item">
            <div class="timeline-item-head">
              <strong>{{ entry.action }}</strong>
              <span class="subtle">{{ formatDate(entry.created_at) }}</span>
            </div>
            <p class="subtle">
              {{ entry.actor?.full_name || "System" }} · {{ entry.entity_type }} · {{ entry.entity_id || "—" }}
            </p>
          </article>
          <div v-if="state.pending.audit" class="list-footer">{{ copy("加载中…", "Loading...") }}</div>
          <div v-else-if="!state.audit.length" class="empty-state">{{ copy("暂无审计记录。", "No audit records.") }}</div>
        </div>

        <footer class="admin-pagination-bar">
          <button class="ghost-button" type="button" :disabled="state.auditPage.page <= 1 || state.pending.audit" @click="changeAuditPage(state.auditPage.page - 1)">
            {{ copy("上一页", "Previous") }}
          </button>
          <span>{{ state.auditPage.page }} / {{ auditTotalPages }}</span>
          <button class="ghost-button" type="button" :disabled="state.auditPage.page >= auditTotalPages || state.pending.audit" @click="changeAuditPage(state.auditPage.page + 1)">
            {{ copy("下一页", "Next") }}
          </button>
        </footer>
      </section>
    </template>
  </main>
</template>
