<script setup>
import { computed, nextTick, onUnmounted, reactive, ref, watch } from "vue";
import { useRouter } from "vue-router";
import {
  clearPreviewState,
  copy,
  downloadJob,
  loadPreview,
  previewDirty,
  savePreview,
  setPreviewMode,
  state,
} from "../store";
import { fileKindLabel, languageName } from "../utils";

const props = defineProps({
  jobId: {
    type: String,
    required: true,
  },
});

const router = useRouter();
const sourceScroller = ref(null);
const translatedScroller = ref(null);
const currentPdfPage = ref(1);
const pdfStageAspect = reactive({
  source: 0.772,
  translated: 0.772,
});
const pdfZoom = reactive({
  source: 1,
  translated: 1,
});
const pdfDocs = {
  source: null,
  translated: null,
};
const loadedPdfUrls = {
  source: null,
  translated: null,
};

let pdfjsPromise = null;
let resizeTimer = null;
let renderQueue = Promise.resolve();
let syncingScroll = false;
let resetPdfOnNextDocumentsChange = false;

const isPdf = computed(() => state.previewData?.document_kind === "pdf");
const isEditing = computed(() => state.previewMode === "edit");
const title = computed(() => state.previewData?.output_name || state.previewJob?.output_file?.original_name || "");
const subtitle = computed(() => {
  if (!state.previewJob) {
    return "";
  }
  return `${fileKindLabel(state.previewJob.input_file.original_name)} · ${languageName(state.previewJob.source_language)} → ${languageName(state.previewJob.target_language)}`;
});

const pdfPages = computed(() => {
  if (!state.previewDraft?.pages || !isPdf.value) {
    return [];
  }
  return [...state.previewDraft.pages].sort((left, right) => (left.page_num || 0) - (right.page_num || 0));
});

const pageCount = computed(() => pdfPages.value.length || 1);
const currentDraftPage = computed(() => pdfPages.value.find((page) => page.page_num === currentPdfPage.value) || pdfPages.value[0] || null);

function editablePdfItems(page) {
  if (!page) {
    return [];
  }

  return page.blocks.flatMap((block) => {
    if ((block.type || "text") === "table") {
      return block.cells.map((cell) => ({
        id: cell.cell_id,
        label: `${copy("单元格", "Cell")} R${cell.row_index} C${cell.col_index}`,
        source: cell.src_text,
        model: cell,
      }));
    }

    return [
      {
        id: block.block_id,
        label: `${copy("文本块", "Text block")} ${block.block_id.slice(0, 8)}`,
        source: block.src_text,
        model: block,
      },
    ];
  });
}

async function ensurePdfJs() {
  if (!pdfjsPromise) {
    const moduleUrl = new URL("/vendor/pdf.mjs", window.location.origin).href;
    pdfjsPromise = import(/* @vite-ignore */ moduleUrl)
      .then((module) => {
        const pdfjs = module.getDocument ? module : module.default;
        if (!pdfjs?.getDocument) {
          throw new Error("PDF renderer module is unavailable.");
        }
        if (pdfjs.GlobalWorkerOptions) {
          pdfjs.GlobalWorkerOptions.workerSrc = new URL("/vendor/pdf.worker.mjs", window.location.origin).href;
        }
        return pdfjs;
      })
      .catch((error) => {
        pdfjsPromise = null;
        throw new Error(`Failed to load PDF renderer. ${error.message}`);
      });
  }
  return pdfjsPromise;
}

async function loadPdfDocument(url) {
  const pdfjsLib = await ensurePdfJs();
  const httpHeaders = state.token ? { Authorization: `Bearer ${state.token}` } : undefined;
  return pdfjsLib.getDocument({
    url,
    httpHeaders,
    cMapUrl: "/vendor/cmaps/",
    cMapPacked: true,
    standardFontDataUrl: "/vendor/standard_fonts/",
  }).promise;
}

async function resetPdfDocs() {
  for (const key of ["source", "translated"]) {
    await pdfDocs[key]?.destroy?.();
    pdfDocs[key] = null;
    loadedPdfUrls[key] = null;
  }
}

