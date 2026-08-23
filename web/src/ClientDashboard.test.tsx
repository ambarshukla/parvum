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
    reconcileBreakAccounts: 0,
    reconcileVarianceUsd: 0,
};

const reyesUnreconciled: WealthRow = {
    ...reyes,
    booksReconcile: false,
    reconcileBreakAccounts: 1,
    reconcileVarianceUsd: 2480.15,
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
            restatementAdjustmentUsd: 0,
            restatementDetail: null,
            dailyTwrReturn: null,
            twrIndexSinceInception: 1,
        },
        {
            asOf: "2026-07-17",
            clientId: "CLI-REYES",
            clientName: "Reyes Family",
            totalWealthUsd: 1712828.76,
            externalFlowUsd: 0,
            restatementAdjustmentUsd: 0,
            restatementDetail: null,
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
            restatementAdjustmentUsd: 0,
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
            currency: "USD",
            inceptionDate: "2024-03-31",
            asOf: "2026-06-30",
            totalCommitmentUsd: 3000000,
            calledToDateUsd: 1800000,
            distributedToDateUsd: 200000,
            unfundedCommitmentUsd: 1200000,
            currentNavUsd: 1900000,
            moic: 1.17,
            pendingReviewDocuments: 1,
            pendingReviewLatestPeriod: "2026-09-30",
        },
        {
            clientId: "CLI-REYES",
            clientName: "Reyes Family",
            fundId: "FUND-EU01",
            fundName: "Alpenrose Capital Fund III",
            accountId: "FQ5521",
            currency: "EUR",
            inceptionDate: "2024-03-31",
            asOf: "2026-06-30",
            totalCommitmentUsd: 1600000,
            calledToDateUsd: 400000,
            distributedToDateUsd: 50000,
            unfundedCommitmentUsd: 1200000,
            currentNavUsd: 380000,
            moic: 1.08,
            pendingReviewDocuments: 0,
            pendingReviewLatestPeriod: null,
        },
    ],
    reconciliationExceptions: [
        {
            clientId: "CLI-REYES",
            clientName: "Reyes Family",
            accountId: "ACC-SHARED",
            asOf: "2026-07-17",
            currency: "USD",
            deltaNative: 2480.15,
            deltaUsd: 2480.15,
        },
    ],
};

describe("ClientDashboard", () => {
    it("shows the headline wealth on the overview", () => {
        render(<ClientDashboard data={data} client={reyes} dark={false} />);
        expect(screen.getByText("Reyes Family")).toBeInTheDocument();
        expect(screen.getByText("$1,694,301")).toBeInTheDocument();
    });

    it("shows the account count and dollar variance behind a reconcile break", () => {
        render(<ClientDashboard data={data} client={reyesUnreconciled} dark={false} />);
        // Not just a boolean: how many of the client's accounts, and how much.
        expect(
            screen.getByText(/Reconciliation variance · 1 of 1 account · \$2,480/),
        ).toBeInTheDocument();
    });

    it("clicking the reconcile badge reveals which account and how much", () => {
        render(<ClientDashboard data={data} client={reyesUnreconciled} dark={false} />);

        // Not shown until clicked.
        expect(screen.queryByText("ACC-SHARED")).not.toBeInTheDocument();

        fireEvent.click(screen.getByRole("button", { name: /Reconciliation variance/ }));

        const row = screen.getByText("ACC-SHARED").closest("tr");
        expect(row).toHaveTextContent("$2,480");
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

    it("says nothing about restatements when the book has not been restated", () => {
        // The overwhelmingly common case. A disclosure tile that showed $0 on
        // every ordinary client would train readers to ignore it.
        render(<ClientDashboard data={data} client={reyes} dark={false} />);
        fireEvent.click(screen.getByRole("tab", { name: "Performance" }));

        expect(screen.queryByText("Book restatement")).not.toBeInTheDocument();
    });

    it("discloses a book restatement so the wealth step reconciles (D-070)", () => {
        // Without this tile the tab shows wealth quintupling, $137,500 of client
        // money, and a NEGATIVE return -- three figures that cannot all be true
        // together, which reads as a broken dashboard rather than a restated book.
        const detail = "60011234: divisor 10000 -> 2000 (D-066)";
        const restated = {
            ...data,
            performance: [
                {
                    asOf: "2026-08-14",
                    clientId: "CLI-REYES",
                    clientName: "Reyes Family",
                    totalWealthUsd: 43024684.9,
                    externalFlowUsd: 0,
                    restatementAdjustmentUsd: 0,
                    restatementDetail: null,
                    dailyTwrReturn: -0.00001133,
                    twrIndexSinceInception: 0.95831694,
                },
                {
                    asOf: "2026-08-17",
                    clientId: "CLI-REYES",
                    clientName: "Reyes Family",
                    totalWealthUsd: 221199794.78,
                    externalFlowUsd: 0,
                    restatementAdjustmentUsd: 178175109.88,
                    restatementDetail: detail,
                    dailyTwrReturn: null,
                    twrIndexSinceInception: 0.95831694,
                },
            ],
            performanceSummary: [
                {
                    clientId: "CLI-REYES",
                    clientName: "Reyes Family",
                    inceptionDate: "2026-05-21",
                    asOf: "2026-08-21",
                    wealthBeginUsd: 44722729.1,
                    wealthEndUsd: 221166594.3,
                    netExternalFlowUsd: 137500,
                    restatementAdjustmentUsd: 178175109.88,
                    twrSinceInception: -0.04169151,
                    dietzSinceInception: -0.03692517,
                    irrSinceInceptionAnnualized: -0.10542851,
                },
            ],
        };

        render(<ClientDashboard data={restated} client={reyes} dark={false} />);
        fireEvent.click(screen.getByRole("tab", { name: "Performance" }));

        expect(screen.getByText("Book restatement")).toBeInTheDocument();
        expect(screen.getByText("$178,175,110")).toBeInTheDocument();
        // The point of the tile is the sentence, not the number.
        expect(screen.getByText(/Change of scale, not performance/)).toBeInTheDocument();
        // And the provenance is reachable without a second request.
        expect(screen.getByTitle(/17 Aug 2026 .* divisor 10000 -> 2000/)).toBeInTheDocument();
    });

    it("shows the fund detail and a pending-review badge on the alternatives tab", () => {
        render(<ClientDashboard data={data} client={reyes} dark={false} />);
        fireEvent.click(screen.getByRole("tab", { name: "Alternatives" }));

        expect(screen.getByText("Meridian Capital Partners IV")).toBeInTheDocument();
        expect(screen.getByText("1.17x")).toBeInTheDocument();
        // Plain language, not the internal document-type taxonomy.
        expect(
            screen.getByText(/Newer figures pending · through 30 Sept? 2026/),
        ).toBeInTheDocument();
        expect(screen.queryByText(/capital_account_statement/)).not.toBeInTheDocument();
    });

    it("annotates a non-USD fund but not a USD one on the alternatives tab", () => {
        render(<ClientDashboard data={data} client={reyes} dark={false} />);
        fireEvent.click(screen.getByRole("tab", { name: "Alternatives" }));

        expect(screen.getByText("Alpenrose Capital Fund III")).toBeInTheDocument();
        expect(screen.getByText("(EUR)")).toBeInTheDocument();
        // The USD fund's row carries no currency annotation.
        expect(
            screen.getByText("Meridian Capital Partners IV").parentElement,
        ).not.toHaveTextContent("(USD)");
    });
});
