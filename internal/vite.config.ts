/// <reference types="vitest/config" />
import { cpSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

/** Copies pdf.js's standard-font data into `public/` so the browser can fetch
 *  it at runtime.
 *
 *  The generated fund documents reference the base-14 fonts (Helvetica,
 *  Helvetica-Bold) *without embedding* them — which is normal and legal in
 *  PDF: the viewer is expected to supply those faces. pdf.js ships the data
 *  but deliberately doesn't bundle it, so without this copy every page renders
 *  with no text at all. Copied from `node_modules` at build time rather than
 *  vendored into git, so ~800 KB of binary font data never enters the repo and
 *  can't drift from the installed pdf.js version. */
function pdfjsStandardFonts() {
    return {
        name: "pdfjs-standard-fonts",
        buildStart() {
            const require = createRequire(import.meta.url);
            const root = path.dirname(require.resolve("pdfjs-dist/package.json"));
            cpSync(path.join(root, "standard_fonts"), path.resolve("public/standard_fonts"), {
                recursive: true,
            });
        },
    };
}

// A different port from web/ (5173) so both dashboards can run locally at
// once. The API base mirrors web/'s split-deployment story (VITE_API_BASE
// override, same-origin default); the dev proxy keeps this app same-origin
// with Quarkus too, so the cross-site cookie/CORS path only exists in prod.
export default defineConfig({
    plugins: [react(), pdfjsStandardFonts()],
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
