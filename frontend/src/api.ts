async function request<T>(path: string, opts?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const body = await res.json();
      if (body.detail) msg = String(body.detail);
    } catch {
      /* body was not JSON */
    }
    throw new Error(msg);
  }
  return res.json();
}

export const get = <T,>(path: string) => request<T>(path);

export const post = <T,>(path: string, body?: unknown) =>
  request<T>(path, {
    method: "POST",
    body: body === undefined ? undefined : JSON.stringify(body),
  });

export const del = <T,>(path: string) => request<T>(path, { method: "DELETE" });

interface PywebviewWindow {
  pywebview?: { api?: { pick_folder: () => Promise<string | null> } };
}

/** Native Finder dialog via pywebview; in a plain browser we ask for the path. */
export async function pickFolder(): Promise<string | null> {
  const w = window as unknown as PywebviewWindow;
  for (let i = 0; i < 30 && !w.pywebview?.api; i++) {
    await new Promise((r) => setTimeout(r, 100));
  }
  if (w.pywebview?.api?.pick_folder) {
    return await w.pywebview.api.pick_folder();
  }
  return window.prompt("Klasör yolunu girin:");
}
