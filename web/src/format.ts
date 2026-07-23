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

/** A ratio like MOIC as "1.44x" — the private-markets convention. */
export function multiple(value: number): string {
    return `${value.toFixed(2)}x`;
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
