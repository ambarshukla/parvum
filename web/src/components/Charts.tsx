import {
    Bar,
    BarChart,
    CartesianGrid,
    Cell,
    Pie,
    PieChart,
    ResponsiveContainer,
    Tooltip,
    XAxis,
    YAxis,
} from "recharts";
import type { AllocationRow, IncomeRow } from "../types";
import { assetClassColor, incomeTypeColor } from "../palette";
import { money, monthLabel, percent } from "../format";

const MUTED = "#898781"; // axis/label ink — mode-invariant in the reference palette

function chrome(dark: boolean) {
    return { grid: dark ? "#2c2c2a" : "#e1e0d9", axis: dark ? "#383835" : "#c3c2b7" };
}

interface DonutProps {
    rows: AllocationRow[];
    dark: boolean;
}

/** Asset allocation as a donut. Legend + direct labels are the secondary
 *  encoding, so identity never rests on color alone. */
export function AllocationDonut({ rows, dark }: DonutProps) {
    const data = [...rows].sort((a, b) => b.valueUsd - a.valueUsd);
    const colorFor = (assetClass: string, index: number) =>
        assetClassColor(assetClass, dark, index);

    return (
        <div>
            <ResponsiveContainer width="100%" height={240}>
                <PieChart>
                    <Pie
                        data={data}
                        dataKey="valueUsd"
                        nameKey="assetClass"
                        innerRadius={62}
                        outerRadius={95}
                        paddingAngle={2}
                        stroke="var(--surface)"
                        strokeWidth={2}
                        isAnimationActive={false}
                    >
                        {data.map((row, i) => (
                            <Cell key={row.assetClass} fill={colorFor(row.assetClass, i)} />
                        ))}
                    </Pie>
                    <Tooltip
                        formatter={(value: number, name: string) => [money(value), name]}
                        contentStyle={{ fontSize: 13 }}
                    />
                </PieChart>
            </ResponsiveContainer>
            <div className="legend">
                {data.map((row, i) => (
                    <div className="item" key={row.assetClass}>
                        <span
                            className="swatch"
                            style={{ background: colorFor(row.assetClass, i) }}
                        />
                        {row.assetClass} <span className="muted">{percent(row.weight)}</span>
                    </div>
                ))}
            </div>
        </div>
    );
}

interface IncomeProps {
    rows: IncomeRow[];
    dark: boolean;
}

interface MonthBucket {
    month: string;
    DIVIDEND: number;
    INTEREST: number;
}

/** Monthly income, dividends and interest stacked per month. */
export function IncomeChart({ rows, dark }: IncomeProps) {
    const byMonth = new Map<string, MonthBucket>();
    for (const row of rows) {
        const bucket = byMonth.get(row.month) ?? { month: row.month, DIVIDEND: 0, INTEREST: 0 };
        bucket[row.type] += row.incomeUsd;
        byMonth.set(row.month, bucket);
    }
    const data = [...byMonth.values()].sort((a, b) => a.month.localeCompare(b.month));
    const { grid, axis } = chrome(dark);

    if (data.length === 0) {
        return <p className="muted">No income recorded.</p>;
    }

    return (
        <div>
            <ResponsiveContainer width="100%" height={260}>
                <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 8 }}>
                    <CartesianGrid stroke={grid} vertical={false} />
                    <XAxis
                        dataKey="month"
                        tickFormatter={monthLabel}
                        tick={{ fill: MUTED, fontSize: 12 }}
                        stroke={axis}
                        tickLine={false}
                    />
                    <YAxis
                        tickFormatter={(v: number) => money(v)}
                        tick={{ fill: MUTED, fontSize: 12 }}
                        stroke={axis}
                        tickLine={false}
                        width={70}
                    />
                    <Tooltip
                        cursor={{ fill: "rgba(128,128,128,0.08)" }}
                        formatter={(value: number, name: string) => [money(value), name]}
                        labelFormatter={(label: string) => monthLabel(label)}
                        contentStyle={{ fontSize: 13 }}
                    />
                    <Bar
                        dataKey="DIVIDEND"
                        stackId="income"
                        fill={incomeTypeColor("DIVIDEND", dark)}
                        isAnimationActive={false}
                    />
                    <Bar
                        dataKey="INTEREST"
                        stackId="income"
                        fill={incomeTypeColor("INTEREST", dark)}
                        radius={[3, 3, 0, 0]}
                        isAnimationActive={false}
                    />
                </BarChart>
            </ResponsiveContainer>
            <div className="legend">
                <div className="item">
                    <span
                        className="swatch"
                        style={{ background: incomeTypeColor("DIVIDEND", dark) }}
                    />
                    Dividends
                </div>
                <div className="item">
                    <span
                        className="swatch"
                        style={{ background: incomeTypeColor("INTEREST", dark) }}
                    />
                    Interest
                </div>
            </div>
        </div>
    );
}
