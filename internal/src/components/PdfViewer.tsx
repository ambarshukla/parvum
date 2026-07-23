import { useEffect, useRef, useState } from "react";

/** pdf.js is large (~350 KB gzipped against a ~150 KB app), so it is imported
 *  dynamically: Vite gives it its own chunk, fetched the first time a reviewer
 *  opens a document rather than on every page load. The promise is cached at
 *  module scope so flicking between documents loads it once. */
type Pdfjs = typeof import("pdfjs-dist");

let pdfjsPromise: Promise<Pdfjs> | null = null;

function loadPdfjs(): Promise<Pdfjs> {
    pdfjsPromise ??= (async () => {
        const pdfjs = await import("pdfjs-dist");
        // The worker has to be a real URL Vite can emit as an asset; without
        // it pdf.js falls back to parsing on the main thread and blocks the UI.
        const worker = await import("pdfjs-dist/build/pdf.worker.min.mjs?url");
        pdfjs.GlobalWorkerOptions.workerSrc = worker.default;
        return pdfjs;
    })();
    return pdfjsPromise;
}

const ZOOM_STEPS = [0.75, 1, 1.25, 1.5, 2, 3] as const;

interface Props {
    /** The raw PDF bytes. */
    data: ArrayBuffer;
    /** Used for the accessible name of the rendered document. */
    label: string;
}

/** Renders a PDF with pdf.js onto canvases this app owns.
 *
 *  Deliberately not an `<iframe>` pointed at the bytes: that hands rendering
 *  to whatever viewer the browser happens to ship, which means an unstyleable
 *  third-party toolbar on desktop and, on several mobile browsers, a download
 *  prompt instead of a document (D-058). */
export function PdfViewer({ data, label }: Props) {
    // Measured for fit-to-width. The wrapper's width comes from the layout
    // above it, never from the canvases inside it — so appending pages can't
    // feed back into the observer and loop.
    const wrapRef = useRef<HTMLDivElement>(null);
    const pagesRef = useRef<HTMLDivElement>(null);

    const [width, setWidth] = useState(0);
    const [zoom, setZoom] = useState(1);
    const [pageCount, setPageCount] = useState(0);
    const [error, setError] = useState<string | null>(null);
    const [ready, setReady] = useState(false);

    useEffect(() => {
        const el = wrapRef.current;
        if (!el) return;
        const measure = () =>
            setWidth((prev) => {
                const next = Math.floor(el.clientWidth);
                return next > 0 && next !== prev ? next : prev;
            });
        measure();
        const observer = new ResizeObserver(measure);
        observer.observe(el);
        return () => observer.disconnect();
    }, []);

    useEffect(() => {
        if (!width) return;
        const host = pagesRef.current;
        if (!host) return;

        let cancelled = false;
        setReady(false);
        setError(null);

        (async () => {
            try {
                const pdfjs = await loadPdfjs();
                if (cancelled) return;

                // pdf.js transfers the buffer to its worker, which detaches it.
                // Hand over a copy so the caller's bytes stay usable — without
                // this, a re-render at a new zoom level gets an empty buffer.
                //
                // destroy() lives on the loading task, not the document, so the
                // task is what has to be held onto to tear the worker down.
                // standardFontDataUrl matters here specifically: these
                // documents use Helvetica without embedding it, so pdf.js has
                // to fetch the face itself or the page renders with no text.
                // vite.config.ts copies that data into public/ at build time.
                const task = pdfjs.getDocument({
                    data: data.slice(0),
                    standardFontDataUrl: `${import.meta.env.BASE_URL}standard_fonts/`,
                });
                const doc = await task.promise;
                if (cancelled) {
                    void task.destroy();
                    return;
                }
                setPageCount(doc.numPages);

                // Render into a detached fragment and swap it in at the end, so
                // the pane never shows a half-drawn document.
                const fragment = document.createDocumentFragment();
                const ratio = window.devicePixelRatio || 1;

                for (let n = 1; n <= doc.numPages; n++) {
                    const page = await doc.getPage(n);
                    if (cancelled) break;

                    const unscaled = page.getViewport({ scale: 1 });
                    // Fit the pane, then apply zoom, then oversample by the
                    // device pixel ratio so text stays sharp on a HiDPI screen.
                    const cssScale = (width / unscaled.width) * zoom;
                    const viewport = page.getViewport({ scale: cssScale * ratio });

                    const canvas = document.createElement("canvas");
                    canvas.className = "pdf-page";
                    canvas.width = Math.floor(viewport.width);
                    canvas.height = Math.floor(viewport.height);
                    canvas.style.width = `${Math.floor(viewport.width / ratio)}px`;
                    canvas.style.height = `${Math.floor(viewport.height / ratio)}px`;
                    fragment.append(canvas);

                    await page.render({ canvas, viewport }).promise;
                    page.cleanup();
                }

                if (cancelled) {
                    void task.destroy();
                    return;
                }
                host.replaceChildren(fragment);
                setReady(true);
                void task.destroy();
            } catch (e) {
                if (!cancelled) setError(e instanceof Error ? e.message : String(e));
            }
        })();

        return () => {
            cancelled = true;
        };
    }, [data, zoom, width]);

    const zoomIndex = ZOOM_STEPS.indexOf(zoom as (typeof ZOOM_STEPS)[number]);

    return (
        <div className="pdf-viewer">
            <div className="pdf-toolbar">
                <span className="muted pdf-pages">
                    {pageCount > 0 ? `${pageCount} page${pageCount > 1 ? "s" : ""}` : " "}
                </span>
                <div className="spacer" />
                <button
                    className="pdf-zoom"
                    onClick={() => setZoom(ZOOM_STEPS[Math.max(0, zoomIndex - 1)] ?? 1)}
                    disabled={zoomIndex <= 0}
                    aria-label="Zoom out"
                >
                    −
                </button>
                <span className="muted pdf-zoom-level">{Math.round(zoom * 100)}%</span>
                <button
                    className="pdf-zoom"
                    onClick={() =>
                        setZoom(ZOOM_STEPS[Math.min(ZOOM_STEPS.length - 1, zoomIndex + 1)] ?? 1)
                    }
                    disabled={zoomIndex >= ZOOM_STEPS.length - 1}
                    aria-label="Zoom in"
                >
                    +
                </button>
            </div>

            <div className="pdf-scroll" ref={wrapRef}>
                {error && (
                    <div className="pdf-state">
                        <span className="muted">Could not render the document.</span>
                        <code>{error}</code>
                    </div>
                )}
                {!error && !ready && <div className="pdf-state muted">Rendering document…</div>}
                <div ref={pagesRef} className="pdf-pages-host" role="document" aria-label={label} />
            </div>
        </div>
    );
}
