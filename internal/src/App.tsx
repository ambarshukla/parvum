import { useEffect, useState } from "react";
import { checkSession, fetchDqMetrics, logout } from "./api";
import { LoginPage } from "./LoginPage";
import { OpsPage } from "./OpsPage";
import type { DqMetricRow } from "./types";

type Theme = "light" | "dark";
type AuthState = "checking" | "out" | "in";

function initialTheme(): Theme {
    const stored = localStorage.getItem("parvum-theme");
    if (stored === "light" || stored === "dark") return stored;
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function App() {
    const [theme, setTheme] = useState<Theme>(initialTheme);
    const [auth, setAuth] = useState<AuthState>("checking");
    const [dqMetrics, setDqMetrics] = useState<DqMetricRow[] | null>(null);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        document.documentElement.setAttribute("data-theme", theme);
        localStorage.setItem("parvum-theme", theme);
    }, [theme]);

    useEffect(() => {
        checkSession().then((ok) => setAuth(ok ? "in" : "out"));
    }, []);

    useEffect(() => {
        if (auth !== "in") return;
        fetchDqMetrics()
            .then(setDqMetrics)
            .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
    }, [auth]);

    return (
        <div className="app">
            <header className="topbar">
                <div className="brand">
                    <span className="mark">◆ Parvum</span>
                    <span className="section">Internal</span>
                </div>
                <div className="spacer" />
                {auth === "in" && (
                    <button
                        className="theme-toggle"
                        onClick={() => logout().then(() => setAuth("out"))}
                    >
                        Sign out
                    </button>
                )}
                <button
                    className="theme-toggle"
                    onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
                    aria-label="Toggle colour theme"
                >
                    {theme === "dark" ? "☀ Light" : "☾ Dark"}
                </button>
            </header>

            {auth === "checking" && <div className="center-state">Loading…</div>}
            {auth === "out" && <LoginPage onLoggedIn={() => setAuth("in")} />}
            {auth === "in" && (
                <div className="body">
                    <main className="main">
                        {error && (
                            <div className="center-state">
                                <strong>Could not reach the serving API.</strong>
                                <code>{error}</code>
                            </div>
                        )}
                        {!error && !dqMetrics && <div className="center-state">Loading…</div>}
                        {!error && dqMetrics && (
                            <OpsPage rows={dqMetrics} dark={theme === "dark"} />
                        )}
                    </main>
                </div>
            )}
        </div>
    );
}
