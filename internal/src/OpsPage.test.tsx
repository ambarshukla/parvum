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
    it("shows the freshness and completeness tiles, and per-metric SLA attainment", () => {
        render(<OpsPage rows={rows} registry={[]} slos={[]} dark={false} />);
        expect(screen.getByText("Data Operations")).toBeInTheDocument();
        expect(screen.getByText("1d behind")).toBeInTheDocument();
        expect(screen.getByText("100%")).toBeInTheDocument(); // completeness, latest day
        // Cross-format match: 1 of 2 days passed = 50%. The label also shows
        // up in the chart legend, so there are two matches by design.
        expect(screen.getAllByText("Cross-format match").length).toBeGreaterThanOrEqual(1);
        expect(screen.getByText("50%")).toBeInTheDocument();
        expect(screen.getByText("SLA attained 1 of 2 days")).toBeInTheDocument();
    });

    it("renders each service level with its attainment, and breaches sort first", () => {
        render(<OpsPage rows={rows} registry={[]} slos={slos} dark={false} />);
        expect(screen.getByText("Service levels")).toBeInTheDocument();
        // Identifiers are humanised, never rendered raw.
        expect(screen.getByText("Holdings agreement")).toBeInTheDocument();
        expect(screen.getByText("Cross field consistency")).toBeInTheDocument();
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
