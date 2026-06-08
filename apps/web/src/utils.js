export const languageOptions = [
  { value: "auto", label: "Auto / 自动检测" },
  { value: "Chinese", label: "Chinese / 中文" },
  { value: "English", label: "English" },
  { value: "Japanese", label: "Japanese / 日本語" },
  { value: "Korean", label: "Korean / 한국어" },
  { value: "German", label: "German / Deutsch" },
  { value: "French", label: "French / Français" },
  { value: "Spanish", label: "Spanish / Español" },
  { value: "Portuguese", label: "Portuguese / Português" },
  { value: "Russian", label: "Russian / Русский" },
];

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

export function formatJobStatus(status, copy) {
  const label = String(status || "").toLowerCase();
  const map = {
    queued: copy("排队中", "Queued"),
    running: copy("进行中", "Running"),
    completed: copy("已完成", "Completed"),
    failed: copy("失败", "Failed"),
    cancelled: copy("已取消", "Cancelled"),
  };
  return map[label] || status;
}

export function formatRole(role, copy) {
  return role === "admin" ? copy("管理员", "Admin") : copy("标准用户", "Standard user");
}

export function languageName(value) {
  return languageOptions.find((option) => option.value === value)?.label || value || "—";
}

export function fileKindLabel(fileName) {
  const normalized = String(fileName || "").toLowerCase();
  if (normalized.endsWith(".pdf")) {
    return "PDF";
  }
  if (normalized.endsWith(".docx")) {
    return "DOCX";
  }
  return "FILE";
}
