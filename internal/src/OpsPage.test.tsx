import { describe, expect, it } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { OpsPage } from "./OpsPage";
import type { CdeRegistryRow, DqMetricRow, SloAttainmentRow } from "./types";

const rows: DqMetricRow[] = [
    {
        asOf: "2026-07-19",
        dimension: "freshness",
        metric: "bronze_days_behind",
        value: 1,
        passed: true,
        detail: "bronze last landed 2026-07-17",
    },
    {
        asOf: "2026-07-17",
        dimension: "completeness",
        metric: "files_landed_rate",
        value: 1,
        passed: true,
        detail: "11 of 11 expected files parsed",
    },
    {
        asOf: "2026-07-16",
        dimension: "accuracy",
        metric: "holdings_cross_format_match_rate",
        value: 0.95,
        passed: false,
        detail: "3 cross-format findings across 60 positions",
    },
    {
        asOf: "2026-07-17",
        dimension: "accuracy",
        metric: "holdings_cross_format_match_rate",
        value: 1,
        passed: true,
        detail: "0 cross-format findings across 60 positions",
    },
    {
        asOf: "2026-07-17",
        dimension: "exceptions",
        metric: "holdings_findings_count",
        value: 0,
        passed: null,
        detail: "0 cross-format findings",
    },
];

const governanceRows: DqMetricRow[] = [
    {
        asOf: "2026-08-20",
        dimension: "governance",
        metric: "columns_classified_rate",
        value: 1,
        passed: true,
        detail: "309 of 309 published columns classified in the register",
    },
    {
        asOf: "2026-08-20",
        dimension: "governance",
        metric: "critical_control_coverage_rate",
        value: 0.357143,
        passed: false,
        detail: "10 of 28 critical elements have a quality rule; target 80%",
    },
];

const registry: CdeRegistryRow[] = [
    {
        tableName: "gold_client_wealth",
        columnName: "fx_rate_used",
        layer: "gold",
        description: "EUR to USD ECB reference rate",
        tier: "critical",
        owner: "reference-data",
        definition: "The rate applied to this date's EUR amounts.",
        qualityRules: "",
        qualityRuleCount: 0,
        controlGap: "Nothing re-checks a landed rate against its source.",
        slo: "gold_freshness",
        sloMeasuredBy: "bronze_days_behind",
        sloTarget: "no more than 2 days behind",
    },
    {
        tableName: "gold_client_wealth",
        columnName: "total_wealth_usd",
        layer: "gold",
        description: "The headline number",
        tier: "critical",
        owner: "client-reporting",
        definition: "Positions plus cash plus alternatives.",
        qualityRules: "files_landed_rate",
        qualityRuleCount: 1,
        controlGap: null,
        slo: "gold_freshness",
        sloMeasuredBy: "bronze_days_behind",
        sloTarget: "no more than 2 days behind",
    },
];

const slos: SloAttainmentRow[] = [
    {
        slo: "holdings_agreement",
        objective: "Positions agree across the two custodial holdings formats.",
        measuredBy: "holdings_cross_format_match_rate",
        target: "99% of account-days or better",
        attainmentObjective: 0.95,
        windowDays: 30,
        windowStart: "2026-06-20",
        windowEnd: "2026-07-19",
        daysMeasured: 20,
        daysMet: 0,
        attainment: 0,
        meetsObjective: false,
        insufficientHistory: false,
        errorBudgetDays: 1,
        budgetConsumedDays: 20,
        budgetRemainingPct: -19,
    },
    {
        slo: "gold_freshness",
        objective: "Client-facing figures reflect the most recent custodial feeds.",
        measuredBy: "bronze_days_behind",
        target: "no more than 2 days behind",
        attainmentObjective: 0.98,
        windowDays: 7,
        windowStart: "2026-07-19",
        windowEnd: "2026-07-19",
        daysMeasured: 1,
        daysMet: 1,
        attainment: 1,
        meetsObjective: null,
        insufficientHistory: true,
        errorBudgetDays: 0.02,
        budgetConsumedDays: 0,
        budgetRemainingPct: 1,
    },
    {
        slo: "cross_field_consistency",
        objective: "Published figures that describe the same fact agree.",
        measuredBy: "cross_field_invariant_rate",
        target: "100% of invariants, every day",
        attainmentObjective: 1,
        windowDays: 30,
        windowStart: "2026-06-20",
        windowEnd: "2026-07-19",
        daysMeasured: 20,
        daysMet: 20,
        attainment: 1,
        meetsObjective: true,
        insufficientHistory: false,
        errorBudgetDays: 0,
        budgetConsumedDays: 0,
        budgetRemainingPct: null,
    },
];

