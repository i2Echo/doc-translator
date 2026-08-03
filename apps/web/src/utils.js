export const languageOptions = [
  { value: "Chinese", zh: "中文", en: "Chinese" },
  { value: "English", zh: "英语", en: "English" },
  { value: "Japanese", zh: "日语", en: "Japanese" },
  { value: "Korean", zh: "韩语", en: "Korean" },
  { value: "Malay", zh: "马来语", en: "Malay" },
  { value: "Thai", zh: "泰语", en: "Thai" },
  { value: "Vietnamese", zh: "越南语", en: "Vietnamese" },
];

export function sourceLanguageOptions(copy) {
  return [{ value: "auto", label: copy("自动检测", "Auto") }, ...targetLanguageOptions(copy)];
}

export function targetLanguageOptions(copy) {
  return languageOptions.map((option) => ({
    value: option.value,
    label: copy(option.zh, option.en),
  }));
}

export function formatBytes(value) {
  const bytes = Number(value || 0);
  if (!bytes) {
    return "0 B";
  }
  const units = ["B", "KB", "MB", "GB", "TB"];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  const amount = bytes / 1024 ** index;
  return `${amount >= 100 || index === 0 ? amount.toFixed(0) : amount.toFixed(1)} ${units[index]}`;
}

export function formatDate(value) {
  if (!value) {
    return "—";
  }
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

export function isJobExpired(job) {
  return job?.status === "completed" && Boolean(job?.output_file?.deleted_at);
}

export function jobStatusKey(job) {
  if (isJobExpired(job)) {
    return "expired";
  }
  if (job?.cancel_requested && !["completed", "failed", "cancelled"].includes(job.status)) {
    return "cancelling";
  }
  return String(job?.status || "").toLowerCase();
}

export function formatJobStatus(status, copy) {
  const label = String(status || "").toLowerCase();
  const map = {
    uploaded: copy("已上传", "Uploaded"),
    queued: copy("排队中", "Queued"),
    running: copy("进行中", "Running"),
    parsing: copy("解析中", "Parsing"),
    ocr_running: copy("OCR 处理中", "Running OCR"),
    translating: copy("翻译中", "Translating"),
    rebuilding: copy("生成中", "Building"),
    validating: copy("校验中", "Validating"),
    cancelling: copy("取消中", "Cancelling"),
    completed: copy("已完成", "Completed"),
    expired: copy("已过期", "Expired"),
    failed: copy("失败", "Failed"),
    cancelled: copy("已取消", "Cancelled"),
  };
  return map[label] || status;
}

export function formatRole(role, copy) {
  return role === "admin" ? copy("管理员", "Admin") : copy("标准用户", "Standard user");
}

export function languageName(value, copy) {
  return sourceLanguageOptions(copy).find((option) => option.value === value)?.label || value || "—";
}

export function fileKindLabel(fileName) {
  const normalized = String(fileName || "").toLowerCase();
  if (normalized.endsWith(".pdf")) {
    return "PDF";
  }
  if (normalized.endsWith(".docx")) {
    return "DOCX";
  }
  if (normalized.endsWith(".xlsx")) {
    return "XLSX";
  }
  if (normalized.endsWith(".ppt")) {
    return "PPT";
  }
  if (normalized.endsWith(".pptx")) {
    return "PPTX";
  }
  return "FILE";
}
