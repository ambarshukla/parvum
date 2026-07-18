import { describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { ClientDashboard } from "./ClientDashboard";
import type { TenantData, WealthRow } from "./types";

const reyes: WealthRow = {
    asOf: "2026-07-17",
    clientId: "CLI-REYES",
    clientName: "Reyes Family",
    positionsUsd: 1645489.38,
    cashUsd: 48811.45,
    totalWealthUsd: 1694300.83,
    fxRateUsed: 1.1435,
    fxRateDate: "2026-07-17",
    booksReconcile: true,
};

const data: TenantData = {
    wealth: [reyes],
    allocation: [
        {
            asOf: "2026-07-17",
            clientId: "CLI-REYES",
            clientName: "Reyes Family",
            assetClass: "Equity",
            valueUsd: 1600000,
            weight: 0.97,
        },
    ],
    income: [],
    holdings: [],
    ownership: [
        {
            accountId: "ACC-SHARED",
            clientId: "CLI-REYES",
            clientName: "Reyes Family",
            ownershipPct: 0.6,
            ownerCount: 2,
            isShared: true,
        },
        {
            accountId: "ACC-SHARED",
            clientId: "CLI-OKAFOR",
            clientName: "Okafor Family",
            ownershipPct: 0.4,
            ownerCount: 2,
            isShared: true,
        },
    ],
};

describe("ClientDashboard", () => {
    it("shows the headline wealth on the overview", () => {
        render(<ClientDashboard data={data} client={reyes} dark={false} />);
        expect(screen.getByText("Reyes Family")).toBeInTheDocument();
        expect(screen.getByText("$1,694,301")).toBeInTheDocument();
    });

    it("surfaces the shared account and its co-owner on the ownership tab", () => {
        render(<ClientDashboard data={data} client={reyes} dark={false} />);
        fireEvent.click(screen.getByRole("tab", { name: "Ownership" }));

        expect(screen.getByText("ACC-SHARED")).toBeInTheDocument();
        expect(screen.getByText("60.00%")).toBeInTheDocument();
        expect(screen.getByText(/Shared · 2 owners/)).toBeInTheDocument();
        // The co-owner in the same firm is named, with their share.
        expect(screen.getByText(/Okafor Family \(40%\)/)).toBeInTheDocument();
    });
});
