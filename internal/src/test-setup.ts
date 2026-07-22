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

// jsdom implements neither half of the object-URL API, which the PDF viewer
// uses to hand a fetched blob to an <iframe>. Stub both: the tests assert the
// frame is wired up, not that a real PDF renders.
globalThis.URL.createObjectURL ??= (() => "blob:stub") as unknown as typeof URL.createObjectURL;
globalThis.URL.revokeObjectURL ??= (() => {}) as unknown as typeof URL.revokeObjectURL;

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
