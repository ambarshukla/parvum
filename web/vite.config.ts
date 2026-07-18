/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The API base is injected at build time (VITE_API_BASE); in dev it defaults
// to same-origin, and calls are proxied to the local Quarkus app below — so
// the browser never makes a cross-origin request and CORS is never in play.
export default defineConfig({
    plugins: [react()],
    server: {
        proxy: {
            "/tenants": "http://localhost:8080",
            "/q": "http://localhost:8080",
        },
    },
    test: {
        globals: true,
        environment: "jsdom",
        setupFiles: ["./src/test-setup.ts"],
    },
});