function pdfPageNumbers(doc) {
  if (pdfPages.value.length) {
    return pdfPages.value.map((page) => page.page_num);
  }
  return Array.from({ length: doc.numPages }, (_, index) => index + 1);
}

function findCanvas(scroller, pageNumber) {
  return scroller?.querySelector(`canvas[data-page="${pageNumber}"]`) || null;
}

function pdfStageStyle(kind) {
  return {
    "--pdf-stage-aspect": String(pdfStageAspect[kind] || 0.772),
  };
}

function formatZoom(kind) {
  return `${Math.round((pdfZoom[kind] || 1) * 100)}%`;
}

function adjustZoom(kind, direction) {
  const nextZoom = Math.min(1.8, Math.max(0.7, Math.round((pdfZoom[kind] + direction * 0.1) * 10) / 10));
  if (nextZoom === pdfZoom[kind]) {
    return;
  }

  pdfZoom[kind] = nextZoom;
  void queuePdfRender();
}

function shellAspectRatio(canvas) {
  const value = Number(canvas.parentElement?.style.getPropertyValue("--pdf-page-aspect"));
  return value > 0 ? value : pdfStageAspect.source;
}

function releaseCanvas(kind, canvas) {
  if (!canvas || canvas.dataset.rendered !== "true") {
    return;
  }

  canvas.width = 0;
  canvas.height = 0;
  canvas.style.width = "100%";
  const aspectRatio = shellAspectRatio(canvas) || pdfStageAspect[kind] || 0.772;
  canvas.style.height = `${Math.round((canvas.parentElement?.clientWidth || 1) / aspectRatio)}px`;
  canvas.dataset.rendered = "false";
  canvas.dataset.renderedWidth = "";
}

function pageNumbersAroundViewport(scroller, multiplier = 1.1) {
  const elements = pageElements(scroller);
  if (!elements.length || !scroller) {
    return [];
  }

  const buffer = scroller.clientHeight * multiplier;
  const viewportTop = scroller.scrollTop - buffer;
  const viewportBottom = scroller.scrollTop + scroller.clientHeight + buffer;

  return elements
    .filter((element) => element.offsetTop + element.offsetHeight >= viewportTop && element.offsetTop <= viewportBottom)
    .map((element) => Number(element.dataset.page || "1"));
}

async function primePdfAspect(kind, doc) {
  if (!doc) {
    return;
  }

  const firstPage = await doc.getPage(1);
  const viewport = firstPage.getViewport({ scale: 1 });
  if (viewport.width > 0 && viewport.height > 0) {
    pdfStageAspect[kind] = viewport.width / viewport.height;
  }
}

async function renderPageIntoCanvas(kind, doc, pageNumber, canvas) {
  if (!doc || !canvas) {
    return;
  }

  const page = await doc.getPage(pageNumber);
  const baseViewport = page.getViewport({ scale: 1 });
  const width = Math.max((canvas.parentElement?.clientWidth || 0) * (pdfZoom[kind] || 1), 260);
  const widthKey = String(Math.round(width));
  if (canvas.dataset.rendered === "true" && canvas.dataset.renderedWidth === widthKey) {
    return;
  }

  const scale = width / baseViewport.width;
  const viewport = page.getViewport({ scale });
  const ratio = window.devicePixelRatio || 1;
  const context = canvas.getContext("2d");
  canvas.parentElement?.style.setProperty("--pdf-page-aspect", String(viewport.width / viewport.height));

  canvas.width = Math.floor(viewport.width * ratio);
  canvas.height = Math.floor(viewport.height * ratio);
  canvas.style.width = `${viewport.width}px`;
  canvas.style.height = `${viewport.height}px`;

  context.setTransform(1, 0, 0, 1, 0, 0);
  context.clearRect(0, 0, canvas.width, canvas.height);

  await page.render({
    canvasContext: context,
    viewport,
    transform: ratio === 1 ? null : [ratio, 0, 0, ratio, 0, 0],
  }).promise;

  canvas.dataset.rendered = "true";
  canvas.dataset.renderedWidth = widthKey;
}

