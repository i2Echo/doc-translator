<script setup>
import { reactive } from "vue";
import { useRouter } from "vue-router";
import { copy, login, state } from "../store";

const router = useRouter();
const form = reactive({
  email: "",
  password: "",
});

async function handleSubmit() {
  try {
    await login(form.email, form.password);
    form.email = "";
    form.password = "";
    router.replace("/");
  } catch (error) {
    state.messages.login = error.message;
  }
}
</script>

<template>
  <main class="login-shell">
    <section class="hero-panel">
      <p class="eyebrow">{{ copy("私有部署文档翻译", "Private document translation") }}</p>
      <h1>{{ copy("翻译、预览、校对都在同一个工作台里完成。", "Translate, preview, and review in one workspace.") }}</h1>
      <p class="hero-copy">
        {{
          copy(
            "文件保留在你自己的存储中；如果模型端点在外部网络，文本会按配置发送到该模型服务。",
            "Files remain in your own storage; if the model endpoint is external, document text is sent there by configuration."
          )
        }}
      </p>
      <div class="hero-pills">
        <span>PDF + DOCX</span>
        <span>{{ copy("在线校对", "Inline review") }}</span>
        <span>{{ copy("异步任务", "Async jobs") }}</span>
        <span>{{ copy("审计留痕", "Audit trail") }}</span>
      </div>
    </section>

    <section class="panel login-panel">
      <div class="panel-heading">
        <p class="eyebrow">{{ copy("本地登录", "Local sign-in") }}</p>
        <h2>{{ copy("进入翻译工作台", "Open the workspace") }}</h2>
        <p class="subtle">
          {{ copy("使用部署环境中创建的账号登录。", "Sign in with an account created in the deployment.") }}
        </p>
      </div>

      <form class="form-stack" @submit.prevent="handleSubmit">
        <label class="field">
          <span>{{ copy("邮箱", "Email") }}</span>
          <span class="control-shell">
            <input v-model="form.email" type="email" autocomplete="username" required />
          </span>
        </label>
        <label class="field">
          <span>{{ copy("密码", "Password") }}</span>
          <span class="control-shell">
            <input v-model="form.password" type="password" autocomplete="current-password" required />
          </span>
        </label>
        <button class="primary-button" type="submit" :disabled="state.pending.login">
          {{ state.pending.login ? copy("登录中…", "Signing in...") : copy("登录", "Sign in") }}
        </button>
        <p v-if="state.messages.login" class="message error">{{ state.messages.login }}</p>
      </form>
    </section>
  </main>
</template>
