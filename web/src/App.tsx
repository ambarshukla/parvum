import { useEffect, useMemo, useState } from "react";
import { fetchTenant } from "./api";
import type { TenantData } from "./types";
import { TENANTS } from "./tenants";
import { money } from "./format";
import { ClientDashboard } from "./ClientDashboard";

type Theme = "light" | "dark";

function initialTheme(): Theme {
    const stored = localStorage.getItem("parvum-theme");
    if (stored === "light" || stored === "dark") return stored;
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function App() {
    const [tenantId, setTenantId] = useState(TENANTS[0]!.id);
    const [theme, setTheme] = useState<Theme>(initialTheme);
    const [data, setData] = useState<TenantData | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [selectedClient, setSelectedClient] = useState<string | null>(null);

    useEffect(() => {
        document.documentElement.setAttribute("data-theme", theme);
        localStorage.setItem("parvum-theme", theme);
    }, [theme]);

    useEffect(() => {
        let live = true;
        setData(null);
        setError(null);
        fetchTenant(tenantId)
            .then((d) => {
                if (!live) return;
                setData(d);
                setSelectedClient(d.wealth[0]?.clientId ?? null);
            })
            .catch((e: unknown) => live && setError(e instanceof Error ? e.message : String(e)));
        return () => {
            live = false;
        };
    }, [tenantId]);

    const tenant = TENANTS.find((t) => t.id === tenantId)!;
    const clients = useMemo(
        () => (data ? [...data.wealth].sort((a, b) => b.totalWealthUsd - a.totalWealthUsd) : []),
        [data],
    );
    const client = clients.find((c) => c.clientId === selectedClient) ?? clients[0] ?? null;

    return (
        <div className="app">
            <header className="topbar">
                <div className="brand">
                    <span className="mark">◆ Parvum</span>
                    <span className="section">Wealth Reporting</span>
                </div>
                <div className="spacer" />
                <select
                    className="tenant-select"
                    value={tenantId}
                    onChange={(e) => setTenantId(e.target.value)}
                    aria-label="Advisory firm"
                >
                    {TENANTS.map((t) => (
                        <option key={t.id} value={t.id}>
                            {t.name}
                        </option>
                    ))}
                </select>
                <button
                    className="theme-toggle"
                    onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
                    aria-label="Toggle colour theme"
                >
                    {theme === "dark" ? "☀ Light" : "☾ Dark"}
                </button>
            </header>

            <div className="body">
                <aside className="sidebar">
                    <div className="firm-line">
                        <div className="firm-name">{tenant.name}</div>
                        <div className="firm-tag">{tenant.tagline}</div>
                    </div>
                    <div className="group-label">Clients</div>
                    {clients.map((c) => (
                        <button
                            key={c.clientId}
                            className={`client-item ${c.clientId === client?.clientId ? "active" : ""}`}
                            onClick={() => setSelectedClient(c.clientId)}
                        >
                            <span className="name">{c.clientName}</span>
                            <span className="sub">{money(c.totalWealthUsd)}</span>
                        </button>
                    ))}
                </aside>

                <main className="main">
                    {error && (
                        <div className="center-state">
                            <strong>Could not reach the serving API.</strong>
                            <code>{error}</code>
                            <span>Is the Quarkus app running and loaded (make export-gold)?</span>
                        </div>
                    )}
                    {!error && !data && <div className="center-state">Loading {tenant.name}…</div>}
                    {!error && data && !client && (
                        <div className="center-state">No clients for this firm yet.</div>
                    )}
                    {!error && data && client && (
                        <ClientDashboard data={data} client={client} dark={theme === "dark"} />
                    )}
                </main>
            </div>
        </div>
    );
}
