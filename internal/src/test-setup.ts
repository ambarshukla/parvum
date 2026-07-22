import "@testing-library/jest-dom";

// Recharts' ResponsiveContainer observes its box; jsdom has no ResizeObserver,
// so provide a no-op one. Charts then render at zero size (fine for asserting
// structure, not pixels).
class ResizeObserverStub {
    observe() {}
    unobserve() {}
    disconnect() {}
}

globalThis.ResizeObserver ??= ResizeObserverStub as unknown as typeof ResizeObserver;

// jsdom has no canvas backend, so getContext() returns null and any real
// rasterisation is impossible. pdf.js itself is mocked in the tests that touch
// it; this only keeps element construction from throwing.
HTMLCanvasElement.prototype.getContext = (() =>
    ({}) as unknown) as unknown as typeof HTMLCanvasElement.prototype.getContext;

// jsdom lacks Blob.arrayBuffer() in some versions; the document viewer reads
// fetched bytes through it before handing them to the renderer.
if (!("arrayBuffer" in Blob.prototype)) {
    Object.defineProperty(Blob.prototype, "arrayBuffer", {
        value(this: Blob) {
            return Promise.resolve(new ArrayBuffer(8));
        },
    });
}

// jsdom has no matchMedia; App reads it once for the initial theme.
globalThis.matchMedia ??= ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
})) as unknown as typeof matchMedia;
