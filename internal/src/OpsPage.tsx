import type { CdeRegistryRow, DqMetricRow, SloAttainmentRow } from "./types";
import { useState } from "react";
import { dqMetricLabel, longDate, percent, sloLabel, summarise } from "./format";
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
    // Every accuracy metric used to get a tile, and the Service levels table
    // below then restated most of them — with a *different* number, because a
    // tile counted attainment over all history while the table counts it over
    // the window the SLO declares. Eight of nine tiles were duplicates saying
    // 35% next to 45.5% about the same metric, which is the "two correct
    // figures answering different questions" shape this estate keeps meeting.
    //
    // The rule now: **a tile says what is true now; the table says whether we
    // are meeting what we promised.** So a metric a service level already
    // covers has no tile, and one no service level covers does.
    const measuredBySlo = new Set(slos.map((s) => s.measuredBy));
    const allAccuracyMetrics = [...new Set(accuracy.map((r) => r.metric))];
    // If the service levels failed to load, show every metric rather than
    // none: a page that silently hides quality information because a second
    // request failed is worse than one that briefly repeats itself.
    const accuracyMetrics =
        slos.length === 0
            ? allAccuracyMetrics
            : allAccuracyMetrics.filter((m) => !measuredBySlo.has(m));
    // Same rule as the accuracy tiles (D-083): a figure stated elsewhere on
    // the page does not get a tile of its own. `critical_element_count` is
    // already inside "34 of 36", and `control_gap_count` is the heading of the
    // work list immediately below.
    const governanceRestated = new Set(["critical_element_count", "control_gap_count"]);
    const governance = rows.filter(
        (r) => r.dimension === "governance" && !governanceRestated.has(r.metric),
    );
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

    const pipelineTiles = [
        freshness ? (
            <Tile
                key="freshness"
                label="Freshness"
                value={`${freshness.value.toFixed(0)}d behind`}
                sub={freshness.detail}
                ok={freshness.passed}
            />
        ) : null,
        completeness ? (
            <Tile
                key="completeness"
                label="Completeness"
                value={percent(completeness.value, 0)}
                sub={`${longDate(completeness.asOf)} — ${completeness.detail}`}
                ok={completeness.passed}
            />
        ) : null,
        ...accuracyMetrics.map((metric) => {
            const series = accuracy.filter((r) => r.metric === metric);
            // These tiles render SLA *attainment* — the share of days the
            // metric passed — under a label that names the metric. That reads
            // correctly over a long series and lies over a short one: a metric
            // published as a single as-of-now row renders 0% or 100% directly
            // beneath a label naming a rate, and those are different numbers.
            // Below the threshold, show the metric's own latest value instead,
            // which is the same honesty the Service levels table applies one
            // section down.
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
        }),
    ].filter(Boolean);

    const governanceTiles = governance.map((r) => (
        <Tile
            key={r.metric}
            label={dqMetricLabel(r.metric)}
            value={r.metric.endsWith("_rate") ? percent(r.value, 0) : r.value.toFixed(0)}
            sub={r.detail}
            ok={r.passed}
        />
    ));

    if (rows.length === 0) {
        return <div className="center-state">No DQ metrics recorded yet.</div>;
    }

    return (
        <>
            <div className="client-header">
                <div>
                    <h1>Data Operations</h1>
                    <div className="asof">
                        Pipeline-wide — not scoped to one firm. These are current facts; whether the
                        estate is meeting what it promised is below.
                    </div>
                </div>
            </div>

            {/* One strip, two named groups. Merging the governance tiles in
                here was right -- they are current facts like the rest -- but it
                cost them their label, and "register coverage" reading as a
                pipeline statistic undersells what it is. A group heading is
                cheaper than a second strip and keeps the row scannable. */}
            {governanceTiles.length > 0 ? (
                <div className="tile-groups" style={{ marginBottom: 18 }}>
                    <section className="tile-group" style={{ flexGrow: pipelineTiles.length }}>
                        <div className="group-label">Pipeline</div>
                        <div className="grid tiles">{pipelineTiles}</div>
                    </section>
                    <section className="tile-group" style={{ flexGrow: governanceTiles.length }}>
                        <div className="group-label">Governance</div>
                        <div className="grid tiles">{governanceTiles}</div>
                    </section>
                </div>
            ) : (
                // No governance metrics: a lone "Pipeline" heading with nothing
                // to distinguish itself from is worse than no heading.
                <div className="grid tiles" style={{ marginBottom: 18 }}>
                    {pipelineTiles}
                </div>
            )}

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
                                        <td title={s.objective}>
                                            {sloLabel(s.slo)}{" "}
                                            <span className="asof">{summarise(s.objective)}</span>
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

            {gaps.length > 0 && (
                <>
                    <div className="client-header" style={{ marginTop: 26 }}>
                        <div>
                            <h1>Governance — {gaps.length} uncovered</h1>
                            <div className="asof">
                                Critical elements with no automated control, as of the last register
                                rebuild. Each carries a written statement of what is missing —
                                recorded rather than papered over. This is the work list.
                            </div>
                        </div>
                    </div>

                    <div className="card" style={{ marginBottom: 18 }}>
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
                                        <td>
                                            <ExpandableText text={g.controlGap} />
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
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

/** A long statement, scannable by default and complete on request.
 *
 *  The control gaps are the most important prose on this page and the least
 *  suited to a table cell: each runs to a paragraph, and three of them stacked
 *  turn the work list into a wall. Truncated they can be scanned; expanded
 *  they say everything. Same move as the reconcile badge on the client
 *  dashboard (D-065) — a verdict you can open, rather than a verdict with its
 *  evidence permanently in the way. */
function ExpandableText({ text, limit = 130 }: { text: string; limit?: number }) {
    const [open, setOpen] = useState(false);
    if (text.length <= limit) return <>{text}</>;
    return (
        <>
            {open ? text : `${text.slice(0, limit).trimEnd()}…`}{" "}
            <button type="button" className="linklike" onClick={() => setOpen(!open)}>
                {open ? "less" : "more"}
            </button>
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
