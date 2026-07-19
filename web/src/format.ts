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
};

/** A dq_metrics `metric` identifier → its display label. */
export function dqMetricLabel(metric: string): string {
    return DQ_METRIC_LABELS[metric] ?? metric;
}
