import { useState } from "react";
import type { TenantData, WealthRow } from "./types";
import { money, longDate, monthLabel, multiple, percent } from "./format";
import { AllocationDonut, IncomeChart, PerformanceChart } from "./components/Charts";

const TABS = [
    "Overview",
    "Allocation",
    "Income",
    "Holdings",
    "Ownership",
    "Performance",
    "Alternatives",
] as const;
type Tab = (typeof TABS)[number];

interface Props {
    data: TenantData;
    client: WealthRow;
    dark: boolean;
}

export function ClientDashboard({ data, client, dark }: Props) {
    const [tab, setTab] = useState<Tab>("Overview");

    const allocation = data.allocation.filter((r) => r.clientId === client.clientId);
    const income = data.income.filter((r) => r.clientId === client.clientId);
    const holdings = data.holdings
        .filter((r) => r.clientId === client.clientId)
        .sort((a, b) => a.rank - b.rank);
    const ownedAccounts = [
        ...new Set(
            data.ownership.filter((r) => r.clientId === client.clientId).map((r) => r.accountId),
        ),
    ].sort();
    const performance = data.performance
        .filter((r) => r.clientId === client.clientId)
        .sort((a, b) => a.asOf.localeCompare(b.asOf));
    const performanceSummary = data.performanceSummary.find((r) => r.clientId === client.clientId);
    const altsHoldings = data.altsHoldings
        .filter((r) => r.clientId === client.clientId)
        .sort((a, b) => a.fundName.localeCompare(b.fundName));

    return (
        <>
            <div className="client-header">
                <div>
                    <h1>{client.clientName}</h1>
                    <div className="asof">As of {longDate(client.asOf)}</div>
                </div>
                <ReconcileBadge ok={client.booksReconcile} />
            </div>

            <div className="tabs" role="tablist">
                {TABS.map((t) => (
                    <button
                        key={t}
                        role="tab"
                        aria-selected={tab === t}
                        className={`tab ${tab === t ? "active" : ""}`}
                        onClick={() => setTab(t)}
                    >
                        {t}
                    </button>
                ))}
            </div>

            {tab === "Overview" && (
                <>
                    <div className="grid tiles" style={{ marginBottom: 18 }}>
                        <Tile label="Total wealth" value={money(client.totalWealthUsd)} hero />
                        <Tile label="Positions" value={money(client.positionsUsd)} />
                        <Tile label="Cash" value={money(client.cashUsd)} />
                        <Tile label="Private markets" value={money(client.altsUsd)} />
                        <Tile
                            label="FX rate used"
                            value={client.fxRateUsed.toFixed(4)}
                            sub={`EUR/USD · ${longDate(client.fxRateDate)}`}
                        />
                    </div>
                    <div className="grid cols-2">
                        <div className="card">
                            <h2>Asset allocation</h2>
                            <AllocationDonut rows={allocation} dark={dark} />
                        </div>
                        <div className="card">
                            <h2>Monthly income</h2>
                            <IncomeChart rows={income} dark={dark} />
                        </div>
                    </div>
                </>
            )}

            {tab === "Allocation" && (
                <div className="grid cols-2">
                    <div className="card">
                        <h2>Breakdown</h2>
                        <AllocationDonut rows={allocation} dark={dark} />
                    </div>
                    <div className="card">
                        <h2>By asset class</h2>
                        <table className="data">
                            <thead>
                                <tr>
                                    <th>Asset class</th>
                                    <th className="num">Value</th>
                                    <th className="num">Weight</th>
                                </tr>
                            </thead>
                            <tbody>
                                {[...allocation]
                                    .sort((a, b) => b.valueUsd - a.valueUsd)
                                    .map((r) => (
                                        <tr key={r.assetClass}>
                                            <td>{r.assetClass}</td>
                                            <td className="num">{money(r.valueUsd)}</td>
                                            <td className="num">
                                                <div className="weight-cell">
                                                    <span className="mono">
                                                        {percent(r.weight)}
                                                    </span>
                                                    <span className="weight-bar">
                                                        <span
                                                            style={{
                                                                width: `${Math.min(r.weight * 100, 100)}%`,
                                                            }}
                                                        />
                                                    </span>
                                                </div>
                                            </td>
                                        </tr>
                                    ))}
                            </tbody>
                        </table>
                    </div>
                </div>
            )}

            {tab === "Income" && (
                <div className="grid cols-2">
                    <div className="card">
                        <h2>Dividends & interest</h2>
                        <IncomeChart rows={income} dark={dark} />
                    </div>
                    <div className="card">
                        <h2>Income detail</h2>
                        <table className="data">
                            <thead>
                                <tr>
                                    <th>Month</th>
                                    <th>Type</th>
                                    <th className="num">Amount</th>
                                    <th className="num">Movements</th>
                                </tr>
                            </thead>
                            <tbody>
                                {income.length === 0 && (
                                    <tr>
                                        <td colSpan={4} className="muted">
                                            No income recorded.
                                        </td>
                                    </tr>
                                )}
                                {[...income]
                                    .sort(
                                        (a, b) =>
                                            a.month.localeCompare(b.month) ||
                                            a.type.localeCompare(b.type),
                                    )
                                    .map((r) => (
                                        <tr key={`${r.month}-${r.type}`}>
                                            <td>{monthLabel(r.month)}</td>
                                            <td>
                                                {r.type === "DIVIDEND" ? "Dividend" : "Interest"}
                                            </td>
                                            <td className="num">{money(r.incomeUsd)}</td>
                                            <td className="num">{r.movements}</td>
                                        </tr>
                                    ))}
                            </tbody>
                        </table>
                    </div>
                </div>
            )}

            {tab === "Holdings" && (
                <div className="card">
                    <h2>Top holdings</h2>
                    <table className="data">
                        <thead>
                            <tr>
                                <th className="num">#</th>
                                <th>Security</th>
                                <th>Asset class</th>
                                <th>Identifier</th>
                                <th className="num">Value</th>
                                <th className="num">Weight</th>
                            </tr>
                        </thead>
                        <tbody>
                            {holdings.map((r) => (
                                <tr key={r.rank}>
                                    <td className="num muted">{r.rank}</td>
                                    <td>{r.securityName}</td>
                                    <td>{r.assetClass}</td>
                                    <td className="muted mono">
                                        {r.securityScheme} {r.securityId}
                                    </td>
                                    <td className="num">{money(r.ownedUsd)}</td>
                                    <td className="num">
                                        <div className="weight-cell">
                                            <span className="mono">{percent(r.weight)}</span>
                                            <span className="weight-bar">
                                                <span
                                                    style={{
                                                        width: `${Math.min(r.weight * 100, 100)}%`,
                                                    }}
                                                />
                                            </span>
                                        </div>
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            )}

            {tab === "Ownership" && (
                <div className="card">
                    <h2>Accounts &amp; ownership</h2>
                    <p className="muted" style={{ marginTop: -6, fontSize: 13 }}>
                        The accounts this client owns and the share held. A shared account is one
                        owned by more than one client — its co-owners in this firm are listed where
                        visible.
                    </p>
                    <table className="data">
                        <thead>
                            <tr>
                                <th>Account</th>
                                <th className="num">This client's share</th>
                                <th>Ownership</th>
                                <th>Co-owners in firm</th>
                            </tr>
                        </thead>
                        <tbody>
                            {ownedAccounts.map((accountId) => {
                                const mine = data.ownership.find(
                                    (r) =>
                                        r.accountId === accountId && r.clientId === client.clientId,
                                )!;
                                const coOwners = data.ownership.filter(
                                    (r) =>
                                        r.accountId === accountId && r.clientId !== client.clientId,
                                );
                                return (
                                    <tr key={accountId}>
                                        <td className="mono">{accountId}</td>
                                        <td className="num">{percent(mine.ownershipPct, 2)}</td>
                                        <td>
                                            {mine.isShared ? (
                                                <span className="chip">
                                                    Shared · {mine.ownerCount} owners
                                                </span>
                                            ) : (
                                                <span className="muted">Sole owner</span>
                                            )}
                                        </td>
                                        <td>
                                            {coOwners.length === 0 ? (
                                                <span className="muted">—</span>
                                            ) : (
                                                coOwners
                                                    .map(
                                                        (c) =>
                                                            `${c.clientName} (${percent(c.ownershipPct, 0)})`,
                                                    )
                                                    .join(", ")
                                            )}
                                        </td>
                                    </tr>
                                );
                            })}
                        </tbody>
                    </table>
                </div>
            )}

            {tab === "Performance" && (
                <>
                    <div className="card" style={{ marginBottom: 18 }}>
                        <h2>Growth of $1 since inception</h2>
                        <p className="muted" style={{ marginTop: -6, fontSize: 13 }}>
                            Time-weighted: chain-linked market return, with the client's own
                            contributions and withdrawals excluded.
                        </p>
                        <PerformanceChart rows={performance} dark={dark} />
                    </div>
                    <div className="card">
                        <h2>Since inception, three ways</h2>
                        <p className="muted" style={{ marginTop: -6, fontSize: 13 }}>
                            {performanceSummary
                                ? `${longDate(performanceSummary.inceptionDate)} – ${longDate(performanceSummary.asOf)}`
                                : "No performance history recorded."}
                            {" — see docs/PERFORMANCE_METHODOLOGY.md for why these differ."}
                        </p>
                        {performanceSummary && (
                            <div className="grid tiles">
                                <Tile
                                    label="Time-weighted (TWR)"
                                    value={percent(performanceSummary.twrSinceInception, 2)}
                                    sub="Manager's return, flow timing excluded"
                                />
                                <Tile
                                    label="Modified Dietz"
                                    value={
                                        performanceSummary.dietzSinceInception === null
                                            ? "—"
                                            : percent(performanceSummary.dietzSinceInception, 2)
                                    }
                                    sub="Flow-weighted approximation of TWR"
                                />
                                <Tile
                                    label="Money-weighted (IRR)"
                                    value={
                                        performanceSummary.irrSinceInceptionAnnualized === null
                                            ? "—"
                                            : percent(
                                                  performanceSummary.irrSinceInceptionAnnualized,
                                                  2,
                                              )
                                    }
                                    sub="Investor's return, annualized"
                                />
                                <Tile
                                    label="Net external flow"
                                    value={money(performanceSummary.netExternalFlowUsd)}
                                    sub={`${money(performanceSummary.wealthBeginUsd)} → ${money(performanceSummary.wealthEndUsd)}`}
                                />
                            </div>
                        )}
                    </div>
                </>
            )}

            {tab === "Alternatives" && (
                <div className="card">
                    <h2>Private markets</h2>
                    <p className="muted" style={{ marginTop: -6, fontSize: 13 }}>
                        Committed, called, and distributed capital, unfunded commitment, and current
                        NAV per fund. MOIC is the multiple on invested capital (distributed + NAV,
                        over called). Only confirmed documents are reflected — a fund still awaiting
                        review shows as pending rather than moving these figures early.
                    </p>
                    <table className="data">
                        <thead>
                            <tr>
                                <th>Fund</th>
                                <th className="num">Committed</th>
                                <th className="num">Called</th>
                                <th className="num">Distributed</th>
                                <th className="num">Unfunded</th>
                                <th className="num">Current NAV</th>
                                <th className="num">MOIC</th>
                            </tr>
                        </thead>
                        <tbody>
                            {altsHoldings.length === 0 && (
                                <tr>
                                    <td colSpan={7} className="muted">
                                        No private-fund holdings.
                                    </td>
                                </tr>
                            )}
                            {altsHoldings.map((r) => (
                                <tr key={r.fundId}>
                                    <td>
                                        {r.fundName}
                                        {r.pendingReviewDocuments > 0 && (
                                            <span className="chip" style={{ marginLeft: 8 }}>
                                                {r.pendingReviewDocuments} pending review
                                            </span>
                                        )}
                                    </td>
                                    <td className="num">{money(r.totalCommitmentUsd)}</td>
                                    <td className="num">{money(r.calledToDateUsd)}</td>
                                    <td className="num">{money(r.distributedToDateUsd)}</td>
                                    <td className="num">{money(r.unfundedCommitmentUsd)}</td>
                                    <td className="num">{money(r.currentNavUsd)}</td>
                                    <td className="num">
                                        {r.moic === null ? "—" : multiple(r.moic)}
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            )}
        </>
    );
}

function Tile({
    label,
    value,
    sub,
    hero,
}: {
    label: string;
    value: string;
    sub?: string;
    hero?: boolean;
}) {
    return (
        <div className="card tile">
            <div className="label">{label}</div>
            <div className={`value ${hero ? "hero" : ""}`}>{value}</div>
            {sub && <div className="asof">{sub}</div>}
        </div>
    );
}

function ReconcileBadge({ ok }: { ok: boolean }) {
    return (
        <span
            className={`badge ${ok ? "ok" : "warn"}`}
            title={
                ok
                    ? "Positions + cash agree with the custodial books"
                    : "The daily quality check flagged a variance against the books"
            }
        >
            <span className="dot" />
            {ok ? "Books reconcile" : "Reconciliation variance"}
        </span>
    );
}
