<script setup>
import { computed, reactive, ref } from "vue";
import { useRouter } from "vue-router";
import AppSelect from "../components/AppSelect.vue";
import {
  cancelJob,
  copy,
  defaultUploadState,
  downloadJob,
  refreshAll,
  retryJob,
  selectJob,
  state,
  uploadJob,
} from "../store";
import { fileKindLabel, formatBytes, formatDate, formatJobStatus, languageName } from "../utils";

const router = useRouter();
const uploadForm = reactive({
  file: null,
  ...defaultUploadState(),
});
const fileInputRef = ref(null);
const languageOptions = [
  { value: "auto", label: "Auto / 自动检测" },
  { value: "Chinese", label: "Chinese / 中文" },
  { value: "English", label: "English" },
  { value: "Japanese", label: "Japanese / 日本語" },
  { value: "Korean", label: "Korean / 한국어" },
  { value: "German", label: "German / Deutsch" },
  { value: "French", label: "French / Français" },
  { value: "Spanish", label: "Spanish / Español" },
];
const targetLanguageOptions = languageOptions.filter((option) => option.value !== "auto");

const activeJobs = computed(() =>
  state.jobs.filter((job) => job.status === "queued" || job.status === "running").length
);

const workspaceModel = computed(() => {
  return state.settings?.model_name || state.jobs[0]?.model_name_snapshot || copy("托管模型", "Managed model");
});

function onFileChange(event) {
  const [file] = event.target.files || [];
  uploadForm.file = file || null;
}

function openFilePicker() {
  fileInputRef.value?.click();
}

async function submitUpload() {
  if (!uploadForm.file) {
    state.messages.upload = copy("请先选择 PDF 或 DOCX 文件。", "Choose a PDF or DOCX file first.");
    return;
  }

  try {
    await uploadJob(uploadForm.file, uploadForm.sourceLanguage, uploadForm.targetLanguage);
    uploadForm.file = null;
    uploadForm.sourceLanguage = "auto";
    uploadForm.targetLanguage = "Chinese";
    const fileInput = document.getElementById("upload-file-input");
    if (fileInput) {
      fileInput.value = "";
    }
  } catch (error) {
    state.messages.upload = error.message;
  }
}

function openPreview(jobId) {
  router.push(`/preview/${jobId}`);
}

function canPreview(job) {
  return job.status === "completed" && job.output_file;
}

function canRetry(job) {
  return job.status === "failed" || job.status === "cancelled";
}

function canCancel(job) {
  return job.status === "queued" || job.status === "running";
}
</script>

