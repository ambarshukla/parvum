// Shapes returned by the serving API (dev.parvum.serving.api.ProjectionResource).
// Money and weights arrive as JSON numbers; we keep them as numbers and format
// at the edge.

export interface WealthRow {
    asOf: string;
    clientId: string;
    clientName: string;
    positionsUsd: number;
    cashUsd: number;
    totalWealthUsd: number;
    fxRateUsed: number;
    fxRateDate: string;
    booksReconcile: boolean;
}

export interface AllocationRow {
    asOf: string;
    clientId: string;
    clientName: string;
    assetClass: string;
    valueUsd: number;
    weight: number;
}

export interface IncomeRow {
    clientId: string;
    clientName: string;
    month: string;
    type: "DIVIDEND" | "INTEREST";
    incomeUsd: number;
    movements: number;
}

export interface HoldingRow {
    asOf: string;
    clientId: string;
    clientName: string;
    rank: number;
    securityName: string;
    securityScheme: string;
    securityId: string;
    assetClass: string;
    ownedUsd: number;
    weight: number;
}

export interface OwnershipRow {
    accountId: string;
    clientId: string;
    clientName: string;
    ownershipPct: number;
    ownerCount: number;
    isShared: boolean;
}

export interface PerformanceRow {
    asOf: string;
    clientId: string;
    clientName: string;
    totalWealthUsd: number;
    externalFlowUsd: number;
    dailyTwrReturn: number | null;
    twrIndexSinceInception: number;
}

export interface PerformanceSummaryRow {
    clientId: string;
    clientName: string;
    inceptionDate: string;
    asOf: string;
    wealthBeginUsd: number;
    wealthEndUsd: number;
    netExternalFlowUsd: number;
    twrSinceInception: number;
    dietzSinceInception: number | null;
    irrSinceInceptionAnnualized: number | null;
}

// Everything the dashboard needs for one tenant, fetched together.
export interface TenantData {
    wealth: WealthRow[];
    allocation: AllocationRow[];
    income: IncomeRow[];
    holdings: HoldingRow[];
    ownership: OwnershipRow[];
    performance: PerformanceRow[];
    performanceSummary: PerformanceSummaryRow[];
}
