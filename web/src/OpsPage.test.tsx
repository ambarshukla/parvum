import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { OpsPage } from "./OpsPage";
import type { DqMetricRow } from "./types";

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

describe("OpsPage", () => {
    it("shows the freshness and completeness tiles, and per-metric SLA attainment", () => {
        render(<OpsPage rows={rows} dark={false} />);
        expect(screen.getByText("Data Operations")).toBeInTheDocument();
        expect(screen.getByText("1d behind")).toBeInTheDocument();
        expect(screen.getByText("100%")).toBeInTheDocument(); // completeness, latest day
        // Cross-format match: 1 of 2 days passed = 50%. The label also shows
        // up in the chart legend, so there are two matches by design.
        expect(screen.getAllByText("Cross-format match").length).toBeGreaterThanOrEqual(1);
        expect(screen.getByText("50%")).toBeInTheDocument();
        expect(screen.getByText("SLA attained 1 of 2 days")).toBeInTheDocument();
    });

    it("shows a placeholder when there is no DQ data yet", () => {
        render(<OpsPage rows={[]} dark={false} />);
        expect(screen.getByText("No DQ metrics recorded yet.")).toBeInTheDocument();
    });
});
