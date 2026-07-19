import type { DqMetricRow } from "./types";
import { dqMetricLabel, longDate, percent } from "./format";
import { AccuracyTrendChart, ExceptionsChart } from "./components/Charts";

interface Props {
    rows: DqMetricRow[];
    dark: boolean;
}

/** The pipeline-wide operations view: not scoped to any one firm's clients
 *  (see V4__dq_metrics.sql) — freshness, completeness, accuracy, and
 *  exceptions for the whole platform, over time. */
export function OpsPage({ rows, dark }: Props) {
    const freshness = rows.find((r) => r.dimension === "freshness");
    const completeness = [...rows.filter((r) => r.dimension === "completeness")].sort((a, b) =>
        b.asOf.localeCompare(a.asOf),
    )[0];
    const accuracy = rows.filter((r) => r.dimension === "accuracy");
    const exceptions = rows.filter((r) => r.dimension === "exceptions");
    const accuracyMetrics = [...new Set(accuracy.map((r) => r.metric))];

    if (rows.length === 0) {
        return <div className="center-state">No DQ metrics recorded yet.</div>;
    }

    return (
        <>
            <div className="client-header">
                <div>
                    <h1>Data Operations</h1>
                    <div className="asof">Pipeline-wide — not scoped to one firm</div>
                </div>
            </div>

            <div className="grid tiles" style={{ marginBottom: 18 }}>
                {freshness && (
                    <Tile
                        label="Freshness"
                        value={`${freshness.value.toFixed(0)}d behind`}
                        sub={freshness.detail}
                        ok={freshness.passed}
                    />
                )}
                {completeness && (
                    <Tile
                        label="Completeness"
                        value={percent(completeness.value, 0)}
                        sub={`${longDate(completeness.asOf)} — ${completeness.detail}`}
                        ok={completeness.passed}
                    />
                )}
                {accuracyMetrics.map((metric) => {
                    const series = accuracy.filter((r) => r.metric === metric);
                    const attained = series.filter((r) => r.passed).length;
                    return (
                        <Tile
                            key={metric}
                            label={dqMetricLabel(metric)}
                            value={percent(attained / series.length, 0)}
                            sub={`SLA attained ${attained} of ${series.length} days`}
                            ok={attained === series.length}
                        />
                    );
                })}
            </div>

            <div className="grid cols-2">
                <div className="card">
                    <h2>Accuracy trend</h2>
                    <AccuracyTrendChart rows={accuracy} dark={dark} />
                </div>
                <div className="card">
                    <h2>Exceptions per day</h2>
                    <ExceptionsChart rows={exceptions} dark={dark} />
                </div>
            </div>
        </>
    );
}

function Tile({
    label,
    value,
    sub,
    ok,
}: {
    label: string;
    value: string;
    sub?: string;
    ok: boolean | null;
}) {
    return (
        <div className="card tile">
            <div className="label">{label}</div>
            <div className="value">{value}</div>
            {ok !== null && (
                <span className={`badge ${ok ? "ok" : "warn"}`} style={{ marginTop: 6 }}>
                    <span className="dot" />
                    {ok ? "Within SLA" : "Breached"}
                </span>
            )}
            {sub && <div className="asof">{sub}</div>}
        </div>
    );
}