function trimRenderedPages(kind, scroller, keepPages) {
  for (const canvas of scroller?.querySelectorAll("canvas[data-page]") || []) {
    const pageNumber = Number(canvas.dataset.page || "0");
    if (!keepPages.has(pageNumber)) {
      releaseCanvas(kind, canvas);
    }
  }
}

async function renderPdfColumn(kind, doc, scroller) {
  if (!doc || !scroller) {
    return;
  }

  const pagesToRender = pageNumbersAroundViewport(scroller, 1.1);
  const keepPages = new Set(pageNumbersAroundViewport(scroller, 2.2));

  for (const pageNumber of pagesToRender) {
    const canvas = findCanvas(scroller, pageNumber);
    if (!canvas) {
      continue;
    }
    await renderPageIntoCanvas(kind, doc, pageNumber, canvas);
  }

  trimRenderedPages(kind, scroller, keepPages);
}

function pageElements(scroller) {
  return [...(scroller?.querySelectorAll(".pdf-page-shell[data-page]") || [])];
}

function detectCurrentPage(scroller) {
  const elements = pageElements(scroller);
  if (!elements.length) {
    return 1;
  }

  const viewportMiddle = scroller.scrollTop + scroller.clientHeight / 2;
  let closestPage = 1;
  let closestDistance = Number.POSITIVE_INFINITY;

  for (const element of elements) {
    const pageNumber = Number(element.dataset.page || "1");
    const pageMiddle = element.offsetTop + element.clientHeight / 2;
    const distance = Math.abs(pageMiddle - viewportMiddle);
    if (distance < closestDistance) {
      closestDistance = distance;
      closestPage = pageNumber;
    }
  }

  return closestPage;
}

function syncScroll(source, target) {
  if (!source || !target) {
    return;
  }

  const sourceRange = Math.max(source.scrollHeight - source.clientHeight, 1);
  const targetRange = Math.max(target.scrollHeight - target.clientHeight, 0);
  const ratio = source.scrollTop / sourceRange;
  target.scrollTop = ratio * targetRange;
}

async function renderCurrentPdfPages() {
  if (!isPdf.value || !pdfDocs.source) {
    return;
  }

  await nextTick();
  await renderPdfColumn("source", pdfDocs.source, sourceScroller.value);
  if (!isEditing.value && pdfDocs.translated) {
    await renderPdfColumn("translated", pdfDocs.translated, translatedScroller.value);
  }

  const activeScroller = sourceScroller.value || translatedScroller.value;
  if (activeScroller) {
    currentPdfPage.value = detectCurrentPage(activeScroller);
  }
}

function queuePdfRender() {
  renderQueue = renderQueue.catch(() => {}).then(() => renderCurrentPdfPages());
  return renderQueue;
}

async function loadPdfPreview({ resetView = false } = {}) {
  if (!state.previewDocuments.sourceUrl || !state.previewDocuments.translatedUrl) {
    return;
  }

  if (resetView) {
    await resetPdfDocs();
    pdfZoom.source = 1;
    pdfZoom.translated = 1;
  }

  const sourceUrl = state.previewDocuments.sourceUrl;
  const translatedUrl = state.previewDocuments.translatedUrl;
  const sourceChanged = !pdfDocs.source || loadedPdfUrls.source !== sourceUrl;
  const translatedChanged = !pdfDocs.translated || loadedPdfUrls.translated !== translatedUrl;

  if (sourceChanged) {
    await pdfDocs.source?.destroy?.();
    pdfDocs.source = await loadPdfDocument(sourceUrl);
    loadedPdfUrls.source = sourceUrl;
    await primePdfAspect("source", pdfDocs.source);
  }

  if (translatedChanged) {
    await pdfDocs.translated?.destroy?.();
    pdfDocs.translated = await loadPdfDocument(translatedUrl);
    loadedPdfUrls.translated = translatedUrl;
    await primePdfAspect("translated", pdfDocs.translated);
  }

  const activeDocument = pdfDocs.source || pdfDocs.translated;
  currentPdfPage.value = Math.min(currentPdfPage.value, pdfPages.value.length || activeDocument?.numPages || 1);
  await queuePdfRender();
  scrollToPage(currentPdfPage.value, "auto");
}

