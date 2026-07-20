import { useState } from "react";
import { ApiError, login } from "./api";

interface Props {
    onLoggedIn: () => void;
}

export function LoginPage({ onLoggedIn }: Props) {
    const [password, setPassword] = useState("");
    const [error, setError] = useState<string | null>(null);
    const [submitting, setSubmitting] = useState(false);

    async function handleSubmit(e: React.FormEvent) {
        e.preventDefault();
        setError(null);
        setSubmitting(true);
        try {
            await login(password);
            onLoggedIn();
        } catch (e) {
            setError(
                e instanceof ApiError && e.status === 401
                    ? "Wrong password."
                    : "Could not reach the serving API.",
            );
        } finally {
            setSubmitting(false);
        }
    }

    return (
        <div className="center-state">
            <form
                onSubmit={handleSubmit}
                style={{ display: "flex", flexDirection: "column", gap: 12, width: 260 }}
            >
                <div className="brand" style={{ justifyContent: "center", color: "var(--ink)" }}>
                    <span className="mark">◆ Parvum</span>
                    <span className="section">Internal</span>
                </div>
                <input
                    type="password"
                    autoFocus
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder="Password"
                    aria-label="Password"
                    className="tenant-select"
                    style={{ color: "var(--ink)", borderColor: "var(--border)" }}
                />
                <button type="submit" className="theme-toggle" disabled={submitting}>
                    {submitting ? "Signing in…" : "Sign in"}
                </button>
                {error && <code style={{ color: "var(--critical)" }}>{error}</code>}
            </form>
        </div>
    );
}