describe("OpsPage", () => {
    it("shows the freshness and completeness tiles, and a short series by value", () => {
        render(<OpsPage rows={rows} registry={[]} slos={[]} dark={false} />);
        expect(screen.getByText("Data Operations")).toBeInTheDocument();
        expect(screen.getByText("1d behind")).toBeInTheDocument();
        // The label also shows up in the chart legend, so there are two
        // matches by design.
        expect(screen.getAllByText("Cross-format match").length).toBeGreaterThanOrEqual(1);
        // Two days is below the attainment threshold, so the tile reports the
        // metric's own latest value and its detail rather than "1 of 2 days",
        // which would put a number under a label that does not mean it.
        expect(screen.queryByText("SLA attained 1 of 2 days")).not.toBeInTheDocument();
        expect(screen.getByText(/0 cross-format findings across 60 positions/)).toBeInTheDocument();
    });

    it("renders each service level with its attainment, and breaches sort first", () => {
        render(<OpsPage rows={rows} registry={[]} slos={slos} dark={false} />);
        expect(screen.getByText("Service levels")).toBeInTheDocument();
        // Identifiers are humanised, never rendered raw.
        expect(screen.getByText("Holdings agreement")).toBeInTheDocument();
        expect(screen.getByText("Cross-field consistency")).toBeInTheDocument();
        expect(screen.queryByText(/holdings_agreement/)).not.toBeInTheDocument();
        expect(screen.getByText("0.0%")).toBeInTheDocument();
        expect(screen.getByText("0/20 days")).toBeInTheDocument();
    });

    it("distinguishes met, breached, and not-enough-history — three states, not two", () => {
        render(<OpsPage rows={rows} registry={[]} slos={slos} dark={false} />);
        // "Breached" is also the wording on the accuracy tiles above, so scope
        // the assertion to the service-levels table rather than the document.
        const table = screen.getByText("Service levels").closest("div")!.parentElement!
            .nextElementSibling!;
        expect(within(table as HTMLElement).getByText("Breached")).toHaveClass("warn");
        expect(within(table as HTMLElement).getByText("Met")).toHaveClass("ok");
        // The one with a single day of history is neither. Reporting it as met
        // would be the false green a service level exists to prevent — and
        // colouring it as a warning would train people to ignore the colour
        // that means one.
        expect(within(table as HTMLElement).getByText("Not enough history")).toHaveClass("neutral");
    });

    it("says an objective of 1.0 has no error budget rather than showing a misleading 0%", () => {
        render(<OpsPage rows={rows} registry={[]} slos={slos} dark={false} />);
        expect(screen.getByText("None — objective is total")).toBeInTheDocument();
        // ...and a breach past the budget says so, rather than showing a
        // negative percentage nobody can interpret.
        expect(screen.getByText(/20 of 1 days spent — over budget/)).toBeInTheDocument();
    });

    it("shows the governance tiles and lists only the critical elements with a stated gap", () => {
        render(
            <OpsPage
                rows={[...rows, ...governanceRows]}
                registry={registry}
                slos={[]}
                dark={false}
            />,
        );
        expect(screen.getByText("Governance")).toBeInTheDocument();
        expect(screen.getByText("Register coverage")).toBeInTheDocument();
        expect(screen.getByText("36%")).toBeInTheDocument();

        // One of the two critical elements has a rule, so only the other is a gap.
        expect(
            screen.getByText("Critical elements with no automated control (1)"),
        ).toBeInTheDocument();
        expect(screen.getByText("gold_client_wealth.fx_rate_used")).toBeInTheDocument();
        expect(screen.queryByText("gold_client_wealth.total_wealth_usd")).not.toBeInTheDocument();
        expect(
            screen.getByText("Nothing re-checks a landed rate against its source."),
        ).toBeInTheDocument();
    });

    it("collapses columns that share one written gap into a single row", () => {
        // Gaps are written per column but caused per root. In production four
        // of five share one alts paragraph word for word, and repeating it
        // four times reads as a copy-paste glitch rather than one problem with
        // four symptoms.
        const shared = "The alts chain is validated document-to-document but never rolls up.";
        const grouped: CdeRegistryRow[] = [
            ...registry,
            {
                tableName: "gold_alts_holdings",
                columnName: "moic",
                layer: "gold",
                description: "Multiple on invested capital",
                tier: "critical",
                owner: "alts-operations",
                definition: "Distributions plus NAV over called.",
                qualityRules: "",
                qualityRuleCount: 0,
                controlGap: shared,
                slo: "gold_freshness",
                sloMeasuredBy: "bronze_days_behind",
                sloTarget: "no more than 2 days behind",
            },
            {
                tableName: "gold_alts_holdings",
                columnName: "current_nav_usd",
                layer: "gold",
                description: "Current NAV",
                tier: "critical",
                owner: "alts-operations",
                definition: "The fund's latest confirmed NAV.",
                qualityRules: "",
                qualityRuleCount: 0,
                controlGap: shared,
                slo: "gold_freshness",
                sloMeasuredBy: "bronze_days_behind",
                sloTarget: "no more than 2 days behind",
            },
        ];

        render(
            <OpsPage
                rows={[...rows, ...governanceRows]}
                registry={grouped}
                slos={[]}
                dark={false}
            />,
        );

        // Three gapped columns, but only two distinct causes.
        expect(
            screen.getByText("Critical elements with no automated control (3)"),
        ).toBeInTheDocument();
        // The shared statement is written once, not once per column.
        expect(screen.getAllByText(shared)).toHaveLength(1);
        // And both columns it covers are still named.
        expect(screen.getByText("gold_alts_holdings.moic")).toBeInTheDocument();
        expect(screen.getByText("gold_alts_holdings.current_nav_usd")).toBeInTheDocument();
    });

    it("hides the governance section entirely when the dimension has no rows", () => {
        // A pipeline whose gold job predates D-068 still renders the rest.
        render(<OpsPage rows={rows} registry={registry} slos={[]} dark={false} />);
        expect(screen.queryByText("Governance")).not.toBeInTheDocument();
    });

    it("shows a placeholder when there is no DQ data yet", () => {
        render(<OpsPage rows={[]} registry={[]} slos={[]} dark={false} />);
        expect(screen.getByText("No DQ metrics recorded yet.")).toBeInTheDocument();
    });
});