async function ensurePreview(jobId) {
  try {
    currentPdfPage.value = 1;
    resetPdfOnNextDocumentsChange = true;
    await loadPreview(jobId);
    if (!isPdf.value) {
      resetPdfOnNextDocumentsChange = false;
    }
  } catch (error) {
    resetPdfOnNextDocumentsChange = false;
    state.messages.preview = error.message;
  }
}

function movePage(step) {
  scrollToPage(currentPdfPage.value + step);
}

function jumpToPage(pageNumber) {
  scrollToPage(pageNumber);
}

function visiblePages() {
  const total = pageCount.value;
  const current = currentPdfPage.value;
  if (total <= 7) {
    return Array.from({ length: total }, (_, index) => index + 1);
  }
  if (current <= 4) {
    return [1, 2, 3, 4, 5, "...", total];
  }
  if (current >= total - 3) {
    return [1, "...", total - 4, total - 3, total - 2, total - 1, total];
  }
  return [1, "...", current - 1, current, current + 1, "...", total];
}

function scrollToPage(pageNumber, behavior = "smooth") {
  const normalizedPage = Math.min(Math.max(pageNumber, 1), pageCount.value);
  currentPdfPage.value = normalizedPage;

  const sourcePage = sourceScroller.value?.querySelector(`.pdf-page-shell[data-page="${normalizedPage}"]`);
  const translatedPage = translatedScroller.value?.querySelector(`.pdf-page-shell[data-page="${normalizedPage}"]`);

  if (sourcePage && sourceScroller.value) {
    sourceScroller.value.scrollTo({
      top: sourcePage.offsetTop - 14,
      behavior,
    });
  }

  if (translatedPage && translatedScroller.value && !isEditing.value) {
    translatedScroller.value.scrollTo({
      top: translatedPage.offsetTop - 14,
      behavior,
    });
  }
}

function handlePdfScroll(kind) {
  const activeScroller = kind === "source" ? sourceScroller.value : translatedScroller.value;
  const passiveScroller = kind === "source" ? translatedScroller.value : sourceScroller.value;

  if (!activeScroller) {
    return;
  }

  currentPdfPage.value = detectCurrentPage(activeScroller);
  if (syncingScroll || !passiveScroller || isEditing.value) {
    return;
  }

  syncingScroll = true;
  syncScroll(activeScroller, passiveScroller);
  window.requestAnimationFrame(() => {
    syncingScroll = false;
  });

  schedulePdfRender();
}

function schedulePdfRender() {
  if (!isPdf.value || state.pending.preview) {
    return;
  }
  window.clearTimeout(resizeTimer);
  resizeTimer = window.setTimeout(() => {
    void queuePdfRender();
  }, 90);
}

watch(
  () => props.jobId,
  (jobId) => {
    void ensurePreview(jobId);
  },
  { immediate: true }
);

watch(
  () => currentPdfPage.value,
  () => {
    state.messages.preview = "";
  }
);

watch(
  () => [state.previewDocuments.sourceUrl, state.previewDocuments.translatedUrl],
  async () => {
    if (!isPdf.value || !state.previewDocuments.sourceUrl || !state.previewDocuments.translatedUrl) {
      return;
    }
    const resetView = resetPdfOnNextDocumentsChange;
    resetPdfOnNextDocumentsChange = false;
    await loadPdfPreview({ resetView });
  }
);

watch(
  () => state.previewMode,
  () => {
    if (!isPdf.value || state.pending.preview) {
      return;
    }
    void queuePdfRender();
  }
);

window.addEventListener("resize", schedulePdfRender);

