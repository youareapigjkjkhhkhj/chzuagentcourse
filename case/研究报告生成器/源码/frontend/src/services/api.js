const API_BASE = import.meta.env.VITE_API_BASE_URL || "";

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {})
    },
    ...options
  });

  if (!response.ok) {
    const message = await response.text();
    throw new Error(message || `Request failed: ${response.status}`);
  }

  return response.json();
}

export function createReport(payload) {
  return request("/api/reports", {
    method: "POST",
    body: JSON.stringify(payload)
  });
}

export function getReport(id) {
  return request(`/api/reports/${id}`);
}

export function listReports() {
  return request("/api/reports");
}

export function downloadUrl(id, kind) {
  return `${API_BASE}/api/reports/${id}/download/${kind}`;
}
