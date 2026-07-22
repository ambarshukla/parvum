import type { DqMetricRow, QueueItem, QueueStatus } from "./types";

// Same-origin by default (empty base), split-deployment override via
// VITE_API_BASE — same story as web/api.ts. Unlike the public dashboard,
// every call here carries credentials (the session cookie) and a custom
// header InternalAuthFilter requires on the server (a cheap CSRF guard: a
// cross-site form post can't set a custom header, only same-origin fetch
// calls like these can).
const API_BASE = (import.meta.env.VITE_API_BASE ?? "").replace(/\/$/, "");

const CSRF_HEADER = "X-Parvum-Internal";

export class ApiError extends Error {
    constructor(
        public status: number,
        message: string,
    ) {
        super(message);
    }
}

async function request(path: string, init: RequestInit = {}): Promise<Response> {
    const response = await fetch(`${API_BASE}${path}`, {
        ...init,
        credentials: "include",
        headers: { ...init.headers, [CSRF_HEADER]: "1" },
    });
    if (!response.ok) {
        throw new ApiError(response.status, `${path} → ${response.status} ${response.statusText}`);
    }
    return response;
}

/** True if the browser already carries a valid session cookie. */
export async function checkSession(): Promise<boolean> {
    try {
        await request("/internal/auth/session");
        return true;
    } catch (e) {
        if (e instanceof ApiError && e.status === 401) return false;
        throw e;
    }
}

/** Throws ApiError(401) on a wrong password. */
export async function login(password: string): Promise<void> {
    await request("/internal/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password }),
    });
}

export async function logout(): Promise<void> {
    await request("/internal/auth/logout", { method: "POST" });
}

// dq_metrics rows are identical regardless of tenant (see
// V4__dq_metrics.sql / D-044) — any configured tenant id works. There is no
// tenant selector in this app; Ops is a pipeline-wide view, not per-firm.
const OPS_TENANT = "aldergate";

export async function fetchDqMetrics(): Promise<DqMetricRow[]> {
    const response = await request(`/internal/tenants/${OPS_TENANT}/dq-metrics`);
    return (await response.json()) as DqMetricRow[];
}

export async function fetchQueue(status?: QueueStatus): Promise<QueueItem[]> {
    const query = status ? `?status=${status}` : "";
    const response = await request(`/internal/alts/queue${query}`);
    return (await response.json()) as QueueItem[];
}

export async function approveQueueItem(id: number): Promise<QueueItem> {
    const response = await request(`/internal/alts/queue/${id}/approve`, { method: "POST" });
    return (await response.json()) as QueueItem;
}

/** correctedFields values keep whatever type the reviewer's edit produced
 *  (string/number/boolean/null) -- the server stores them verbatim, same as
 *  an extraction's own fields. */
export async function correctQueueItem(
    id: number,
    correctedFields: Record<string, unknown>,
): Promise<QueueItem> {
    const response = await request(`/internal/alts/queue/${id}/correct`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(correctedFields),
    });
    return (await response.json()) as QueueItem;
}
