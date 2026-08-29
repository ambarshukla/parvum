import type { CdeRegistryRow, DqMetricRow, SloAttainmentRow } from "./types";
import { dqMetricLabel, longDate, percent, sloLabel } from "./format";
import { AccuracyTrendChart, ExceptionsChart } from "./components/Charts";

/** Below this many days, attainment is not a service level and is not shown
 *  as one. Mirrors MIN_DAYS_FOR_VERDICT in spark/gold_reports.py, which makes
 *  the same call for dq_slo_attainment.meets_objective. */
const MIN_DAYS_FOR_ATTAINMENT = 7;

interface Props {
    rows: DqMetricRow[];
    registry: CdeRegistryRow[];
    slos: SloAttainmentRow[];
    dark: boolean;
}

/** The pipeline-wide operations view: not scoped to any one firm's clients
 *  (see V4__dq_metrics.sql) — freshness, completeness, accuracy, and
 *  exceptions for the whole platform, over time. */
export function OpsPage({ rows, registry, slos, dark }: Props) {
    const freshness = rows.find((r) => r.dimension === "freshness");
    const completeness = [...rows.filter((r) => r.dimension === "completeness")].sort((a, b) =>
        b.asOf.localeCompare(a.asOf),
    )[0];
    const accuracy = rows.filter((r) => r.dimension === "accuracy");
    const exceptions = rows.filter((r) => r.dimension === "exceptions");
    const accuracyMetrics = [...new Set(accuracy.map((r) => r.metric))];
    const governance = rows.filter((r) => r.dimension === "governance");
    // The interesting artefact is not the coverage percentage but the named
    // gaps behind it: critical elements nobody has a control for. A stated
    // gap is a work item; an unstated one is a surprise.
    const gaps = registry
        .filter((r) => r.tier === "critical" && r.qualityRuleCount === 0 && r.controlGap)
        .sort((a, b) =>
            `${a.tableName}.${a.columnName}`.localeCompare(`${b.tableName}.${b.columnName}`),
        );
    // Gaps are written per column but caused per root. Four of the five below
    // share one alts paragraph word for word, and repeating it four times
    // reads as a glitch rather than as one problem with four symptoms. Group
    // on the statement itself: same words, same cause.
    const gapGroups = [
        ...gaps
            .reduce((acc, r) => {
                const existing = acc.get(r.controlGap!);
                if (existing) {
                    existing.elements.push(r);
                    if (!existing.owners.includes(r.owner!)) existing.owners.push(r.owner!);
                } else {
                    acc.set(r.controlGap!, {
                        controlGap: r.controlGap!,
                        owners: [r.owner!],
                        elements: [r],
                    });
                }
                return acc;
            }, new Map<string, { controlGap: string; owners: string[]; elements: typeof gaps }>())
            .values(),
    ];

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
                    // These tiles render SLA *attainment* — the share of days
                    // the metric passed — under a label that names the metric.
                    // That reads correctly over a long series and lies over a
                    // short one: a metric published as a single as-of-now row
                    // renders 0% or 100% directly beneath a label naming a
                    // rate, and those are different numbers. Below the
                    // threshold, show the metric's own latest value instead,
                    // which is the same honesty the Service levels table
                    // applies one section down.
                    const latest = [...series].sort((a, b) => b.asOf.localeCompare(a.asOf))[0];
                    if (latest && series.length < MIN_DAYS_FOR_ATTAINMENT) {
                        return (
                            <Tile
                                key={metric}
                                label={dqMetricLabel(metric)}
                                value={percent(latest.value, 0)}
                                sub={`${longDate(latest.asOf)} — ${latest.detail}`}
                                ok={latest.passed}
                            />
                        );
                    }
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

            {slos.length > 0 && (
                <>
                    <div className="client-header" style={{ marginTop: 26 }}>
                        <div>
                            <h1>Service levels</h1>
                            <div className="asof">
                                What the estate is held to, and whether it is meeting it. Breaches
                                first — a met objective needs no attention.
                            </div>
                        </div>
                    </div>

                    <div className="card" style={{ marginBottom: 18 }}>
                        <table className="data">
                            <thead>
                                <tr>
                                    <th>Service level</th>
                                    <th>Objective</th>
                                    <th className="num">Attainment</th>
                                    <th className="num">Window</th>
                                    <th>Error budget</th>
                                    <th>Status</th>
                                </tr>
                            </thead>
                            <tbody>
                                {slos.map((s) => (
                                    <tr key={s.slo}>
                                        <td>
                                            <div>{sloLabel(s.slo)}</div>
                                            <div className="asof">{s.objective}</div>
                                        </td>
                                        <td>{s.target}</td>
                                        <td className="num">
                                            {percent(s.attainment, 1)}
                                            <div className="asof">
                                                target {percent(s.attainmentObjective, 0)}
                                            </div>
                                        </td>
                                        <td className="num">
                                            {s.daysMet}/{s.daysMeasured} days
                                            <div className="asof">{s.windowDays}d window</div>
                                        </td>
                                        <td>{budgetText(s)}</td>
                                        <td>
                                            <span className={`badge ${sloBadge(s)}`}>
                                                {sloStatus(s)}
                                            </span>
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                </>
            )}

            {governance.length > 0 && (
                <>
                    <div className="client-header" style={{ marginTop: 26 }}>
                        <div>
                            <h1>Governance</h1>
                            <div className="asof">
                                The register, as of the last rebuild — a fact about the estate now,
                                not about a business day
                            </div>
                        </div>
                    </div>

                    <div className="grid tiles" style={{ marginBottom: 18 }}>
                        {governance.map((r) => (
                            <Tile
                                key={r.metric}
                                label={dqMetricLabel(r.metric)}
                                value={
                                    r.metric.endsWith("_rate")
                                        ? percent(r.value, 0)
                                        : r.value.toFixed(0)
                                }
                                sub={r.detail}
                                ok={r.passed}
                            />
                        ))}
                    </div>

                    {gaps.length > 0 && (
                        <div className="card" style={{ marginBottom: 18 }}>
                            <h2>Critical elements with no automated control ({gaps.length})</h2>
                            <div className="asof" style={{ marginBottom: 10 }}>
                                Each of these is classified critical and carries a written statement
                                of what is missing. Recorded rather than papered over — this is the
                                work list.
                            </div>
                            <table className="data">
                                <thead>
                                    <tr>
                                        <th>Element{gaps.length > gapGroups.length ? "s" : ""}</th>
                                        <th>Owner</th>
                                        <th>What is missing</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {gapGroups.map((g) => (
                                        <tr key={g.controlGap}>
                                            <td>
                                                {g.elements.map((r) => (
                                                    <div key={`${r.tableName}.${r.columnName}`}>
                                                        <code>
                                                            {r.tableName}.{r.columnName}
                                                        </code>
                                                    </div>
                                                ))}
                                            </td>
                                            <td>{g.owners.join(", ")}</td>
                                            <td>{g.controlGap}</td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    )}
                </>
            )}

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

/** Three states, not two. An SLO with too little history to judge is neither
 *  met nor breached, and saying "met" there would be the exact false green a
 *  service level exists to prevent. */
function sloStatus(s: SloAttainmentRow): string {
    if (s.insufficientHistory || s.meetsObjective === null) return "Not enough history";
    return s.meetsObjective ? "Met" : "Breached";
}

/** Grey, not amber, for "not enough history": it is an absence of evidence,
 *  not a warning about the estate, and colouring it as a problem would train
 *  people to ignore the colour that means one. */
function sloBadge(s: SloAttainmentRow): string {
    if (s.insufficientHistory || s.meetsObjective === null) return "neutral";
    return s.meetsObjective ? "ok" : "warn";
}

/** An objective of 1.0 has no error budget at all, so there is nothing to
 *  report as spent — say that rather than rendering a misleading 0% or 100%. */
function budgetText(s: SloAttainmentRow): string {
    if (s.errorBudgetDays === 0) return "None — objective is total";
    const remaining = s.budgetRemainingPct;
    const spent = `${s.budgetConsumedDays} of ${s.errorBudgetDays} days spent`;
    if (remaining === null) return spent;
    return remaining < 0 ? `${spent} — over budget` : `${spent} — ${percent(remaining, 0)} left`;
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
