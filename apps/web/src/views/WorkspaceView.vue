<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from "vue";
import { useRouter } from "vue-router";
import AppSelect from "../components/AppSelect.vue";
import {
  cancelJob,
  copy,
  defaultUploadState,
  downloadJob,
  downloadJobDebugArtifact,
  refreshAll,
  retryJob,
  selectJob,
  state,
  uploadJobs,
} from "../store";
import {
  fileKindLabel,
  formatBytes,
  formatDate,
  formatJobStatus,
  isJobExpired,
  jobStatusKey,
  languageName,
  sourceLanguageOptions,
  targetLanguageOptions,
} from "../utils";

const router = useRouter();
const uploadForm = reactive({
  files: [],
  ...defaultUploadState(),
});
const fileInputRef = ref(null);
const activeJobStatuses = new Set(["queued", "running", "parsing", "ocr_running", "translating", "rebuilding", "validating"]);
const terminalJobStatuses = new Set(["completed", "failed", "cancelled"]);
const nowMs = ref(Date.now());
let clockHandle = null;
const activeJobs = computed(() => state.jobs.filter((job) => activeJobStatuses.has(job.status)).length);
const localizedSourceLanguageOptions = computed(() => sourceLanguageOptions(copy));
const localizedTargetLanguageOptions = computed(() => targetLanguageOptions(copy));
const supportedUploadExtensions = new Set([".pdf", ".docx"]);
const uploadMessageIsError = computed(() => {
  const message = state.messages.upload;
  return Boolean(
    message &&
      (message.includes("Choose") ||
        message.includes("请先") ||
        message.includes("无需翻译") ||
        message.includes("No translation is needed") ||
        message.includes("选择其他语言") ||
        message.includes("different target language") ||
        message.includes("language are the same"))
  );
});

const workspaceModel = computed(() => {
  return state.settings?.model_name || state.jobs[0]?.model_name_snapshot || copy("托管模型", "Managed model");
});

const selectedJobTimeline = computed(() => {
  const job = state.selectedJob;
  if (!job?.events?.length) {
    return [];
  }
  const events = [...job.events].sort((left, right) => timestampMs(left.created_at) - timestampMs(right.created_at));
  const jobEndMs = jobEndTimestampMs(job);
  return events.map((event, index) => {
    const startedMs = timestampMs(event.created_at);
    const nextStartedMs = timestampMs(events[index + 1]?.created_at);
    const endedMs = nextStartedMs || jobEndMs || nowMs.value;
    const running = !nextStartedMs && !jobEndMs;
    return {
      ...event,
      durationLabel: formatDuration(Math.max(endedMs - startedMs, 0)),
      durationState: running ? copy("进行中", "Running") : copy("耗时", "Duration"),
    };
  });
});

const selectedJobElapsedLabel = computed(() => {
  if (!state.selectedJob) {
    return "—";
  }
  return formatDuration(jobElapsedMs(state.selectedJob));
});

function timestampMs(value) {
  if (!value) {
    return 0;
  }
  const time = new Date(value).getTime();
  return Number.isFinite(time) ? time : 0;
}

function jobEndTimestampMs(job) {
  if (!terminalJobStatuses.has(job.status)) {
    return 0;
  }
  return timestampMs(job.completed_at) || timestampMs(job.updated_at);
}

function jobElapsedMs(job) {
  const startedMs = timestampMs(job.started_at) || timestampMs(job.created_at);
  const endedMs = jobEndTimestampMs(job) || nowMs.value;
  return Math.max(endedMs - startedMs, 0);
}

function formatDuration(valueMs) {
  const totalSeconds = Math.max(0, Math.floor(Number(valueMs || 0) / 1000));
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  if (hours) {
    return `${hours}h ${minutes}m ${seconds}s`;
  }
  if (minutes) {
    return `${minutes}m ${seconds}s`;
  }
  return `${seconds}s`;
}

function fileKey(file) {
  return `${file.name}:${file.size}:${file.lastModified}`;
}

function isSupportedUploadFile(file) {
  const extensionIndex = file.name.lastIndexOf(".");
  const extension = extensionIndex >= 0 ? file.name.slice(extensionIndex).toLowerCase() : "";
  return supportedUploadExtensions.has(extension);
}

