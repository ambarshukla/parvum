import {
    Bar,
    BarChart,
    CartesianGrid,
    Line,
    LineChart,
    ResponsiveContainer,
    Tooltip,
    XAxis,
    YAxis,
} from "recharts";
import type { DqMetricRow } from "../types";
import { categorical } from "../palette";
import { dqMetricLabel, longDate, percent } from "../format";

const MUTED = "#898781"; // axis/label ink — mode-invariant in the reference palette

function chrome(dark: boolean) {
    return { grid: dark ? "#2c2c2a" : "#e1e0d9", axis: dark ? "#383835" : "#c3c2b7" };
}

interface DqTrendProps {
    /** Pre-filtered to one dimension by the caller (e.g. only 'accuracy' rows). */
    rows: DqMetricRow[];
    dark: boolean;
}

/** Long rows (one per date × metric) → one row per date, one column per
 *  metric — what recharts' multi-line/stacked-bar charts actually want. */
function pivotByAsOf(rows: DqMetricRow[]): Record<string, number | string>[] {
    const byDate = new Map<string, Record<string, number | string>>();
    for (const row of rows) {
        const bucket = byDate.get(row.asOf) ?? { asOf: row.asOf };
        bucket[row.metric] = row.value;
        byDate.set(row.asOf, bucket);
    }
    return [...byDate.values()].sort((a, b) => (a.asOf as string).localeCompare(b.asOf as string));
}

/** Accuracy rates over time — one line per metric. Metric order (and so
 *  color) follows the API's own ORDER BY dimension, metric, as_of, which is
 *  stable across renders. */
export function AccuracyTrendChart({ rows, dark }: DqTrendProps) {
    const data = pivotByAsOf(rows);
    const metrics = [...new Set(rows.map((r) => r.metric))];
    const { grid, axis } = chrome(dark);
    const colors = categorical(dark);

    if (data.length === 0) {
        return <p className="muted">No accuracy history recorded.</p>;
    }

    return (
        <div>
            <ResponsiveContainer width="100%" height={260}>
                <LineChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 8 }}>
                    <CartesianGrid stroke={grid} vertical={false} />
                    <XAxis
                        dataKey="asOf"
                        tickFormatter={longDate}
                        tick={{ fill: MUTED, fontSize: 12 }}
                        stroke={axis}
                        tickLine={false}
                        minTickGap={40}
                    />
                    <YAxis
                        domain={[0, 1]}
                        tickFormatter={(v: number) => percent(v, 0)}
                        tick={{ fill: MUTED, fontSize: 12 }}
                        stroke={axis}
                        tickLine={false}
                        width={44}
                    />
                    <Tooltip
                        formatter={(value: number, name: string) => [
                            percent(value, 1),
                            dqMetricLabel(name),
                        ]}
                        labelFormatter={(label: string) => longDate(label)}
                        contentStyle={{ fontSize: 13 }}
                    />
                    {metrics.map((m, i) => (
                        <Line
                            key={m}
                            type="monotone"
                            dataKey={m}
                            stroke={colors[i % colors.length]}
                            strokeWidth={2}
                            dot={false}
                            isAnimationActive={false}
                        />
                    ))}
                </LineChart>
            </ResponsiveContainer>
            <div className="legend">
                {metrics.map((m, i) => (
                    <div className="item" key={m}>
                        <span
                            className="swatch"
                            style={{ background: colors[i % colors.length] }}
                        />
                        {dqMetricLabel(m)}
                    </div>
                ))}
            </div>
        </div>
    );
}

/** Exception counts over time — one stacked bar per metric, so a bad day's
 *  total height and its composition are both visible at once. */
export function ExceptionsChart({ rows, dark }: DqTrendProps) {
    const data = pivotByAsOf(rows);
    const metrics = [...new Set(rows.map((r) => r.metric))];
    const { grid, axis } = chrome(dark);
    const colors = categorical(dark);

    if (data.length === 0) {
        return <p className="muted">No exceptions recorded.</p>;
    }

    return (
        <div>
            <ResponsiveContainer width="100%" height={260}>
                <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 8 }}>
                    <CartesianGrid stroke={grid} vertical={false} />
                    <XAxis
                        dataKey="asOf"
                        tickFormatter={longDate}
                        tick={{ fill: MUTED, fontSize: 12 }}
                        stroke={axis}
                        tickLine={false}
                        minTickGap={40}
                    />
                    <YAxis
                        allowDecimals={false}
                        tick={{ fill: MUTED, fontSize: 12 }}
                        stroke={axis}
                        tickLine={false}
                        width={30}
                    />
                    <Tooltip
                        formatter={(value: number, name: string) => [value, dqMetricLabel(name)]}
                        labelFormatter={(label: string) => longDate(label)}
                        contentStyle={{ fontSize: 13 }}
                    />
                    {metrics.map((m, i) => (
                        <Bar
                            key={m}
                            dataKey={m}
                            stackId="exceptions"
                            fill={colors[i % colors.length]}
                            isAnimationActive={false}
                        />
                    ))}
                </BarChart>
            </ResponsiveContainer>
            <div className="legend">
                {metrics.map((m, i) => (
                    <div className="item" key={m}>
                        <span
                            className="swatch"
                            style={{ background: colors[i % colors.length] }}
                        />
                        {dqMetricLabel(m)}
                    </div>
                ))}
            </div>
        </div>
    );
}
