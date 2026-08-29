import { describe, expect, it } from "vitest";

import { dqMetricLabel, sloLabel } from "./format";

describe("dqMetricLabel", () => {
    it("prefers the curated label where there is one", () => {
        // The reason the map exists: a mechanical humanisation of this name
        // would read "Holdings cross format match rate", which is worse.
        expect(dqMetricLabel("holdings_cross_format_match_rate")).toBe("Cross-format match");
        expect(dqMetricLabel("cash_conformed_consistency_rate")).toBe("Cash consistency");
        expect(dqMetricLabel("critical_control_coverage_rate")).toBe("Critical elements tested");
    });

    it("names every metric the gold job appends (D-070, D-073)", () => {
        // These four shipped to production unlabelled, rendering as raw
        // snake_case beside properly-named neighbours, because nothing
        // connects adding a metric in Spark to naming it here.
        expect(dqMetricLabel("daily_return_plausibility_rate")).toBe("Return plausibility");
        expect(dqMetricLabel("return_plausibility_breaks_count")).toBe("Plausibility breaks");
        expect(dqMetricLabel("cross_field_invariant_rate")).toBe("Cross-field invariants");
        expect(dqMetricLabel("cross_field_invariant_breaks_count")).toBe("Invariant breaks");
    });

    it("humanises an unknown metric instead of surrendering to snake_case", () => {
        // dq_metrics is open by design, so the next unnamed metric is a matter
        // of time. It should look like a blemish, not a seam.
        expect(dqMetricLabel("some_future_metric_rate")).toBe("Some future metric rate");
    });

    it("never renders an underscore, whatever it is given", () => {
        for (const metric of ["a_b_c", "already Fine", "single", "trailing_"]) {
            expect(dqMetricLabel(metric)).not.toContain("_");
        }
    });
});

describe("sloLabel", () => {
    it("uses the curated label, including acronym casing the fallback cannot infer", () => {
        expect(sloLabel("fx_integrity")).toBe("FX integrity");
        expect(sloLabel("cash_ledger_integrity")).toBe("Cash ledger integrity");
    });

    it("does not surface a medallion layer name to an ops reader", () => {
        // `gold_freshness` is the register's identifier; "gold" is the
        // pipeline's vocabulary, not the reader's.
        expect(sloLabel("gold_freshness")).toBe("Data freshness");
    });

    it("humanises an unknown service level rather than rendering the identifier", () => {
        expect(sloLabel("some_new_promise")).toBe("Some new promise");
        expect(sloLabel("some_new_promise")).not.toContain("_");
    });
});

describe("dqMetricLabel — the metrics added after the last labelling miss", () => {
    it("names every metric the pipeline currently publishes", () => {
        expect(dqMetricLabel("alts_cross_document_valid_rate")).toBe("Alts document validity");
        expect(dqMetricLabel("alts_documents_unconfirmed_count")).toBe("Alts awaiting review");
        expect(dqMetricLabel("fx_rate_plausibility_rate")).toBe("FX rate plausibility");
        expect(dqMetricLabel("fx_rate_stale_days_count")).toBe("FX stale days");
    });
});
