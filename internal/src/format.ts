// Display formatters. Kept pure and separate so they can be unit-tested without
// rendering anything.

const USD = new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
});

/** Whole-dollar money, for headlines and table cells. */
export function money(value: number): string {
    return USD.format(value);
}

/** A 0..1 weight as a percentage; `digits` decimals (default 1). */
export function percent(weight: number, digits = 1): string {
    return `${(weight * 100).toFixed(digits)}%`;
}

/** ISO date (YYYY-MM-DD) → "17 Jul 2026". */
export function longDate(iso: string): string {
    const [y, m, d] = iso.split("-").map(Number);
    if (!y || !m || !d) return iso;
    const date = new Date(Date.UTC(y, m - 1, d));
    return date.toLocaleDateString("en-GB", {
        day: "2-digit",
        month: "short",
        year: "numeric",
        timeZone: "UTC",
    });
}

/** ISO month (first-of-month) → "Jul 2026". */
export function monthLabel(iso: string): string {
    const [y, m] = iso.split("-").map(Number);
    if (!y || !m) return iso;
    const date = new Date(Date.UTC(y, m - 1, 1));
    return date.toLocaleDateString("en-GB", {
        month: "short",
        year: "numeric",
        timeZone: "UTC",
    });
}

// dq_metrics' `metric` names are the SQL rollup's own identifiers
// (spark/dq_recon.py) — stable, but not written for a screen. One label per
// known metric; anything new falls back to the raw name rather than hiding.
const DQ_METRIC_LABELS: Record<string, string> = {
    files_landed_rate: "Files landed",
    holdings_cross_format_match_rate: "Cross-format match",
    cash_conformed_consistency_rate: "Cash consistency",
    cash_day_over_day_continuity_rate: "Day-over-day continuity",
    holdings_findings_count: "Cross-format findings",
    cash_integrity_breaks_count: "Cash integrity breaks",
    cash_continuity_breaks_count: "Continuity breaks",
    bronze_days_behind: "Bronze days behind",
    columns_classified_rate: "Register coverage",
    critical_control_coverage_rate: "Critical elements tested",
    critical_element_count: "Critical elements",
    control_gap_count: "Stated control gaps",
    daily_return_plausibility_rate: "Return plausibility",
    return_plausibility_breaks_count: "Plausibility breaks",
    cross_field_invariant_rate: "Cross-field invariants",
    cross_field_invariant_breaks_count: "Invariant breaks",
    alts_cross_document_valid_rate: "Alts document validity",
    alts_documents_unconfirmed_count: "Alts awaiting review",
    fx_rate_plausibility_rate: "FX rate plausibility",
    fx_rate_stale_days_count: "FX stale days",
    registry_snapshot_stale_days: "Register snapshot age",
};

// The register's SLO names, same problem and same treatment. The humanising
// fallback below cannot capitalise an acronym, so `fx_integrity` reads "Fx
// integrity" without an entry here — which is how it shipped, and is why the
// governance gate now refuses a service level nobody has named.
const SLO_LABELS: Record<string, string> = {
    feed_completeness: "Feed completeness",
    // Not "Gold freshness": `gold` is a medallion layer, which is the
    // pipeline's vocabulary and not the reader's.
    gold_freshness: "Data freshness",
    holdings_agreement: "Holdings agreement",
    cash_ledger_integrity: "Cash ledger integrity",
    cash_continuity: "Cash continuity",
    cross_field_consistency: "Cross-field consistency",
    return_plausibility: "Return plausibility",
    fx_integrity: "FX integrity",
};

/** A dq_metrics `metric` identifier → its display label.
 *
 * `dq_metrics` is deliberately open: adding a check means adding one more
 * `SELECT` to a `UNION ALL`, with nothing forcing anyone to come here and
 * name it. That is a good property for the pipeline and a bad one for this
 * page, and it has already bitten twice — the D-070 and D-073 metrics both
 * shipped to production shouting `CROSS_FIELD_INVARIANT_RATE` at a reader
 * beside neighbours reading "Cash consistency".
 *
 * So the fallback humanises rather than surrendering. An unnamed metric still
 * reads as a phrase, which makes forgetting a label a cosmetic blemish
 * instead of a visible seam. Explicit entries above remain preferred: they
 * are what let "holdings_cross_format_match_rate" read as "Cross-format
 * match" rather than "Holdings cross format match rate".
 */
export function dqMetricLabel(metric: string): string {
    return DQ_METRIC_LABELS[metric] ?? humanise(metric);
}

/** A service level's identifier → its display label. Same contract as
 *  `dqMetricLabel`, for the same reason: the register names SLOs for the gate,
 *  not for a screen. */
export function sloLabel(slo: string): string {
    return SLO_LABELS[slo] ?? humanise(slo);
}

/** Last resort, not a substitute for a curated label. It cannot know that
 *  `fx` is an acronym or that `gold` is a layer name rather than a quality —
 *  which is exactly why the gate requires the curated entry. */
function humanise(identifier: string): string {
    const words = identifier.replace(/_/g, " ").trim();
    return words.charAt(0).toUpperCase() + words.slice(1);
}

/** The first sentence, capped, for a table cell that must stay one line high.
 *
 * The register's objectives are written to be read in a YAML file, where two
 * sentences and 200 characters are fine. Rendered verbatim in a table they
 * doubled every row's height and turned the Service levels block into a third
 * of the page. The full text is still there — the cell carries it as a title —
 * but what a reader scans for is which promise is breached, not its prose.
 */
export function summarise(text: string, max = 110): string {
    const [first] = text.trim().split(/(?<=\.)\s+/);
    const sentence = first ?? text.trim();
    if (sentence.length <= max) return sentence;
    const cut = sentence.slice(0, max);
    const boundary = cut.lastIndexOf(" ");
    return `${(boundary > 40 ? cut.slice(0, boundary) : cut).replace(/[,;:]$/, "")}…`;
}
