import type {
    AllocationRow,
    AltsHoldingRow,
    HoldingRow,
    IncomeRow,
    OwnershipRow,
    PerformanceRow,
    PerformanceSummaryRow,
    TenantData,
    WealthRow,
} from "./types";

// Same-origin by default (empty base): in production the app is served behind
// the same host as the API, and in dev Vite proxies /tenants to the local
// Quarkus app (see vite.config.ts) — so no CORS either way. VITE_API_BASE
// overrides it for a split deployment (a separately hosted API).
const API_BASE = (import.meta.env.VITE_API_BASE ?? "").replace(/\/$/, "");

async function getJson<T>(path: string): Promise<T> {
    const response = await fetch(`${API_BASE}${path}`);
    if (!response.ok) {
        throw new Error(`${path} → ${response.status} ${response.statusText}`);
    }
    return (await response.json()) as T;
}

/** Fetch every projection for one tenant in parallel. */
export async function fetchTenant(tenantId: string): Promise<TenantData> {
    const base = `/tenants/${tenantId}`;
    const [
        wealth,
        allocation,
        income,
        holdings,
        ownership,
        performance,
        performanceSummary,
        altsHoldings,
    ] = await Promise.all([
        getJson<WealthRow[]>(`${base}/wealth`),
        getJson<AllocationRow[]>(`${base}/allocation`),
        getJson<IncomeRow[]>(`${base}/income`),
        getJson<HoldingRow[]>(`${base}/holdings`),
        getJson<OwnershipRow[]>(`${base}/ownership`),
        getJson<PerformanceRow[]>(`${base}/performance`),
        getJson<PerformanceSummaryRow[]>(`${base}/performance-summary`),
        getJson<AltsHoldingRow[]>(`${base}/alts-holdings`),
    ]);
    return {
        wealth,
        allocation,
        income,
        holdings,
        ownership,
        performance,
        performanceSummary,
        altsHoldings,
    };
}
