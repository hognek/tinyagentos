/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

import { withCsrf } from "./csrf";

export type LoraStatus = "pending" | "downloading" | "ready" | "failed";

export interface LoraItem {
  id: string;
  source_url: string;
  provider: string;
  civitai_model_id: number | string | null;
  civitai_version_id: number | string | null;
  name: string;
  description: string;
  creator: string;
  base_model: string;
  trigger_words: string[];
  tags: string[];
  nsfw: boolean;
  file_path: string;
  file_name: string;
  sha256: string;
  bytes: number;
  preview_paths: string[];
  meta_json: Record<string, unknown>;
  status: LoraStatus;
  error: string | null;
  created_at: number;
  updated_at: number;
}

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

async function fetchJson<T>(url: string, fallback: T, init?: RequestInit): Promise<T> {
  try {
    const headers = new Headers(init?.headers);
    headers.set("Accept", "application/json");
    const res = await fetch(url, { ...init, headers });
    if (!res.ok) return fallback;
    const ct = res.headers.get("content-type") ?? "";
    if (!ct.includes("application/json")) return fallback;
    return await res.json();
  } catch {
    return fallback;
  }
}

/* ------------------------------------------------------------------ */
/*  Items                                                              */
/* ------------------------------------------------------------------ */

export async function listLoras(status?: LoraStatus): Promise<LoraItem[]> {
  const qs = status ? `?status=${encodeURIComponent(status)}` : "";
  const data = await fetchJson<{ loras: LoraItem[] }>(`/api/loras${qs}`, { loras: [] });
  return Array.isArray(data.loras) ? data.loras : [];
}

export async function getLora(id: string): Promise<LoraItem | null> {
  try {
    const res = await fetch(`/api/loras/${encodeURIComponent(id)}`, {
      headers: { Accept: "application/json" },
    });
    if (!res.ok) return null;
    const ct = res.headers.get("content-type") ?? "";
    if (!ct.includes("application/json")) return null;
    return await res.json();
  } catch {
    return null;
  }
}

export async function deleteLora(id: string): Promise<boolean> {
  try {
    const res = await fetch(`/api/loras/${encodeURIComponent(id)}`, withCsrf({
      method: "DELETE",
      headers: { Accept: "application/json" },
    }));
    return res.ok;
  } catch {
    return false;
  }
}

/* ------------------------------------------------------------------ */
/*  Ingest / retry                                                     */
/* ------------------------------------------------------------------ */

// The backend endpoint declares `url: str = Form(...)`, so this MUST post
// form-encoded, not JSON -- passing a URLSearchParams body lets fetch set
// the `application/x-www-form-urlencoded` content type itself.
export async function ingestLora(url: string): Promise<LoraItem | null> {
  try {
    const res = await fetch("/api/loras/ingest", withCsrf({
      method: "POST",
      headers: { Accept: "application/json" },
      body: new URLSearchParams({ url }),
    }));
    if (!res.ok) return null;
    const ct = res.headers.get("content-type") ?? "";
    if (!ct.includes("application/json")) return null;
    return await res.json();
  } catch {
    return null;
  }
}

export async function retryLora(id: string): Promise<LoraItem | null> {
  try {
    const res = await fetch(`/api/loras/${encodeURIComponent(id)}/retry`, withCsrf({
      method: "POST",
      headers: { Accept: "application/json" },
    }));
    if (!res.ok) return null;
    const ct = res.headers.get("content-type") ?? "";
    if (!ct.includes("application/json")) return null;
    return await res.json();
  } catch {
    return null;
  }
}

/* ------------------------------------------------------------------ */
/*  Previews                                                            */
/* ------------------------------------------------------------------ */

export function loraPreviewUrl(id: string, index: number): string {
  return `/api/loras/${encodeURIComponent(id)}/preview/${index}`;
}
