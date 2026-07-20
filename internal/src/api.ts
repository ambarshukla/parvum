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