onUnmounted(async () => {
  window.removeEventListener("resize", schedulePdfRender);
  window.clearTimeout(resizeTimer);
  await resetPdfDocs();
  clearPreviewState();
});
</script>

<template>
  <main class="preview-shell">
    <header class="preview-fixed-bar">
      <div class="preview-fixed-bar__left">
        <button class="icon-button icon-button--bare" type="button" @click="router.push('/')">
          <svg viewBox="0 0 20 20" fill="none" aria-hidden="true">
            <path d="m12.5 4.5-5 5 5 5" />
          </svg>
        </button>
        <div class="preview-fixed-bar__copy">
          <h1>{{ title || copy("加载预览中…", "Loading preview...") }}</h1>
          <p>{{ subtitle }}</p>
        </div>
      </div>

      <div class="preview-fixed-bar__actions">
        <button
          v-if="state.previewData"
          class="ghost-button"
          type="button"
          @click="setPreviewMode(isEditing ? 'view' : 'edit')"
        >
          {{ isEditing ? copy("关闭编辑", "Close edit") : copy("编辑", "Edit") }}
        </button>
        <button
          v-if="state.previewData"
          class="primary-button"
          type="button"
          :disabled="!previewDirty || state.pending.previewSave"
          @click="savePreview()"
        >
          {{ state.pending.previewSave ? copy("保存中…", "Saving...") : copy("保存", "Save") }}
        </button>
        <button
          v-if="state.previewJob"
          class="ghost-button"
          type="button"
          @click="downloadJob(state.previewJob.id)"
        >
          {{ copy("下载", "Download") }}
        </button>
      </div>
    </header>

    <section v-if="state.pending.preview" class="preview-loading">
      <div class="empty-state">{{ copy("正在加载文档预览…", "Loading document preview...") }}</div>
    </section>

    <section v-else-if="state.previewData && isPdf" class="preview-body preview-body--pdf">
      <article class="preview-column preview-column--canvas">
        <div class="preview-column__head">
          <strong>{{ copy("原文", "Source") }}</strong>
          <span>{{ state.previewJob?.input_file?.original_name }}</span>
        </div>

        <div class="preview-zoom-control">
          <button
            class="icon-button icon-button--tiny icon-button--bare"
            type="button"
            :disabled="pdfZoom.source <= 0.7"
            :title="copy('缩小', 'Zoom out')"
            @click="adjustZoom('source', -1)"
          >
            −
          </button>
          <span>{{ formatZoom("source") }}</span>
          <button
            class="icon-button icon-button--tiny icon-button--bare"
            type="button"
            :disabled="pdfZoom.source >= 1.8"
            :title="copy('放大', 'Zoom in')"
            @click="adjustZoom('source', 1)"
          >
            +
          </button>
        </div>

        <div
          ref="sourceScroller"
          class="pdf-stage pdf-stage--scroll"
          :style="pdfStageStyle('source')"
          @scroll="handlePdfScroll('source')"
        >
          <div
            v-for="page in pdfPages"
            :key="`source-${page.page_num}`"
            class="pdf-page-shell"
            :data-page="page.page_num"
          >
            <div class="pdf-canvas-shell">
              <canvas class="pdf-canvas" :data-page="page.page_num"></canvas>
            </div>
          </div>
        </div>
        <div class="floating-page-chip">
          <span>{{ currentPdfPage }} / {{ pageCount }}</span>
        </div>
      </article>

      <article v-if="!isEditing" class="preview-column preview-column--canvas">
        <div class="preview-column__head">
          <strong>{{ copy("译文", "Translated") }}</strong>
          <span>{{ title }}</span>
        </div>

        <div class="preview-zoom-control">
          <button
            class="icon-button icon-button--tiny icon-button--bare"
            type="button"
            :disabled="pdfZoom.translated <= 0.7"
            :title="copy('缩小', 'Zoom out')"
            @click="adjustZoom('translated', -1)"
          >
            −
          </button>
          <span>{{ formatZoom("translated") }}</span>
          <button
            class="icon-button icon-button--tiny icon-button--bare"
            type="button"
            :disabled="pdfZoom.translated >= 1.8"
            :title="copy('放大', 'Zoom in')"
            @click="adjustZoom('translated', 1)"
          >
            +
          </button>
        </div>

        <div
          ref="translatedScroller"
          class="pdf-stage pdf-stage--scroll"
          :style="pdfStageStyle('translated')"
          @scroll="handlePdfScroll('translated')"
        >
          <div
            v-for="page in pdfPages"
            :key="`translated-${page.page_num}`"
            class="pdf-page-shell"
            :data-page="page.page_num"
          >
            <div class="pdf-canvas-shell">
              <canvas class="pdf-canvas" :data-page="page.page_num"></canvas>
            </div>
          </div>
        </div>
        <div class="floating-page-chip">
          <span>{{ currentPdfPage }} / {{ pageCount }}</span>
        </div>
      </article>

      <article v-else class="preview-column preview-column--editor">
        <div class="preview-column__head">
          <strong>{{ copy("右侧编辑区", "Editor") }}</strong>
          <span>{{ currentDraftPage ? `${copy("第", "Page")} ${currentDraftPage.page_num} ${copy("页", "")}` : "" }}</span>
        </div>

        <div class="editor-scroll-area">
          <template v-if="currentDraftPage">
            <article v-for="item in editablePdfItems(currentDraftPage)" :key="item.id" class="editor-item editor-item--compact">
              <div class="editor-item-head">
                <strong>{{ item.label }}</strong>
                <span class="subtle">{{ item.id }}</span>
              </div>
              <p class="editor-source">{{ item.source || copy("没有原文可参考。", "No source text available.") }}</p>
              <span class="control-shell control-shell--textarea">
                <textarea v-model="item.model.tgt_text" rows="5"></textarea>
              </span>
            </article>
          </template>
        </div>

        <footer class="editor-fixed-pagination">
          <button class="icon-button icon-button--small" type="button" :disabled="currentPdfPage <= 1" @click="movePage(-1)">‹</button>
          <button
            v-for="page in visiblePages()"
            :key="page"
            class="pagination-pill"
            :class="{ active: page === currentPdfPage, muted: page === '...' }"
            type="button"
            :disabled="page === '...'"
            @click="typeof page === 'number' ? jumpToPage(page) : null"
          >
            {{ page }}
          </button>
          <button class="icon-button icon-button--small" type="button" :disabled="currentPdfPage >= pageCount" @click="movePage(1)">›</button>
        </footer>
      </article>
    </section>

    <section v-else-if="state.previewData" class="preview-body preview-body--docx">
      <article class="preview-column preview-column--docx">
        <div class="docx-preview-stack">
          <article v-for="page in state.previewDraft.pages" :key="page.id" class="docx-preview-card">
            <div class="preview-column__head">
              <strong>{{ page.label || copy("文档段落", "Document section") }}</strong>
              <span>{{ page.id }}</span>
            </div>

            <div class="preview-text-grid">
              <section class="text-panel">
                <h3>{{ copy("原文", "Source") }}</h3>
                <pre>{{ page.source_text || copy("没有原文内容。", "No source text available.") }}</pre>
              </section>
              <section class="text-panel">
                <h3>{{ isEditing ? copy("译文编辑", "Translated editor") : copy("译文", "Translated") }}</h3>
                <span v-if="isEditing" class="control-shell control-shell--textarea">
                  <textarea v-model="page.translated_text" rows="10"></textarea>
                </span>
                <pre v-else>{{ page.translated_text || copy("没有译文内容。", "No translated text available.") }}</pre>
              </section>
            </div>
          </article>
        </div>
      </article>
    </section>

    <section v-else class="preview-loading">
      <div class="empty-state">{{ copy("预览未就绪。", "Preview is not ready.") }}</div>
    </section>

    <p v-if="state.messages.preview" class="preview-message-banner">{{ state.messages.preview }}</p>
  </main>
</template>
