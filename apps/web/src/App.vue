<script setup>
import { computed, onMounted, watch } from "vue";
import { RouterView, useRoute, useRouter } from "vue-router";
import AppSelect from "./components/AppSelect.vue";
import LoginView from "./views/LoginView.vue";
import { bootstrapSession, copy, isAdmin, isAuthenticated, logout, refreshAll, setUiLanguage, state } from "./store";

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
    <div class="ambient ambient-left"></div>
    <div class="ambient ambient-right"></div>

    <div
      class="app-frame"
      :class="{ 'app-frame--preview': isPreviewRoute, 'app-frame--workspace': isWorkspaceRoute, 'app-frame--admin': isAdminRoute }"
    >
      <LoginView v-if="!isAuthenticated" />

      <template v-else>
        <header v-if="!isPreviewRoute" class="topbar">
          <div class="brand-block">
            <p class="eyebrow">{{ copy("私有部署文档翻译", "Private document translation") }}</p>
            <h1>Doc Translator</h1>
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
            <button class="ghost-button" type="button" :disabled="state.pending.refresh" @click="refreshAll()">
              {{ copy("刷新", "Refresh") }}
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
