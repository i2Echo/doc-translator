<script setup>
import { computed, onMounted, watch } from "vue";
import { RouterView, useRoute, useRouter } from "vue-router";
import AppSelect from "./components/AppSelect.vue";
import LoginView from "./views/LoginView.vue";
import { bootstrapSession, copy, isAdmin, isAuthenticated, logout, setUiLanguage, state } from "./store";

const route = useRoute();
const router = useRouter();
const isPreviewRoute = computed(() => route.name === "preview");
const isWorkspaceRoute = computed(() => isAuthenticated.value && route.name === "workspace");
const isAdminRoute = computed(() => isAuthenticated.value && route.name === "admin");
const uiLanguageOptions = [
  { value: "zh-CN", label: "简体中文" },
  { value: "en", label: "English" },
];

const userLabel = computed(() => {
  if (!state.user) {
    return "";
  }
  return `${state.user.full_name} · ${state.user.email}`;
});

watch(
  () => route.name,
  (name) => {
    if (name === "admin" && isAuthenticated.value && !isAdmin.value) {
      router.replace("/");
    }
  },
  { immediate: true }
);

onMounted(() => {
  void bootstrapSession();
});
</script>

<template>
  <div class="app-shell">
    <div
      class="app-frame"
      :class="{ 'app-frame--preview': isPreviewRoute, 'app-frame--workspace': isWorkspaceRoute, 'app-frame--admin': isAdminRoute }"
    >
      <LoginView v-if="!isAuthenticated" />

      <template v-else>
        <header v-if="!isPreviewRoute" class="topbar">
          <div class="brand-block">
            <p class="eyebrow">{{ copy("私有部署文档翻译", "Private document translation") }}</p>
            <div class="brand-title">
              <span class="brand-mark" aria-hidden="true">
                <svg viewBox="0 0 20 20" fill="none">
                  <path d="M2.5 5.5h6M5.5 3.5v2M3.8 5.5c.6 2 1.9 3.7 3.7 4.7M7.4 5.5c-.7 1.8-1.9 3.3-3.5 4.3" />
                  <path d="m9.5 16.5 3-7 3 7M10.7 13.8h3.6" />
                </svg>
              </span>
              <h1>Doc Translator</h1>
            </div>
            <p class="subtle">{{ userLabel }}</p>
          </div>

          <div class="topbar-actions">
            <AppSelect
              :model-value="state.uiLanguage"
              :options="uiLanguageOptions"
              :aria-label="copy('界面语言', 'Interface language')"
              compact
              align="end"
              @update:model-value="setUiLanguage"
            />
            <button class="ghost-button" type="button" @click="router.push('/')">
              {{ copy("工作台", "Workspace") }}
            </button>
            <button v-if="isAdmin" class="ghost-button" type="button" @click="router.push('/admin/settings')">
              {{ copy("管理", "Admin") }}
            </button>
            <button class="ghost-button danger-text" type="button" @click="logout()">
              {{ copy("退出", "Log out") }}
            </button>
          </div>
        </header>

        <RouterView />
      </template>
    </div>
  </div>
</template>
