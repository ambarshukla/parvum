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
    altsUsd: 0,
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
    performance: [
        {
            asOf: "2026-04-20",
            clientId: "CLI-REYES",
            clientName: "Reyes Family",
            totalWealthUsd: 1897109.79,
            externalFlowUsd: 0,
            dailyTwrReturn: null,
            twrIndexSinceInception: 1,
        },
        {
            asOf: "2026-07-17",
            clientId: "CLI-REYES",
            clientName: "Reyes Family",
            totalWealthUsd: 1712828.76,
            externalFlowUsd: 0,
            dailyTwrReturn: -0.013054,
            twrIndexSinceInception: 0.89226698,
        },
    ],
    performanceSummary: [
        {
            clientId: "CLI-REYES",
            clientName: "Reyes Family",
            inceptionDate: "2026-04-20",
            asOf: "2026-07-17",
            wealthBeginUsd: 1897109.79,
            wealthEndUsd: 1712828.76,
            netExternalFlowUsd: 22500,
            twrSinceInception: -0.10773302,
            dietzSinceInception: -0.10785682,
            irrSinceInceptionAnnualized: -0.37707435,
        },
    ],
    altsHoldings: [
        {
            clientId: "CLI-REYES",
            clientName: "Reyes Family",
            fundId: "FUND-PE01",
            fundName: "Meridian Capital Partners IV",
            accountId: "X4478210",
            inceptionDate: "2024-03-31",
            asOf: "2026-06-30",
            totalCommitmentUsd: 3000000,
            calledToDateUsd: 1800000,
            distributedToDateUsd: 200000,
            unfundedCommitmentUsd: 1200000,
            currentNavUsd: 1900000,
            moic: 1.17,
            pendingReviewDocuments: 1,
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

    it("shows the three since-inception methodologies on the performance tab", () => {
        render(<ClientDashboard data={data} client={reyes} dark={false} />);
        fireEvent.click(screen.getByRole("tab", { name: "Performance" }));

        expect(screen.getByText("-10.77%")).toBeInTheDocument(); // TWR
        expect(screen.getByText("-10.79%")).toBeInTheDocument(); // Modified Dietz
        expect(screen.getByText("-37.71%")).toBeInTheDocument(); // IRR, annualized
        expect(screen.getByText("$22,500")).toBeInTheDocument(); // net external flow
    });

    it("shows the fund detail and a pending-review badge on the alternatives tab", () => {
        render(<ClientDashboard data={data} client={reyes} dark={false} />);
        fireEvent.click(screen.getByRole("tab", { name: "Alternatives" }));

        expect(screen.getByText("Meridian Capital Partners IV")).toBeInTheDocument();
        expect(screen.getByText("1.17x")).toBeInTheDocument();
        expect(screen.getByText(/1 pending review/)).toBeInTheDocument();
    });
});
