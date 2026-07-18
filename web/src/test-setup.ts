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