<template>
  <main class="workspace-grid">
    <section class="panel upload-card">
      <div class="panel-heading inline-between">
        <div>
          <p class="eyebrow">{{ copy("上传任务", "Upload job") }}</p>
          <h2>{{ copy("提交新的翻译文档", "Queue a document") }}</h2>
        </div>
        <button class="ghost-button" type="button" :disabled="state.pending.refresh" @click="refreshAll()">
          {{ copy("刷新任务", "Refresh jobs") }}
        </button>
      </div>

      <form class="form-stack card-scroll-body" @submit.prevent="submitUpload">
        <label class="upload-dropzone" for="upload-file-input">
          <input
            id="upload-file-input"
            ref="fileInputRef"
            type="file"
            accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            @change="onFileChange"
          />
          <div class="upload-copy">
            <strong>{{ copy("拖拽或选择 PDF / DOCX", "Drop or choose a PDF / DOCX") }}</strong>
            <p class="subtle">
              {{
                uploadForm.file
                  ? `${uploadForm.file.name} · ${formatBytes(uploadForm.file.size)}`
                  : copy("支持直接排队翻译并进入在线校对。", "Queue translation and review online.")
              }}
            </p>
          </div>
          <button class="ghost-button upload-picker-button" type="button" @click.prevent="openFilePicker()">
            {{ copy("选择文件", "Choose file") }}
          </button>
        </label>

        <div class="compact-grid two-up">
          <label class="field">
            <span>{{ copy("源语言", "Source language") }}</span>
            <AppSelect
              v-model="uploadForm.sourceLanguage"
              :options="languageOptions"
              :aria-label="copy('源语言', 'Source language')"
            />
          </label>
          <label class="field">
            <span>{{ copy("目标语言", "Target language") }}</span>
            <AppSelect
              v-model="uploadForm.targetLanguage"
              :options="targetLanguageOptions"
              :aria-label="copy('目标语言', 'Target language')"
            />
          </label>
        </div>

        <div class="stats-row">
          <div class="mini-stat">
            <span>{{ copy("当前模型", "Current model") }}</span>
            <strong>{{ workspaceModel }}</strong>
          </div>
          <div class="mini-stat">
            <span>{{ copy("活跃任务", "Active jobs") }}</span>
            <strong>{{ activeJobs }}</strong>
          </div>
        </div>

        <div class="button-row">
          <button class="primary-button" type="submit" :disabled="state.pending.upload">
            {{ state.pending.upload ? copy("提交中…", "Queuing...") : copy("开始翻译", "Start translation") }}
          </button>
        </div>
        <p v-if="state.messages.upload" class="message" :class="{ error: state.messages.upload.includes('Choose') || state.messages.upload.includes('请先') }">
          {{ state.messages.upload }}
        </p>
      </form>
    </section>

    <section class="panel jobs-card">
      <div class="panel-heading">
        <p class="eyebrow">{{ copy("最近任务", "Recent jobs") }}</p>
        <h2>{{ copy("队列、进度与预览入口", "Queue, progress, and preview") }}</h2>
      </div>

      <div v-if="!state.jobs.length" class="empty-state">
        {{ copy("还没有任务。先上传一个 PDF 或 DOCX。", "No jobs yet. Upload a PDF or DOCX to get started.") }}
      </div>

      <div v-else class="job-list">
        <article
          v-for="job in state.jobs"
          :key="job.id"
          class="job-card"
          :class="{ selected: state.selectedJobId === job.id }"
          @click="selectJob(job.id)"
        >
          <div class="job-card-main">
            <div class="job-card-copy">
              <p class="job-file" :title="job.input_file.original_name">{{ job.input_file.original_name }}</p>
              <p class="subtle">{{ fileKindLabel(job.input_file.original_name) }} · {{ formatDate(job.created_at) }}</p>
              <p class="subtle">
                {{ languageName(job.source_language) }} → {{ languageName(job.target_language) }}
              </p>
            </div>

            <div class="job-card-side">
              <span class="status-pill" :data-status="job.status">{{ formatJobStatus(job.status, copy) }}</span>

              <div v-if="(job.progress || 0) < 100" class="progress-row job-progress-inline">
                <div class="progress-track">
                  <div class="progress-bar" :style="{ width: `${job.progress || 0}%` }"></div>
                </div>
                <span>{{ job.progress || 0 }}%</span>
              </div>

              <div class="button-row tight job-actions">
                <button
                  v-if="canPreview(job)"
                  class="icon-button icon-button--bare icon-button--tiny"
                  type="button"
                  :aria-label="copy('预览', 'Preview')"
                  :title="copy('预览', 'Preview')"
                  @click.stop="openPreview(job.id)"
                >
                  <svg viewBox="0 0 20 20" fill="none" aria-hidden="true">
                    <path d="M1.75 10s3.25-5 8.25-5 8.25 5 8.25 5-3.25 5-8.25 5-8.25-5-8.25-5Z" />
                    <circle cx="10" cy="10" r="2.5" />
                  </svg>
                </button>
                <button
                  v-if="job.output_file"
                  class="icon-button icon-button--bare icon-button--tiny"
                  type="button"
                  :aria-label="copy('下载', 'Download')"
                  :title="copy('下载', 'Download')"
                  @click.stop="downloadJob(job.id)"
                >
                  <svg viewBox="0 0 20 20" fill="none" aria-hidden="true">
                    <path d="M10 3.5v8.25" />
                    <path d="m6.75 8.75 3.25 3.25 3.25-3.25" />
                    <path d="M4.5 14.5h11" />
                  </svg>
                </button>
                <button v-if="canCancel(job)" class="ghost-button danger-text" type="button" @click.stop="cancelJob(job.id)">
                  {{ copy("取消", "Cancel") }}
                </button>
                <button v-if="canRetry(job)" class="ghost-button" type="button" @click.stop="retryJob(job.id)">
                  {{ copy("重试", "Retry") }}
                </button>
              </div>
            </div>
          </div>
        </article>
      </div>
    </section>

    <section class="panel detail-card">
      <div class="panel-heading">
        <p class="eyebrow">{{ copy("任务详情", "Job detail") }}</p>
        <h2>{{ copy("事件、文件与运行快照", "Events, files, and runtime snapshot") }}</h2>
      </div>

      <div v-if="!state.selectedJob" class="empty-state">
        {{ copy("从左侧选择任务以查看详情。", "Select a job to inspect its details.") }}
      </div>

      <template v-else>
        <div class="detail-body">
          <div class="compact-grid two-up">
            <div class="meta-card">
              <span>{{ copy("状态", "Status") }}</span>
              <strong>{{ formatJobStatus(state.selectedJob.status, copy) }}</strong>
            </div>
            <div class="meta-card">
              <span>{{ copy("模型", "Model") }}</span>
              <strong :title="state.selectedJob.model_name_snapshot">{{ state.selectedJob.model_name_snapshot }}</strong>
            </div>
            <div class="meta-card">
              <span>{{ copy("原文件", "Input file") }}</span>
              <strong :title="state.selectedJob.input_file.original_name">{{ state.selectedJob.input_file.original_name }}</strong>
            </div>
            <div class="meta-card">
              <span>{{ copy("输出文件", "Output file") }}</span>
              <strong :title="state.selectedJob.output_file?.original_name || ''">{{ state.selectedJob.output_file?.original_name || "—" }}</strong>
            </div>
          </div>

          <div class="timeline">
            <article v-for="event in state.selectedJob.events" :key="event.id" class="timeline-item">
              <div class="timeline-item-head">
                <strong>{{ event.message }}</strong>
                <span class="subtle">{{ formatDate(event.created_at) }}</span>
              </div>
              <p class="subtle">{{ event.level }}</p>
            </article>
          </div>
        </div>
      </template>
    </section>
  </main>
</template>