function addFiles(fileList) {
  const existingKeys = new Set(uploadForm.files.map(fileKey));
  const selectedFiles = Array.from(fileList || []);
  const nextFiles = selectedFiles.filter((file) => {
    const key = fileKey(file);
    if (!isSupportedUploadFile(file) || existingKeys.has(key)) {
      return false;
    }
    existingKeys.add(key);
    return true;
  });
  uploadForm.files.push(...nextFiles);
  if (selectedFiles.length && !nextFiles.length) {
    state.messages.upload = copy("没有新的 PDF 或 DOCX 文件可加入。", "No new PDF or DOCX files to add.");
  } else if (nextFiles.length) {
    state.messages.upload = "";
  }
}

function onFileChange(event) {
  addFiles(event.target.files);
  event.target.value = "";
}

function onFileDrop(event) {
  addFiles(event.dataTransfer?.files);
}

function openFilePicker() {
  fileInputRef.value?.click();
}

function removeUploadFile(index) {
  uploadForm.files.splice(index, 1);
}

function normalizeSelectedLanguage(value) {
  return String(value || "").trim().toLowerCase();
}

function hasSameTranslationLanguages(sourceLanguage, targetLanguage) {
  const normalizedSourceLanguage = normalizeSelectedLanguage(sourceLanguage);
  if (!normalizedSourceLanguage || normalizedSourceLanguage === "auto") {
    return false;
  }
  return normalizedSourceLanguage === normalizeSelectedLanguage(targetLanguage);
}

async function submitUpload() {
  if (!uploadForm.files.length) {
    state.messages.upload = copy("请先选择 PDF 或 DOCX 文件。", "Choose a PDF or DOCX file first.");
    return;
  }

  if (hasSameTranslationLanguages(uploadForm.sourceLanguage, uploadForm.targetLanguage)) {
    state.messages.upload = copy(
      "源语言与目标语言相同，无需翻译；请选择其他目标语言。",
      "Source and target language are the same. No translation is needed, or choose a different target language."
    );
    return;
  }

  try {
    await uploadJobs(uploadForm.files, uploadForm.sourceLanguage, uploadForm.targetLanguage);
    uploadForm.files = [];
  } catch (error) {
    state.messages.upload = error.message;
  }
}

function openPreview(jobId) {
  router.push(`/preview/${jobId}`);
}

function canPreview(job) {
  return job.status === "completed" && job.output_file && !isJobExpired(job);
}

function canDownload(job) {
  return job.status === "completed" && job.output_file && !isJobExpired(job);
}

function canRetry(job) {
  return job.status === "failed" || job.status === "cancelled";
}

function canCancel(job) {
  return activeJobStatuses.has(job.status);
}

function canDownloadDebugArtifacts(job) {
  return job.status === "completed" && job.output_file && !isJobExpired(job);
}

onMounted(() => {
  clockHandle = window.setInterval(() => {
    nowMs.value = Date.now();
  }, 1000);
});

