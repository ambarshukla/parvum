import { useEffect, useState } from "react";
import { checkSession, logout } from "./api";
import { LoginPage } from "./LoginPage";

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

    useEffect(() => {
        document.documentElement.setAttribute("data-theme", theme);
        localStorage.setItem("parvum-theme", theme);
    }, [theme]);

    useEffect(() => {
        checkSession().then((ok) => setAuth(ok ? "in" : "out"));
    }, []);

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
                <div className="center-state">
                    Signed in. Ops and the alts review queue land here next.
                </div>
            )}
        </div>
    );
}