describe("OpsPage accuracy tiles", () => {
    // The tiles render SLA *attainment*, which is not the metric's value. Over
    // a long series that reads correctly; over a one-row series it put "0%"
    // directly beneath a label naming a rate whose actual value was 60.9%.
    const singleRow: DqMetricRow[] = [
        {
            asOf: "2026-08-29",
            dimension: "accuracy",
            metric: "alts_cross_document_valid_rate",
            value: 0.609375,
            passed: false,
            detail: "39 of 64 private-fund documents reconcile against the rest of their fund",
        },
    ];

    it("shows the metric's own value when there is too little history for attainment", () => {
        render(<OpsPage rows={singleRow} registry={[]} slos={[]} dark={false} />);
        expect(screen.getAllByText("Alts document validity").length).toBeGreaterThanOrEqual(1);
        // 61%, the real rate — not 0%, which is what attainment over one
        // failing day would have said.
        expect(screen.getByText("61%")).toBeInTheDocument();
        expect(screen.queryByText("0%")).not.toBeInTheDocument();
        expect(screen.queryByText(/SLA attained/)).not.toBeInTheDocument();
    });

    it("still reports attainment once a real series exists", () => {
        const series: DqMetricRow[] = Array.from({ length: 10 }, (_, i) => ({
            asOf: `2026-08-${String(i + 1).padStart(2, "0")}`,
            dimension: "accuracy" as const,
            metric: "fx_rate_plausibility_rate",
            value: 1,
            passed: i > 1,
            detail: "rate moved 0.1% and was carried 1 day(s)",
        }));
        render(<OpsPage rows={series} registry={[]} slos={[]} dark={false} />);
        expect(screen.getAllByText("FX rate plausibility").length).toBeGreaterThanOrEqual(1);
        expect(screen.getByText("SLA attained 8 of 10 days")).toBeInTheDocument();
    });
});

