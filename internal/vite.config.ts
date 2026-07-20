/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// A different port from web/ (5173) so both dashboards can run locally at
// once. The API base mirrors web/'s split-deployment story (VITE_API_BASE
// override, same-origin default); the dev proxy keeps this app same-origin
// with Quarkus too, so the cross-site cookie/CORS path only exists in prod.
export default defineConfig({
    plugins: [react()],
    server: {
        port: 5174,
        proxy: {
            "/internal": "http://localhost:8080",
        },
    },
    test: {
        globals: true,
        environment: "jsdom",
        setupFiles: ["./src/test-setup.ts"],
    },
});
