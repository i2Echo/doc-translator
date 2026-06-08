const API_BASE = "/api/v1";

export function apiPath(path) {
  return `${API_BASE}${path}`;
}

function buildErrorMessage(response, fallback) {
  return response
    .json()
    .then((data) => data.detail || JSON.stringify(data))
    .catch(() => response.statusText || fallback);
}

export async function apiRequest(path, options = {}, config = {}) {
  const headers = new Headers(options.headers || {});
  if (config.token) {
    headers.set("Authorization", `Bearer ${config.token}`);
  }

  const response = await fetch(apiPath(path), {
    ...options,
    headers,
  });

  if (!response.ok) {
    throw new Error(await buildErrorMessage(response, "Request failed"));
  }

  if (config.raw) {
    return response;
  }

  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    return response.json();
  }
  return response;
}

export function triggerDownload(blob, filename) {
  const downloadUrl = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = downloadUrl;
  link.download = filename;
  link.style.display = "none";
  document.body.append(link);
  link.click();

  window.setTimeout(() => {
    link.remove();
    URL.revokeObjectURL(downloadUrl);
  }, 1000);
}

export function contentDispositionFilename(headerValue, fallback) {
  const match = /filename="?([^"]+)"?/.exec(headerValue || "");
  return match?.[1] || fallback;
}
