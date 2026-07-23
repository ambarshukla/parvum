import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ReviewQueuePage } from "./ReviewQueuePage";
import type { QueueItem } from "./types";

// pdf.js rasterises to a canvas, which jsdom cannot do. Mock it at the module
// boundary: these tests are about the page wiring the renderer up with the
// right bytes and label, not about pixels — the real renderer is exercised
// against real documents in the browser.
vi.mock("pdfjs-dist", () => ({
    GlobalWorkerOptions: { workerSrc: "" },
    getDocument: () => ({
        destroy: () => Promise.resolve(),
        promise: Promise.resolve({
            numPages: 1,
            getPage: () =>
                Promise.resolve({
                    getViewport: ({ scale }: { scale: number }) => ({
                        width: 600 * scale,
                        height: 800 * scale,
                    }),
                    render: () => ({ promise: Promise.resolve() }),
                    cleanup: () => {},
                }),
            destroy: () => Promise.resolve(),
        }),
    }),
}));

vi.mock("pdfjs-dist/build/pdf.worker.min.mjs?url", () => ({ default: "worker-stub" }));

afterEach(() => {
    vi.restoreAllMocks();
});

const PENDING_ITEM: QueueItem = {
    id: 1,
    fundId: "FUND-PE01",
    document: "capital_call_02.pdf",
    docType: "capital_call",
    sequenceNumber: 2,
    periodEnd: null,
    extractedFields: JSON.stringify({
        call_amount: "100000.00",
        call_number: 2,
        recallable: true,
        purpose: null,
    }),
    confidence: 0.7,
    validationNotes: "cumulative_called 1751000.00 != running sum 1750000.00",
    status: "pending",
    stale: false,
    decidedFields: null,
    decidedAt: null,
    loadedAt: "2026-07-22T10:00:00Z",
};

const APPROVED_ITEM: QueueItem = {
    ...PENDING_ITEM,
    id: 2,
    document: "capital_call_01.pdf",
    status: "approved",
    decidedFields: PENDING_ITEM.extractedFields,
    decidedAt: "2026-07-22T11:00:00Z",
};

function mockFetchSequence(responses: Array<[string, unknown, number?]>) {
    let call = 0;
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
        // The PDF viewer fetches whenever a document is selected. Answer it
        // out of band rather than from the sequence, so every other test
        // doesn't have to budget an entry for a request it isn't about.
        if (String(input).includes("/internal/alts/documents/")) {
            return Promise.resolve(new Response("%PDF-1.4 stub", { status: 200 }));
        }
        const entry = responses[Math.min(call, responses.length - 1)]!;
        const [, body, status] = entry;
        call += 1;
        return Promise.resolve(new Response(JSON.stringify(body), { status: status ?? 200 }));
    });
}

describe("ReviewQueuePage", () => {
    it("shows a placeholder when there are no pending documents", async () => {
        mockFetchSequence([["list", []]]);
        render(<ReviewQueuePage />);
        await waitFor(() => expect(screen.getByText("No pending documents.")).toBeInTheDocument());
    });

    it("lists queue items and shows the first one's extracted fields", async () => {
        mockFetchSequence([["list", [PENDING_ITEM]]]);
        render(<ReviewQueuePage />);

        await waitFor(() =>
            expect(screen.getAllByText("capital_call_02.pdf").length).toBeGreaterThanOrEqual(1),
        );
        expect(screen.getAllByText(/FUND-PE01/).length).toBeGreaterThanOrEqual(1);
        expect(screen.getByText(PENDING_ITEM.validationNotes!)).toBeInTheDocument();
        expect(screen.getByLabelText("call_amount")).toHaveValue("100000.00");
        expect(screen.getByLabelText("recallable")).toHaveValue("true");
    });

    it("renders the source PDF beside the extracted fields, in the app's own viewer", async () => {
        mockFetchSequence([["list", [PENDING_ITEM]]]);
        render(<ReviewQueuePage />);

        // Labelled by the app, not by a browser's built-in viewer — the point
        // of D-058 is that this element is ours.
        await waitFor(() =>
            expect(
                screen.getByLabelText("capital_call_02.pdf — source document"),
            ).toBeInTheDocument(),
        );
        // The zoom controls are the app's chrome; a browser viewer would have
        // supplied its own and we'd have none of these.
        expect(screen.getByLabelText("Zoom in")).toBeInTheDocument();
        expect(screen.getByLabelText("Zoom out")).toBeInTheDocument();
    });

    it("approving a pending item reloads the list and clears it from the pending view", async () => {
        mockFetchSequence([
            ["list", [PENDING_ITEM]],
            ["approve", { ...PENDING_ITEM, status: "approved" }],
            ["list-after", []],
        ]);
        render(<ReviewQueuePage />);

        await waitFor(() => expect(screen.getByText("Approve as extracted")).toBeInTheDocument());
        fireEvent.click(screen.getByText("Approve as extracted"));

        await waitFor(() => expect(screen.getByText("No pending documents.")).toBeInTheDocument());
    });

    it("a decided item shows its decided fields read-only, with no action buttons", async () => {
        mockFetchSequence([["list", [APPROVED_ITEM]]]);
        render(<ReviewQueuePage />);

        // Switch to the "Approved" filter to see it (default view is "Pending").
        fireEvent.click(screen.getByText("Approved"));

        await waitFor(() =>
            expect(screen.getAllByText("capital_call_01.pdf").length).toBeGreaterThanOrEqual(1),
        );
        expect(screen.queryByText("Approve as extracted")).not.toBeInTheDocument();
        expect(screen.queryByLabelText("call_amount")).not.toBeInTheDocument();
        expect(screen.getByText("100000.00")).toBeInTheDocument();
    });
});
