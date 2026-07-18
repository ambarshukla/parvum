// Categorical palette from the data-viz reference instance, in its validated
// fixed order (the ordering is the CVD-safety mechanism, not cosmetic). Two
// selected sets: the dark set is the same hues stepped for the dark surface.
const CATEGORICAL_LIGHT = [
    "#2a78d6", // blue
    "#008300", // green
    "#e87ba4", // magenta
    "#eda100", // yellow
    "#1baf7a", // aqua
    "#eb6834", // orange
    "#4a3aa7", // violet
    "#e34948", // red
];

const CATEGORICAL_DARK = [
    "#3987e5",
    "#008300",
    "#d55181",
    "#c98500",
    "#199e70",
    "#d95926",
    "#9085e9",
    "#e66767",
];

export function categorical(dark: boolean): string[] {
    return dark ? CATEGORICAL_DARK : CATEGORICAL_LIGHT;
}

// Color follows the entity, never its rank: an asset class keeps its hue across
// clients and across renders. Known classes take fixed slots; anything else is
// assigned deterministically by name so it is at least stable within a view.
const ASSET_CLASS_SLOT: Record<string, number> = {
    Equity: 0,
    "Fixed Income": 1,
    Cash: 4,
    Alternatives: 6,
    Unknown: 7,
};

export function assetClassColor(assetClass: string, dark: boolean, fallbackIndex: number): string {
    const colors = categorical(dark);
    const slot = ASSET_CLASS_SLOT[assetClass] ?? fallbackIndex % colors.length;
    return colors[slot] ?? colors[0]!;
}

// Income types get two fixed, well-separated slots (blue, green).
export function incomeTypeColor(type: string, dark: boolean): string {
    const colors = categorical(dark);
    return type === "DIVIDEND" ? colors[0]! : colors[1]!;
}