onBeforeUnmount(() => {
  if (clockHandle) {
    window.clearInterval(clockHandle);
    clockHandle = null;
  }
});
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
        <label class="upload-dropzone" for="upload-file-input" @dragover.prevent @drop.prevent="onFileDrop">
          <input
            id="upload-file-input"
            ref="fileInputRef"
            type="file"
            multiple
            accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            @change="onFileChange"
          />
          <div class="upload-copy">
            <strong>{{ copy("拖拽或选择 PDF / DOCX", "Drop or choose PDF / DOCX files") }}</strong>
            <p class="subtle">
              {{
                uploadForm.files.length
                  ? copy(`已加入 ${uploadForm.files.length} 个待翻译文件。`, `${uploadForm.files.length} files ready to translate.`)
                  : copy("支持直接排队翻译并进入在线校对。", "Queue translation and review online.")
              }}
            </p>
          </div>
          <button class="ghost-button upload-picker-button" type="button" @click.prevent="openFilePicker()">
            {{ copy("选择文件", "Choose file") }}
          </button>
        </label>

        <div v-if="uploadForm.files.length" class="upload-file-list">
          <article v-for="(file, index) in uploadForm.files" :key="`${fileKey(file)}:${index}`" class="upload-file-card">
            <button
              class="icon-button icon-button--bare icon-button--tiny upload-file-remove"
              type="button"
              :aria-label="copy('移除文件', 'Remove file')"
              :title="copy('移除文件', 'Remove file')"
              :disabled="state.pending.upload"
              @click="removeUploadFile(index)"
            >
              <svg viewBox="0 0 20 20" fill="none" aria-hidden="true">
                <path d="m5.5 5.5 9 9" />
                <path d="m14.5 5.5-9 9" />
              </svg>
            </button>
            <div class="upload-file-copy">
              <strong :title="file.name">{{ file.name }}</strong>
              <span>{{ fileKindLabel(file.name) }} · {{ formatBytes(file.size) }}</span>
            </div>
          </article>
        </div>

        <div class="compact-grid two-up">
          <label class="field">
            <span>{{ copy("源语言", "Source language") }}</span>
            <AppSelect
              v-model="uploadForm.sourceLanguage"
              :options="localizedSourceLanguageOptions"
              :aria-label="copy('源语言', 'Source language')"
            />
          </label>
          <label class="field">
            <span>{{ copy("目标语言", "Target language") }}</span>
            <AppSelect
              v-model="uploadForm.targetLanguage"
              :options="localizedTargetLanguageOptions"
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
        <p v-if="state.messages.upload" class="message" :class="{ error: uploadMessageIsError }">
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
                {{ languageName(job.source_language, copy) }} → {{ languageName(job.target_language, copy) }}
              </p>
            </div>

            <div class="job-card-side">
              <span class="status-pill" :data-status="jobStatusKey(job)">{{ formatJobStatus(jobStatusKey(job), copy) }}</span>

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
                  v-if="canDownload(job)"
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
                <button
                  v-if="canCancel(job)"
                  class="icon-button icon-button--bare icon-button--tiny danger-text"
                  type="button"
                  :aria-label="copy('取消', 'Cancel')"
                  :title="copy('取消', 'Cancel')"
                  @click.stop="cancelJob(job.id)"
                >
                  <svg viewBox="0 0 20 20" fill="none" aria-hidden="true">
                    <circle cx="10" cy="10" r="6.75" />
                    <path d="m7.25 7.25 5.5 5.5" />
                    <path d="m12.75 7.25-5.5 5.5" />
                  </svg>
                </button>
                <button
                  v-if="canRetry(job)"
                  class="icon-button icon-button--bare icon-button--tiny"
                  type="button"
                  :aria-label="copy('重试', 'Retry')"
                  :title="copy('重试', 'Retry')"
                  @click.stop="retryJob(job.id)"
                >
                  <svg viewBox="0 0 20 20" fill="none" aria-hidden="true">
                    <path d="M15.2 10a5.2 5.2 0 1 1-1.05-4.55" />
                    <path d="M14.15 5.45 15.95 7.25H14.2" />
                  </svg>
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
              <strong>{{ formatJobStatus(jobStatusKey(state.selectedJob), copy) }}</strong>
              <small>{{ copy("总耗时", "Total") }} {{ selectedJobElapsedLabel }}</small>
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

          <div v-if="canDownloadDebugArtifacts(state.selectedJob)" class="button-row">
            <button class="ghost-button" type="button" @click="downloadJobDebugArtifact(state.selectedJob.id, 'structure-before')">
              {{ copy("下载切分前 JSON", "Download pre-split JSON") }}
            </button>
            <button class="ghost-button" type="button" @click="downloadJobDebugArtifact(state.selectedJob.id, 'structure-after')">
              {{ copy("下载切分后 JSON", "Download post-split JSON") }}
            </button>
          </div>

          <div class="timeline">
            <article v-for="event in selectedJobTimeline" :key="event.id" class="timeline-item">
              <div class="timeline-item-head">
                <strong>{{ event.message }}</strong>
                <div class="timeline-item-meta">
                  <span class="subtle">{{ formatDate(event.created_at) }}</span>
                  <span class="duration-pill">{{ event.durationState }} {{ event.durationLabel }}</span>
                </div>
              </div>
              <p class="subtle">{{ event.level }}</p>
            </article>
          </div>
        </div>
      </template>
    </section>
  </main>
</template>
