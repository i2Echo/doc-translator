<script setup>
import { computed, nextTick, onUnmounted, reactive, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { renderAsync as renderDocx } from "docx-preview";
import {
  clearPreviewState,
  copy,
  downloadJob,
  loadPreview,
  previewDirty,
  savePreview,
  setMessage,
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
const editorScroller = ref(null);
const layoutSandbox = ref(null);
const docxSourceHost = ref(null);
const docxTranslatedHost = ref(null);
const xlsxSourceScroller = ref(null);
const xlsxTranslatedScroller = ref(null);
const activeXlsxSheetId = ref("");
const activePdfItemId = ref("");
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
const PDF_LANGUAGE_LAYOUT = {
  zh: {
    minFontSize: 8,
    stepDown: 0.5,
    lineHeightMultiplier: 1.4,
    fontFamily: '"Noto Sans SC", "Microsoft YaHei", "PingFang SC", sans-serif',
  },
  en: {
    minFontSize: 6.5,
    stepDown: 0.5,
    lineHeightMultiplier: 1.5,
    fontFamily: 'Arial, "Liberation Sans", "Noto Sans", sans-serif',
  },
  ja: {
    minFontSize: 7.5,
    stepDown: 0.5,
    lineHeightMultiplier: 1.3,
    fontFamily: '"Noto Sans JP", "Yu Gothic", "Meiryo", sans-serif',
  },
  ko: {
    minFontSize: 8,
    stepDown: 0.5,
    lineHeightMultiplier: 1.4,
    fontFamily: '"Noto Sans KR", "Malgun Gothic", sans-serif',
  },
  ms: {
    minFontSize: 6,
    stepDown: 0.8,
    lineHeightMultiplier: 1.5,
    fontFamily: 'Arial, "Liberation Sans", "Noto Sans", sans-serif',
  },
  th: {
    minFontSize: 7.5,
    stepDown: 0.5,
    lineHeightMultiplier: 1.2,
    fontFamily: '"Noto Sans Thai", "Leelawadee UI", sans-serif',
  },
  vi: {
    minFontSize: 7,
    stepDown: 0.5,
    lineHeightMultiplier: 1.25,
    fontFamily: 'Arial, "Liberation Sans", "Noto Sans", sans-serif',
  },
};
const PDF_LANGUAGE_ALIASES = {
  "zh": "zh",
  "zh-cn": "zh",
  chinese: "zh",
  "simplified chinese": "zh",
  en: "en",
  english: "en",
  ja: "ja",
  japanese: "ja",
  ko: "ko",
  korean: "ko",
  ms: "ms",
  malay: "ms",
  th: "th",
  thai: "th",
  vi: "vi",
  vietnamese: "vi",
};
const PDF_SERIF_FONT_HINTS = ["serif", "times", "roman", "song", "ming", "mincho", "cambria", "georgia", "simsun"];
const PDF_MONO_FONT_HINTS = ["mono", "courier", "consola", "fixed"];

let pdfjsPromise = null;
let resizeTimer = null;
let renderQueue = Promise.resolve();
let syncingScroll = false;
let resetPdfOnNextDocumentsChange = false;
let layoutMeasureTimer = null;
let docxRenderVersion = 0;

const isPdf = computed(() => state.previewData?.document_kind === "pdf");
const isDocx = computed(() => state.previewData?.document_kind === "docx");
const isPptx = computed(() => state.previewData?.document_kind === "pptx");
const isXlsx = computed(() => state.previewData?.document_kind === "xlsx");
const isVisualPreview = computed(() => isPdf.value || isPptx.value);
const isEditing = computed(() => state.previewMode === "edit");
const title = computed(() => state.previewData?.output_name || state.previewJob?.output_file?.original_name || "");
const referencePdfKind = computed(() => (isEditing.value ? "translated" : "source"));
const referencePdfLabel = computed(() => (isEditing.value ? copy("译文", "Translated") : copy("原文", "Source")));
const referencePdfName = computed(() =>
  isEditing.value ? title.value : (state.previewJob?.input_file?.original_name || "")
);
const subtitle = computed(() => {
  if (!state.previewJob) {
    return "";
  }
  return `${fileKindLabel(state.previewJob.input_file.original_name)} · ${languageName(state.previewJob.source_language, copy)} → ${languageName(state.previewJob.target_language, copy)}`;
});

const xlsxSheets = computed(() => (isXlsx.value ? state.previewDraft?.sheets || [] : []));
const activeXlsxSheet = computed(
  () => xlsxSheets.value.find((sheet) => sheet.id === activeXlsxSheetId.value) || xlsxSheets.value[0] || null
);
const xlsxEditableCellCount = computed(() => activeXlsxSheet.value?.cells.filter((cell) => cell.editable).length || 0);
const activeXlsxCells = computed(() => activeXlsxSheet.value?.cells.filter((cell) => !cell.merged_parent) || []);
const activeXlsxSheetNumber = computed(() => {
  const index = xlsxSheets.value.findIndex((sheet) => sheet.id === activeXlsxSheet.value?.id);
  return index >= 0 ? index + 1 : 1;
});
const xlsxSheetCount = computed(() => xlsxSheets.value.length || 1);
const hasHiddenXlsxSheets = computed(() => xlsxSheets.value.some((sheet) => sheet.state !== "visible"));
const showXlsxSheetTabs = computed(() => xlsxSheets.value.length > 1 || hasHiddenXlsxSheets.value);
const pptxSlides = computed(() =>
  isPptx.value
    ? (() => {
        const pages = state.previewData?.pages || [];
        const slides = pages.filter((page) => !String(page.label || "").toLowerCase().startsWith("notes"));
        return slides.length ? slides : pages;
      })()
    : []
);

const pdfPages = computed(() => {
  if (!state.previewDraft?.pages || !isPdf.value) {
    return [];
  }
  return [...state.previewDraft.pages].sort((left, right) => (left.page_num || 0) - (right.page_num || 0));
});
const visualPageCount = computed(() => {
  if (isPptx.value) {
    return pptxSlides.value.length || 1;
  }
  return pdfPages.value.length || 1;
});

const repeatedPdfEdgeTexts = computed(() => collectRepeatedPdfEdgeTexts(pdfPages.value));
const pageCount = computed(() => visualPageCount.value);
const currentDraftPage = computed(() => pdfPages.value.find((page) => page.page_num === currentPdfPage.value) || pdfPages.value[0] || null);
const currentPdfItems = computed(() => editablePdfItems(currentDraftPage.value));
const activePdfItem = computed(() => currentPdfItems.value.find((item) => item.id === activePdfItemId.value) || currentPdfItems.value[0] || null);
const layoutOverflowCount = computed(() =>
  pdfPages.value.reduce(
    (count, page) =>
      count +
      editablePdfItems(page).filter((item) => item.model.layout_status === "overflow").length,
    0
  )
);

function editablePdfItems(page) {
  if (!page) {
    return [];
  }

  return page.blocks.flatMap((block) => {
    if ((block.type || "text") === "table") {
      return block.cells
        .map((cell) => ({
        id: cell.cell_id,
        label: `${copy("单元格", "Cell")} R${cell.row_index} C${cell.col_index}`,
        source: cell.src_text,
        pageNum: page.page_num,
        model: cell,
        }))
        .filter((item) => !isPdfItemReadOnly(page, item));
    }

    return [
      {
        id: block.block_id,
        label: `${copy("文本块", "Text block")} ${block.block_id.slice(0, 8)}`,
        source: block.src_text,
        pageNum: page.page_num,
        model: block,
      },
    ].filter((item) => !isPdfItemReadOnly(page, item));
  });
}

function pdfBlockStyle(page, item) {
  const rect = item.model.rect || [0, 0, 0, 0];
  const pageWidth = page.page_width || 1;
  const pageHeight = page.page_height || 1;
  return {
    left: `${(rect[0] / pageWidth) * 100}%`,
    top: `${(rect[1] / pageHeight) * 100}%`,
    width: `${Math.max(((rect[2] - rect[0]) / pageWidth) * 100, 0.2)}%`,
    height: `${Math.max(((rect[3] - rect[1]) / pageHeight) * 100, 0.2)}%`,
  };
}

function escapeHtml(text) {
  return String(text || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function itemRectSize(item) {
  const rect = item.model.rect || [0, 0, 0, 0];
  return {
    width: Math.max(rect[2] - rect[0], 1),
    height: Math.max(rect[3] - rect[1], 1),
  };
}

function normalizePdfLanguageCode(language) {
  return PDF_LANGUAGE_ALIASES[String(language || "").trim().toLowerCase()] || "";
}

function pdfLanguageLayout() {
  return PDF_LANGUAGE_LAYOUT[normalizePdfLanguageCode(state.previewData?.target_language)] || {
    minFontSize: 6,
    stepDown: 0.5,
    lineHeightMultiplier: 1.12,
    fontFamily: 'Arial, "Noto Sans", sans-serif',
  };
}

function normalizedPdfFontName(fontName) {
  return String(fontName || "")
    .replace(/^[A-Z]{6}\+/, "")
    .toLowerCase();
}

function pdfFontNameHasHint(fontName, hints) {
  const normalizedName = normalizedPdfFontName(fontName);
  return hints.some((hint) => normalizedName.includes(hint));
}

function pdfItemFontFamily(item) {
  const fontName = item?.model?.font_name || "";
  if (pdfFontNameHasHint(fontName, PDF_MONO_FONT_HINTS)) {
    return '"Courier New", Consolas, monospace';
  }
  if (!normalizePdfLanguageCode(state.previewData?.target_language) && pdfFontNameHasHint(fontName, PDF_SERIF_FONT_HINTS)) {
    return '"Times New Roman", Georgia, serif';
  }
  return pdfLanguageLayout().fontFamily;
}

function pdfItemMeasureStartFontSize(item) {
  const layout = pdfLanguageLayout();
  return Math.max(
    Number(item?.model?.font_size_original || 0),
    Number(item?.model?.font_size_current || 0),
    layout.minFontSize
  );
}

function pdfItemLineHeight(fontSize, { compact = false } = {}) {
  if (compact) {
    return fontSize;
  }
  return Math.max(fontSize * pdfLanguageLayout().lineHeightMultiplier, fontSize + 1);
}

function canonicalImmunityText(text) {
  return String(text ?? "")
    .normalize("NFKC")
    .replace(/[\u200b-\u200d\ufeff]/g, "")
    .replace(/[\u2010-\u2015\u2212]/g, "-")
    .replace(/[\s\n\r]/g, "")
    .replace(/^[,;:|，；：、]+|[,;:|，；：、]+$/g, "");
}

function itemText(item) {
  return String(item?.model?.src_text ?? item?.model?.tgt_text ?? item?.source ?? "");
}

function pdfEdgeBandSize(pageHeight) {
  return Math.max(pageHeight * 0.05, 28);
}

function isNearPdfPageEdge(page, item) {
  const rect = item?.model?.rect;
  const pageHeight = Number(page?.page_height || 0);
  if (!Array.isArray(rect) || rect.length !== 4 || pageHeight <= 0) {
    return false;
  }

  const edgeBand = pdfEdgeBandSize(pageHeight);
  return rect[1] <= edgeBand || rect[3] >= pageHeight - edgeBand;
}

function isLikelyPdfPageMarker(text) {
  const normalized = String(text ?? "")
    .normalize("NFKC")
    .trim()
    .toLowerCase();
  if (!normalized) {
    return false;
  }

  return /^(?:[-–—]?\s*)?(?:page|p\.?|第)?\s*(?:\d{1,4}|[ivxlcdm]{1,8})(?:\s*(?:\/|of)\s*\d{1,4})?(?:\s*[)\].-])?$/.test(normalized);
}

function collectRepeatedPdfEdgeTexts(pages) {
  const counts = new Map();

  for (const page of pages || []) {
    const seenOnPage = new Set();
    for (const item of editablePdfCandidates(page)) {
      if (!isNearPdfPageEdge(page, item)) {
        continue;
      }

      const canonicalText = canonicalImmunityText(itemText(item));
      if (!canonicalText || seenOnPage.has(canonicalText)) {
        continue;
      }

      seenOnPage.add(canonicalText);
      counts.set(canonicalText, (counts.get(canonicalText) || 0) + 1);
    }
  }

  return counts;
}

function editablePdfCandidates(page) {
  if (!page) {
    return [];
  }

  return page.blocks.flatMap((block) => {
    if ((block.type || "text") === "table") {
      return block.cells.map((cell) => ({
        id: cell.cell_id,
        label: `${copy("单元格", "Cell")} R${cell.row_index} C${cell.col_index}`,
        source: cell.src_text,
        pageNum: page.page_num,
        model: cell,
      }));
    }

    return [
      {
        id: block.block_id,
        label: `${copy("文本块", "Text block")} ${block.block_id.slice(0, 8)}`,
        source: block.src_text,
        pageNum: page.page_num,
        model: block,
      },
    ];
  });
}

function isPdfItemReadOnly(page, item) {
  if (!isNearPdfPageEdge(page, item)) {
    return false;
  }

  const canonicalText = canonicalImmunityText(itemText(item));
  if (canonicalText && (repeatedPdfEdgeTexts.value.get(canonicalText) || 0) >= 2) {
    return true;
  }

  return isLikelyPdfPageMarker(itemText(item));
}

function isEligibleForImmunity(item) {
  const sourceText = item.model.src_text ?? item.source ?? "";
  const targetText = item.model.tgt_text ?? "";
  return canonicalImmunityText(sourceText) === canonicalImmunityText(targetText);
}

function isSingleLineText(text) {
  return !String(text ?? "").includes("\n");
}

function measurePdfItem(item) {
  const sandbox = layoutSandbox.value;
  if (!sandbox || !item?.model) {
    return;
  }

  if (isEligibleForImmunity(item)) {
    item.model.layout_status = "ok";
    return;
  }

  const { width, height } = itemRectSize(item);
  const allowedWidth = width + (height < 15 || width < 80 ? 3 : 0);
  const diagramLabel = height < 18 && isSingleLineText(item.model.tgt_text);
  const multilineBlock = !isSingleLineText(item.model.tgt_text);
  const allowedHeight = multilineBlock ? height + Math.max(4, height * 0.1) : height;
  const layout = pdfLanguageLayout();
  const minFontSize = layout.minFontSize;
  let fontSize = Math.max(pdfItemMeasureStartFontSize(item), minFontSize);
  let overflow = false;

  sandbox.style.width = `${allowedWidth}px`;
  sandbox.style.maxWidth = `${allowedWidth}px`;
  sandbox.style.height = `${allowedHeight}px`;
  sandbox.style.fontFamily = pdfItemFontFamily(item);
  sandbox.style.fontWeight = item.model.font_style === "BOLD" ? "700" : "400";
  sandbox.style.letterSpacing = "0";
  sandbox.style.setProperty("padding", "0", "important");
  sandbox.style.setProperty("margin", "0", "important");
  sandbox.style.textAlign = item.model.alignment === "CENTER" ? "center" : "left";
  sandbox.innerHTML = escapeHtml(item.model.tgt_text).replaceAll("\n", "<br>");

  while (fontSize >= minFontSize) {
    sandbox.style.fontSize = `${fontSize}px`;
    if (diagramLabel) {
      sandbox.style.setProperty("line-height", "1", "important");
    } else {
      sandbox.style.setProperty("line-height", `${pdfItemLineHeight(fontSize)}px`);
    }
    overflow = sandbox.scrollWidth > allowedWidth + 0.5 || sandbox.scrollHeight > allowedHeight + 0.5;
    if (!overflow || fontSize === minFontSize) {
      break;
    }
    fontSize = Math.max(minFontSize, Math.round((fontSize - layout.stepDown) * 10) / 10);
  }

  item.model.layout_status = overflow ? "overflow" : "ok";
}

function measureCurrentPageItems() {
  for (const item of currentPdfItems.value) {
    measurePdfItem(item);
  }
}

function scheduleLayoutMeasure(item = null) {
  window.clearTimeout(layoutMeasureTimer);
  layoutMeasureTimer = window.setTimeout(async () => {
    await nextTick();
    if (item) {
      measurePdfItem(item);
      return;
    }
    measureCurrentPageItems();
  }, 40);
}

function scrollEditorItemIntoView(itemId, { behavior = "smooth", block = "nearest" } = {}) {
  const scroller = editorScroller.value;
  if (!scroller) {
    return;
  }

  const row = scroller.querySelector(`[data-editor-id="${CSS.escape(itemId)}"]`);
  if (!row) {
    return;
  }

  const paddingTop = 14;
  const viewportTop = scroller.scrollTop;
  const viewportBottom = viewportTop + scroller.clientHeight;
  const rowTop = row.offsetTop;
  const rowBottom = rowTop + row.offsetHeight;

  let nextTop = viewportTop;
  if (block === "start") {
    nextTop = Math.max(rowTop - paddingTop, 0);
  } else if (rowTop < viewportTop + paddingTop) {
    nextTop = Math.max(rowTop - paddingTop, 0);
  } else if (rowBottom > viewportBottom - paddingTop) {
    nextTop = Math.max(rowBottom - scroller.clientHeight + paddingTop, 0);
  } else {
    return;
  }

  scroller.scrollTo({
    top: nextTop,
    behavior,
  });
}

function selectPdfItem(item, { behavior = "smooth", editorBlock = "nearest" } = {}) {
  if (!item) {
    return;
  }
  activePdfItemId.value = item.id;
  if (item.pageNum && item.pageNum !== currentPdfPage.value) {
    scrollToPage(item.pageNum, behavior);
  }
  nextTick(() => {
    scrollEditorItemIntoView(item.id, {
      block: editorBlock,
      behavior,
    });
  });
}

function handlePdfTextInput(item) {
  activePdfItemId.value = item.id;
  scheduleLayoutMeasure(item);
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
  if (nextZoom === pdfZoom.source && nextZoom === pdfZoom.translated) {
    return;
  }

  pdfZoom.source = nextZoom;
  pdfZoom.translated = nextZoom;
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
  canvas.dataset.renderedDocKey = "";
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
  const docKey = loadedPdfUrls[kind] || kind;
  if (
    canvas.dataset.rendered === "true" &&
    canvas.dataset.renderedWidth === widthKey &&
    canvas.dataset.renderedDocKey === docKey
  ) {
    return;
  }

  const scale = width / baseViewport.width;
  const viewport = page.getViewport({ scale });
  const ratio = window.devicePixelRatio || 1;
  const context = canvas.getContext("2d");
  canvas.parentElement?.style.setProperty("--pdf-page-aspect", String(viewport.width / viewport.height));

  canvas.dataset.rendered = "false";
  canvas.dataset.renderedWidth = "";
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
  canvas.dataset.renderedDocKey = docKey;
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

function xlsxCellTypeLabel(cell) {
  if (cell.value_type === "formula") {
    return copy("公式", "Formula");
  }
  if (cell.value_type === "value") {
    return copy("只读值", "Read-only");
  }
  return copy("文本", "Text");
}

function xlsxSheetStateLabel(sheet) {
  if (sheet.state === "veryHidden") {
    return copy("深度隐藏", "Very hidden");
  }
  if (sheet.state === "hidden") {
    return copy("隐藏", "Hidden");
  }
  return copy("可见", "Visible");
}

function xlsxEditorRows(text) {
  return Math.min(6, Math.max(2, String(text || "").split("\n").length));
}

function xlsxColumnPosition(sheet, columnIndex) {
  return Math.max((sheet?.columns || []).findIndex((column) => column.index === columnIndex), 0) + 2;
}

function xlsxRowPosition(sheet, rowIndex) {
  return Math.max((sheet?.rows || []).findIndex((row) => row.index === rowIndex), 0) + 2;
}

function xlsxGridStyle(sheet) {
  const columns = sheet?.columns?.length ? sheet.columns : [{ width: 72 }];
  const rows = sheet?.rows?.length ? sheet.rows : [{ height: 28 }];
  return {
    gridTemplateColumns: `46px ${columns.map((column) => `${column.width || 72}px`).join(" ")}`,
    gridTemplateRows: `30px ${rows.map((row) => `${row.height || 28}px`).join(" ")}`,
  };
}

function xlsxGridCellStyle(sheet, cell) {
  return {
    gridColumn: `${xlsxColumnPosition(sheet, cell.col_index)} / span ${cell.col_span || 1}`,
    gridRow: `${xlsxRowPosition(sheet, cell.row_index)} / span ${cell.row_span || 1}`,
    ...cell.style,
  };
}

function xlsxColumnHeaderStyle(index) {
  return {
    gridColumn: index + 2,
    gridRow: 1,
  };
}

function xlsxRowHeaderStyle(index) {
  return {
    gridColumn: 1,
    gridRow: index + 2,
  };
}

function xlsxCellText(cell, pane) {
  return pane === "source" ? cell.source_text : cell.translated_text;
}

function selectXlsxSheet(sheetId) {
  activeXlsxSheetId.value = sheetId;
  nextTick(() => {
    for (const scroller of [xlsxSourceScroller.value, xlsxTranslatedScroller.value]) {
      scroller?.scrollTo({ top: 0, left: 0, behavior: "auto" });
    }
  });
}

function handleXlsxScroll(kind) {
  const activeScroller = kind === "source" ? xlsxSourceScroller.value : xlsxTranslatedScroller.value;
  const passiveScroller = kind === "source" ? xlsxTranslatedScroller.value : xlsxSourceScroller.value;

  if (!activeScroller || syncingScroll || !passiveScroller) {
    return;
  }

  syncingScroll = true;
  syncScroll(activeScroller, passiveScroller);
  window.requestAnimationFrame(() => {
    syncingScroll = false;
  });
}

async function renderCurrentPdfPages() {
  const referenceDoc = pdfDocs[referencePdfKind.value];
  if (!isVisualPreview.value || !referenceDoc) {
    return;
  }

  await nextTick();
  await renderPdfColumn(referencePdfKind.value, referenceDoc, sourceScroller.value);
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
  if (!state.previewDocuments.sourceUrl) {
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
  const translatedChanged = translatedUrl && (!pdfDocs.translated || loadedPdfUrls.translated !== translatedUrl);

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
  } else if (!translatedUrl) {
    await pdfDocs.translated?.destroy?.();
    pdfDocs.translated = null;
    loadedPdfUrls.translated = null;
  }

  const activeDocument = pdfDocs.source || pdfDocs.translated;
  currentPdfPage.value = Math.min(currentPdfPage.value, pdfPages.value.length || activeDocument?.numPages || 1);
  await queuePdfRender();
  scrollToPage(currentPdfPage.value, "auto");
}

async function ensurePreview(jobId) {
  try {
    currentPdfPage.value = 1;
    activeXlsxSheetId.value = "";
    resetPdfOnNextDocumentsChange = true;
    await loadPreview(jobId);
    if (!isVisualPreview.value) {
      resetPdfOnNextDocumentsChange = false;
    }
  } catch (error) {
    resetPdfOnNextDocumentsChange = false;
    setMessage("preview", error.message, "error");
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

  schedulePdfRender();
}

function handlePdfScroll(kind) {
  const activeScroller = kind === "source" ? sourceScroller.value : translatedScroller.value;
  const passiveScroller = kind === "source" ? translatedScroller.value : sourceScroller.value;

  if (!activeScroller) {
    return;
  }

  currentPdfPage.value = detectCurrentPage(activeScroller);
  schedulePdfRender();
  if (syncingScroll || !passiveScroller || isEditing.value) {
    return;
  }

  syncingScroll = true;
  syncScroll(activeScroller, passiveScroller);
  window.requestAnimationFrame(() => {
    syncingScroll = false;
  });
}

function handleEditorScroll() {
  const rows = [...(editorScroller.value?.querySelectorAll("[data-editor-id]") || [])];
  if (!rows.length) {
    return;
  }

  const viewportTop = editorScroller.value.scrollTop;
  let closest = rows[0];
  let closestDistance = Number.POSITIVE_INFINITY;
  for (const row of rows) {
    const distance = Math.abs(row.offsetTop - viewportTop);
    if (distance < closestDistance) {
      closest = row;
      closestDistance = distance;
    }
  }
  const item = currentPdfItems.value.find((candidate) => candidate.id === closest.dataset.editorId);
  if (item) {
    activePdfItemId.value = item.id;
  }
}

function schedulePdfRender() {
  if (!isVisualPreview.value || state.pending.preview) {
    return;
  }
  window.clearTimeout(resizeTimer);
  resizeTimer = window.setTimeout(() => {
    void queuePdfRender();
  }, 90);
}

async function fetchDocx(url) {
  const headers = state.token ? { Authorization: `Bearer ${state.token}` } : undefined;
  const response = await fetch(url, { headers });
  if (!response.ok) {
    throw new Error(`Failed to load DOCX (${response.status}).`);
  }
  return response.arrayBuffer();
}

async function renderDocxDocuments() {
  if (!isDocx.value) {
    return;
  }

  const sourceUrl = state.previewDocuments.sourceUrl;
  const translatedUrl = state.previewDocuments.translatedUrl;
  if (!sourceUrl) {
    return;
  }

  const version = ++docxRenderVersion;
  await nextTick();
  const sourceHost = docxSourceHost.value;
  const translatedHost = docxTranslatedHost.value;
  if (!sourceHost) {
    return;
  }

  sourceHost.replaceChildren();
  translatedHost?.replaceChildren();
  try {
    const sourceDocument = await fetchDocx(sourceUrl);
    if (version !== docxRenderVersion) {
      return;
    }
    const options = {
      breakPages: true,
      ignoreFonts: false,
      ignoreHeight: false,
      ignoreWidth: false,
      renderFooters: true,
      renderHeaders: true,
    };
    await renderDocx(sourceDocument, sourceHost, undefined, options);
    if (translatedHost && translatedUrl) {
      const translatedDocument = await fetchDocx(translatedUrl);
      if (version !== docxRenderVersion) {
        return;
      }
      await renderDocx(translatedDocument, translatedHost, undefined, options);
    }
  } catch (error) {
    if (version === docxRenderVersion) {
      setMessage("preview", error.message, "error");
    }
  }
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
    setMessage("preview");
    activePdfItemId.value = "";
    scheduleLayoutMeasure();
  }
);

watch(
  () => [state.previewDocuments.sourceUrl, state.previewDocuments.translatedUrl],
  async () => {
    if (!isVisualPreview.value || !state.previewDocuments.sourceUrl) {
      return;
    }
    const resetView = resetPdfOnNextDocumentsChange;
    resetPdfOnNextDocumentsChange = false;
    await loadPdfPreview({ resetView });
  }
);

watch(
  () => [state.previewDocuments.sourceUrl, state.previewDocuments.translatedUrl, isEditing.value],
  () => {
    if (!isDocx.value) {
      return;
    }
    void renderDocxDocuments();
  }
);

watch(
  () => state.previewMode,
  () => {
    if (!isVisualPreview.value || state.pending.preview) {
      return;
    }
    if (isEditing.value) {
      scheduleLayoutMeasure();
    }
    void queuePdfRender();
  }
);

watch(
  () => state.previewDraft,
  () => {
    activePdfItemId.value = "";
    scheduleLayoutMeasure();
    if (isXlsx.value && !xlsxSheets.value.some((sheet) => sheet.id === activeXlsxSheetId.value)) {
      activeXlsxSheetId.value = xlsxSheets.value[0]?.id || "";
    }
  }
);

window.addEventListener("resize", schedulePdfRender);

onUnmounted(async () => {
  docxRenderVersion += 1;
  window.removeEventListener("resize", schedulePdfRender);
  window.clearTimeout(resizeTimer);
  window.clearTimeout(layoutMeasureTimer);
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
          <h1 :title="title">{{ title || copy("加载预览中…", "Loading preview...") }}</h1>
          <p :title="subtitle">{{ subtitle }}</p>
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
          <strong>{{ referencePdfLabel }}</strong>
          <span :title="referencePdfName">{{ referencePdfName }}</span>
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
              <div v-if="isEditing" class="pdf-block-overlay" aria-hidden="true">
                <button
                  v-for="item in editablePdfItems(page)"
                  :key="`source-overlay-${item.id}`"
                  class="pdf-block-hotspot"
                  :class="{
                    active: activePdfItem?.id === item.id,
                    overflow: item.model.layout_status === 'overflow',
                  }"
                  type="button"
                  :style="pdfBlockStyle(page, item)"
                  @click.stop="selectPdfItem(item, { editorBlock: 'start' })"
                ></button>
              </div>
              <div class="pdf-page-loader" aria-hidden="true">
                <span class="pdf-page-spinner"></span>
                <span>{{ copy("页面加载中", "Loading page") }}</span>
              </div>
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
          <span :title="title">{{ title }}</span>
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
              <div class="pdf-page-loader" aria-hidden="true">
                <span class="pdf-page-spinner"></span>
                <span>{{ copy("页面加载中", "Loading page") }}</span>
              </div>
            </div>
          </div>
        </div>
        <div class="floating-page-chip">
          <span>{{ currentPdfPage }} / {{ pageCount }}</span>
        </div>
      </article>

      <article v-else class="preview-column preview-column--editor">
        <div class="preview-column__head">
          <div class="preview-column-title">
            <strong>{{ copy("右侧编辑区", "Editor") }}</strong>
            <span>
              {{
                currentDraftPage
                  ? `${copy("第", "Page")} ${currentDraftPage.page_num} ${copy("页", "")} · ${currentPdfItems.length} ${copy("块", "blocks")}`
                  : ""
              }}
            </span>
          </div>
          <div class="pdf-editor-status-row">
            <span>{{ previewDirty ? copy("草稿未保存", "Unsaved draft") : copy("无待保存修改", "No pending edits") }}</span>
            <strong :class="{ danger: layoutOverflowCount > 0 }">
              {{
                layoutOverflowCount
                  ? copy(`${layoutOverflowCount} 个块溢出`, `${layoutOverflowCount} blocks overflow`)
                  : copy("版面正常", "Layout OK")
              }}
            </strong>
          </div>
        </div>

        <div ref="editorScroller" class="editor-scroll-area pdf-editor-grid" @scroll="handleEditorScroll">
          <template v-if="currentDraftPage && currentPdfItems.length">
            <article
              v-for="item in currentPdfItems"
              :key="item.id"
              class="editor-item editor-item--compact pdf-editor-row"
              :class="{
                active: activePdfItem?.id === item.id,
                overflow: item.model.layout_status === 'overflow',
              }"
              :data-editor-id="item.id"
              @click="selectPdfItem(item)"
            >
              <div class="editor-item-head">
                <strong>{{ item.label }}</strong>
                <span class="pdf-editor-meta">
                  <span>{{ item.model.font_size_current || item.model.font_size_original }}pt</span>
                  <span v-if="item.model.alignment === 'CENTER'">{{ copy("居中", "Center") }}</span>
                  <span v-if="item.model.font_style === 'BOLD'">{{ copy("加粗", "Bold") }}</span>
                  <span v-if="item.model.rotation">{{ item.model.rotation }}°</span>
                </span>
              </div>
              <p class="editor-source">{{ item.source || copy("没有原文可参考。", "No source text available.") }}</p>
              <span class="control-shell control-shell--textarea">
                <textarea
                  v-model="item.model.tgt_text"
                  rows="5"
                  @input="handlePdfTextInput(item)"
                  @focus="selectPdfItem(item, { behavior: 'auto' })"
                ></textarea>
              </span>
              <p v-if="item.model.layout_status === 'overflow'" class="pdf-layout-alert">
                {{ copy("已降至最小字号，仍超出目标边界。", "Minimum font size reached and the text still exceeds the target bounds.") }}
              </p>
            </article>
          </template>
          <div v-else-if="currentDraftPage" class="empty-state">
            {{ copy("当前页只有页头或页脚内容，默认不开放编辑。", "This page only has header or footer content, which is read-only by default.") }}
          </div>
        </div>

        <div ref="layoutSandbox" class="layout-sandbox" aria-hidden="true"></div>

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

    <section
      v-else-if="state.previewData && isPptx"
      class="preview-body preview-body--pptx"
      :class="{ 'preview-body--pptx-editor': isEditing }"
    >
      <article class="preview-column preview-column--canvas">
        <div class="preview-column__head">
          <strong>{{ referencePdfLabel }}</strong>
          <span :title="referencePdfName">{{ referencePdfName }}</span>
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

        <div ref="sourceScroller" class="pdf-stage pdf-stage--scroll" :style="pdfStageStyle('source')" @scroll="handlePdfScroll('source')">
          <div v-for="(page, index) in pptxSlides" :key="`source-${page.id}`" class="pdf-page-shell" :data-page="index + 1">
            <div class="pdf-canvas-shell">
              <canvas class="pdf-canvas" :data-page="index + 1"></canvas>
              <div class="pdf-page-loader" aria-hidden="true">
                <span class="pdf-page-spinner"></span>
                <span>{{ copy("页面加载中", "Loading page") }}</span>
              </div>
            </div>
          </div>
        </div>
        <div class="floating-page-chip">
          <span>{{ currentPdfPage }} / {{ pageCount }}</span>
        </div>
      </article>

      <article v-if="!isEditing" class="preview-column preview-column--canvas">
        <div class="preview-column__head">
          <strong>{{ copy("译文 PPTX", "Translated PPTX") }}</strong>
          <span :title="title">{{ title }}</span>
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
          <div v-for="(page, index) in pptxSlides" :key="`translated-${page.id}`" class="pdf-page-shell" :data-page="index + 1">
            <div class="pdf-canvas-shell">
              <canvas class="pdf-canvas" :data-page="index + 1"></canvas>
              <div class="pdf-page-loader" aria-hidden="true">
                <span class="pdf-page-spinner"></span>
                <span>{{ copy("页面加载中", "Loading page") }}</span>
              </div>
            </div>
          </div>
        </div>
        <div class="floating-page-chip">
          <span>{{ currentPdfPage }} / {{ pageCount }}</span>
        </div>
      </article>

      <article v-else class="preview-column preview-column--docx preview-column--pptx-editor">
        <div class="preview-column__head">
          <div class="preview-column-title">
            <strong>{{ copy("右侧编辑区", "Editor") }}</strong>
            <span>{{ state.previewJob?.input_file?.original_name }}</span>
          </div>
          <span>{{ previewDirty ? copy("草稿未保存", "Unsaved draft") : copy("无待保存修改", "No pending edits") }}</span>
        </div>

        <div class="docx-preview-stack docx-preview-stack--editor">
          <article v-for="page in state.previewDraft.pages" :key="page.id" class="docx-preview-card">
            <div class="editor-item-head">
              <strong>{{ page.label || copy("幻灯片", "Slide") }}</strong>
              <span>{{ page.id }}</span>
            </div>
            <p class="editor-source">{{ page.source_text || copy("没有原文可参考。", "No source text available.") }}</p>
            <span class="control-shell control-shell--textarea">
              <textarea v-model="page.translated_text" rows="10"></textarea>
            </span>
          </article>
        </div>
      </article>
    </section>

    <section v-else-if="state.previewData && isXlsx" class="preview-body preview-body--xlsx">
      <nav v-if="showXlsxSheetTabs" class="xlsx-sheet-tabs" :aria-label="copy('工作表', 'Worksheets')">
        <button
          v-for="sheet in xlsxSheets"
          :key="sheet.id"
          class="xlsx-sheet-tab"
          :class="{ active: activeXlsxSheet?.id === sheet.id }"
          type="button"
          @click="selectXlsxSheet(sheet.id)"
        >
          <span>{{ sheet.name }}</span>
          <small v-if="sheet.state !== 'visible'">{{ xlsxSheetStateLabel(sheet) }}</small>
        </button>
      </nav>

      <article class="preview-column preview-column--xlsx">
        <div class="preview-column__head xlsx-preview-heading">
          <div class="preview-column-title">
            <strong>{{ copy("原文 XLSX", "Source XLSX") }}</strong>
            <span v-if="activeXlsxSheet">{{ activeXlsxSheet.name }}</span>
          </div>
        </div>

        <div v-if="activeXlsxSheet" ref="xlsxSourceScroller" class="xlsx-grid-scroll" @scroll="handleXlsxScroll('source')">
          <div class="xlsx-grid" :style="xlsxGridStyle(activeXlsxSheet)">
            <div class="xlsx-grid-corner"></div>
            <div
              v-for="(column, index) in activeXlsxSheet.columns"
              :key="column.index"
              class="xlsx-grid-header xlsx-grid-header--column"
              :class="{ hidden: column.hidden }"
              :style="xlsxColumnHeaderStyle(index)"
            >
              {{ column.letter }}
            </div>
            <div
              v-for="(row, index) in activeXlsxSheet.rows"
              :key="row.index"
              class="xlsx-grid-header xlsx-grid-header--row"
              :class="{ hidden: row.hidden }"
              :style="xlsxRowHeaderStyle(index)"
            >
              {{ row.index }}
            </div>
            <div
              v-for="cell in activeXlsxCells"
              :key="cell.coordinate"
              class="xlsx-grid-cell"
              :class="{ 'is-editable': cell.editable, muted: !cell.editable }"
              :style="xlsxGridCellStyle(activeXlsxSheet, cell)"
              :title="`${cell.coordinate} · ${xlsxCellTypeLabel(cell)}`"
            >
              <span>{{ xlsxCellText(cell, "source") }}</span>
            </div>
          </div>
        </div>
        <div class="floating-page-chip">
          <span>{{ activeXlsxSheetNumber }} / {{ xlsxSheetCount }}</span>
        </div>
      </article>

      <article class="preview-column preview-column--xlsx" :class="{ 'preview-column--xlsx-editor': isEditing }">
        <div class="preview-column__head xlsx-preview-heading">
          <div class="preview-column-title">
            <strong>{{ isEditing ? copy("右侧编辑区", "Editor") : copy("译文 XLSX", "Translated XLSX") }}</strong>
            <span v-if="activeXlsxSheet">{{ activeXlsxSheet.name }}</span>
          </div>
          <div class="xlsx-preview-status">
            <span v-if="isEditing">{{ previewDirty ? copy("草稿未保存", "Unsaved draft") : copy("无待保存修改", "No pending edits") }}</span>
            <strong>{{ xlsxEditableCellCount }} {{ copy("个可编辑", "editable") }}</strong>
          </div>
        </div>

        <div v-if="activeXlsxSheet" ref="xlsxTranslatedScroller" class="xlsx-grid-scroll" @scroll="handleXlsxScroll('translated')">
          <div class="xlsx-grid" :style="xlsxGridStyle(activeXlsxSheet)">
            <div class="xlsx-grid-corner"></div>
            <div
              v-for="(column, index) in activeXlsxSheet.columns"
              :key="column.index"
              class="xlsx-grid-header xlsx-grid-header--column"
              :class="{ hidden: column.hidden }"
              :style="xlsxColumnHeaderStyle(index)"
            >
              {{ column.letter }}
            </div>
            <div
              v-for="(row, index) in activeXlsxSheet.rows"
              :key="row.index"
              class="xlsx-grid-header xlsx-grid-header--row"
              :class="{ hidden: row.hidden }"
              :style="xlsxRowHeaderStyle(index)"
            >
              {{ row.index }}
            </div>
            <div
              v-for="cell in activeXlsxCells"
              :key="cell.coordinate"
              class="xlsx-grid-cell"
              :class="{ 'is-editable': cell.editable, muted: !cell.editable }"
              :style="xlsxGridCellStyle(activeXlsxSheet, cell)"
              :title="`${cell.coordinate} · ${xlsxCellTypeLabel(cell)}`"
            >
              <textarea
                v-if="isEditing && cell.editable"
                v-model="cell.translated_text"
                class="xlsx-grid-editor"
                :rows="xlsxEditorRows(cell.translated_text)"
              ></textarea>
              <span v-else>{{ xlsxCellText(cell, "translated") }}</span>
            </div>
          </div>
        </div>
        <div class="floating-page-chip">
          <span>{{ activeXlsxSheetNumber }} / {{ xlsxSheetCount }}</span>
        </div>
      </article>
    </section>

    <section
      v-else-if="state.previewData && isDocx"
      class="preview-body preview-body--docx"
      :class="{ 'preview-body--docx-editor': isEditing }"
    >
      <article class="preview-column preview-column--docx">
        <div class="preview-column__head">
          <strong>{{ copy("原文 DOCX", "Source DOCX") }}</strong>
          <span>{{ state.previewJob?.input_file?.original_name }}</span>
        </div>
        <div class="docx-render-scroll">
          <div ref="docxSourceHost" class="docx-render-host"></div>
        </div>
      </article>

      <article v-if="!isEditing" class="preview-column preview-column--docx">
        <div class="preview-column__head">
          <strong>{{ copy("译文 DOCX", "Translated DOCX") }}</strong>
          <span>{{ title }}</span>
        </div>
        <div class="docx-render-scroll">
          <div ref="docxTranslatedHost" class="docx-render-host"></div>
        </div>
      </article>

      <article v-else class="preview-column preview-column--docx preview-column--docx-editor">
        <div class="preview-column__head">
          <div class="preview-column-title">
            <strong>{{ copy("右侧编辑区", "Editor") }}</strong>
            <span>{{ title }}</span>
          </div>
          <span>{{ previewDirty ? copy("草稿未保存", "Unsaved draft") : copy("无待保存修改", "No pending edits") }}</span>
        </div>

        <div class="docx-preview-stack docx-preview-stack--editor">
          <article v-for="page in state.previewDraft.pages" :key="page.id" class="docx-preview-card">
            <div class="editor-item-head">
              <strong>{{ page.label || copy("文档段落", "Document section") }}</strong>
              <span>{{ page.id }}</span>
            </div>
            <span class="control-shell control-shell--textarea">
              <textarea v-model="page.translated_text" rows="10"></textarea>
            </span>
          </article>
        </div>
      </article>
    </section>

    <section v-else class="preview-loading">
      <div class="empty-state">{{ copy("预览未就绪。", "Preview is not ready.") }}</div>
    </section>

    <p v-if="state.messages.preview" class="preview-message-banner" :class="state.messageLevels.preview">
      {{ state.messages.preview }}
    </p>
  </main>
</template>
