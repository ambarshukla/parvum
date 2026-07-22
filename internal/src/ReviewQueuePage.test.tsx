import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ReviewQueuePage } from "./ReviewQueuePage";
import type { QueueItem } from "./types";

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
    vi.spyOn(globalThis, "fetch").mockImplementation(() => {
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