describe("OpsPage tile row", () => {
    const covered: DqMetricRow[] = Array.from({ length: 10 }, (_, i) => ({
        asOf: `2026-08-${String(i + 1).padStart(2, "0")}`,
        dimension: "accuracy" as const,
        metric: "cash_conformed_consistency_rate",
        value: 1,
        passed: true,
        detail: "all accounts consistent",
    }));
    const uncovered: DqMetricRow[] = [
        {
            asOf: "2026-08-29",
            dimension: "accuracy",
            metric: "alts_cross_document_valid_rate",
            value: 0.609375,
            passed: false,
            detail: "39 of 64 private-fund documents reconcile",
        },
    ];
    const withSlo: SloAttainmentRow[] = [
        {
            slo: "cash_ledger_integrity",
            objective: "the ledger adds up",
            measuredBy: "cash_conformed_consistency_rate",
            target: "99% of account-days",
            attainmentObjective: 0.95,
            windowDays: 30,
            windowStart: "2026-07-30",
            windowEnd: "2026-08-28",
            daysMeasured: 22,
            daysMet: 10,
            attainment: 0.454545,
            meetsObjective: false,
            insufficientHistory: false,
            errorBudgetDays: 1.1,
            budgetConsumedDays: 12,
            budgetRemainingPct: -9.9,
        },
    ];

    it("gives no tile to a metric a service level already reports on", () => {
        // The duplicate that put "35%" beside "45.5%" for the same metric.
        render(
            <OpsPage rows={[...covered, ...uncovered]} registry={[]} slos={withSlo} dark={false} />,
        );
        // It still appears once, in the Accuracy trend chart's legend — the
        // chart is the history view and plotting it there is the point. What
        // it must not have is a *tile* stating an attainment figure the
        // Service levels row below states differently.
        expect(screen.getAllByText("Cash consistency")).toHaveLength(1);
        expect(screen.queryByText(/SLA attained 10 of 10 days/)).not.toBeInTheDocument();
        expect(screen.getByText("Cash ledger integrity")).toBeInTheDocument();
    });

    it("keeps a tile for a metric no service level covers", () => {
        render(
            <OpsPage rows={[...covered, ...uncovered]} registry={[]} slos={withSlo} dark={false} />,
        );
        expect(screen.getAllByText("Alts document validity").length).toBeGreaterThanOrEqual(1);
        expect(screen.getByText("61%")).toBeInTheDocument();
    });

    it("shows every metric when the service levels did not load", () => {
        // Degrading to a repeated number beats hiding quality information
        // because a second request failed.
        render(<OpsPage rows={[...covered, ...uncovered]} registry={[]} slos={[]} dark={false} />);
        expect(screen.getAllByText("Cash consistency").length).toBeGreaterThanOrEqual(1);
        expect(screen.getAllByText("Alts document validity").length).toBeGreaterThanOrEqual(1);
    });
});
