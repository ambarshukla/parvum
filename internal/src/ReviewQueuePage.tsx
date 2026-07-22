import { useEffect, useState } from "react";
import { approveQueueItem, correctQueueItem, fetchDocumentPdf, fetchQueue } from "./api";
import { longDate } from "./format";
import type { DocType, QueueItem, QueueStatus } from "./types";

type Filter = QueueStatus | "all";

const FILTERS: Filter[] = ["pending", "approved", "corrected", "all"];

const DOC_TYPE_LABELS: Record<DocType, string> = {
    capital_call: "Capital call",
    distribution: "Distribution",
    capital_account_statement: "Capital account statement",
};

function docTypeLabel(docType: DocType): string {
    return DOC_TYPE_LABELS[docType] ?? docType;
}

function capitalize(s: string): string {
    return s.charAt(0).toUpperCase() + s.slice(1);
}

/** A field's current value, as editable text. null/undefined show as an
 *  empty box (nothing meaningful to type back) rather than the string "null". */
function formatFieldValue(value: unknown): string {
    if (value === null || value === undefined) return "";
    return String(value);
}

/** Best-effort back into the extracted field's original type, so a
 *  correction to one field doesn't silently turn a number or boolean into a
 *  string for every field in the row. */
function coerceFieldValue(original: unknown, input: string): unknown {
    if (typeof original === "number") {
        const parsed = Number(input);
        return Number.isNaN(parsed) ? input : parsed;
    }
    if (typeof original === "boolean") {
        return input.trim().toLowerCase() === "true";
    }
    if (original === null && input === "") return null;
    return input;
}

export function ReviewQueuePage() {
    const [filter, setFilter] = useState<Filter>("pending");
    const [items, setItems] = useState<QueueItem[] | null>(null);
    const [selectedId, setSelectedId] = useState<number | null>(null);
    const [error, setError] = useState<string | null>(null);

    function load(next: Filter) {
        setItems(null);
        fetchQueue(next === "all" ? undefined : next)
            .then((rows) => {
                setItems(rows);
                setSelectedId((current) =>
                    current !== null && rows.some((r) => r.id === current)
                        ? current
                        : (rows[0]?.id ?? null),
                );
            })
            .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
    }

    useEffect(() => {
        load(filter);
        // load() is stable enough for this component's needs; re-running on
        // every render would refetch mid-edit.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [filter]);

    if (error) {
        return (
            <div className="center-state">
                <strong>Could not reach the serving API.</strong>
                <code>{error}</code>
            </div>
        );
    }

    const selected = items?.find((item) => item.id === selectedId) ?? null;

    return (
        <>
            <div className="client-header">
                <div>
                    <h1>Alts Review Queue</h1>
                    <div className="asof">
                        Documents silver_alts_documents routed to needs_review
                    </div>
                </div>
            </div>

            <div className="tabs">
                {FILTERS.map((f) => (
                    <button
                        key={f}
                        className={`tab ${filter === f ? "active" : ""}`}
                        onClick={() => setFilter(f)}
                    >
                        {capitalize(f)}
                    </button>
                ))}
            </div>

            {items === null && <div className="center-state">Loading…</div>}
            {items !== null && items.length === 0 && (
                <div className="center-state">No {filter === "all" ? "" : filter} documents.</div>
            )}
            {items !== null && items.length > 0 && (
                <div className="queue-layout">
                    <QueueList items={items} selectedId={selectedId} onSelect={setSelectedId} />
                    {selected && (
                        <QueueDetail
                            key={selected.id}
                            item={selected}
                            onDecided={() => load(filter)}
                        />
                    )}
                </div>
            )}
        </>
    );
}

function QueueList({
    items,
    selectedId,
    onSelect,
}: {
    items: QueueItem[];
    selectedId: number | null;
    onSelect: (id: number) => void;
}) {
    return (
        <div className="card queue-list">
            <table className="data">
                <thead>
                    <tr>
                        <th>Document</th>
                        <th>Status</th>
                    </tr>
                </thead>
                <tbody>
                    {items.map((item) => (
                        <tr
                            key={item.id}
                            className={`queue-row ${item.id === selectedId ? "active" : ""}`}
                            onClick={() => onSelect(item.id)}
                        >
                            <td>
                                <div>{item.document}</div>
                                <div className="muted queue-row-sub">
                                    {item.fundId} · {docTypeLabel(item.docType)}
                                </div>
                            </td>
                            <td>
                                <StatusBadge status={item.status} stale={item.stale} />
                            </td>
                        </tr>
                    ))}
                </tbody>
            </table>
        </div>
    );
}

function StatusBadge({ status, stale }: { status: QueueStatus; stale: boolean }) {
    if (stale) {
        return (
            <span className="badge warn">
                <span className="dot" />
                Stale
            </span>
        );
    }
    if (status === "pending") {
        return (
            <span className="badge neutral">
                <span className="dot" />
                Pending
            </span>
        );
    }
    return (
        <span className="badge ok">
            <span className="dot" />
            {capitalize(status)}
        </span>
    );
}

function QueueDetail({ item, onDecided }: { item: QueueItem; onDecided: () => void }) {
    const extracted = JSON.parse(item.extractedFields) as Record<string, unknown>;
    const decidedFields = item.decidedFields
        ? (JSON.parse(item.decidedFields) as Record<string, unknown>)
        : null;
    const decided = item.status !== "pending";

    const [edits, setEdits] = useState<Record<string, string>>(() =>
        Object.fromEntries(Object.entries(extracted).map(([k, v]) => [k, formatFieldValue(v)])),
    );
    const [submitting, setSubmitting] = useState(false);
    const [actionError, setActionError] = useState<string | null>(null);

    async function handleApprove() {
        setSubmitting(true);
        setActionError(null);
        try {
            await approveQueueItem(item.id);
            onDecided();
        } catch (e) {
            setActionError(e instanceof Error ? e.message : String(e));
            setSubmitting(false);
        }
    }

    async function handleCorrect() {
        setSubmitting(true);
        setActionError(null);
        try {
            const corrected = Object.fromEntries(
                Object.entries(extracted).map(([field, original]) => [
                    field,
                    coerceFieldValue(original, edits[field] ?? ""),
                ]),
            );
            await correctQueueItem(item.id, corrected);
            onDecided();
        } catch (e) {
            setActionError(e instanceof Error ? e.message : String(e));
            setSubmitting(false);
        }
    }

    return (
        <div className="card queue-detail">
            <div className="queue-detail-header">
                <div>
                    <h2 style={{ margin: 0 }}>{item.document}</h2>
                    <div className="asof">
                        {item.fundId} · {docTypeLabel(item.docType)}
                        {item.periodEnd && ` · period end ${longDate(item.periodEnd)}`}
                        {item.sequenceNumber !== null && ` · #${item.sequenceNumber}`}
                    </div>
                </div>
                <StatusBadge status={item.status} stale={item.stale} />
            </div>

            {item.validationNotes && <div className="validation-notes">{item.validationNotes}</div>}

            <div className="queue-detail-body">
                <div>
                    <table className="data">
                        <tbody>
                            {Object.entries(extracted).map(([field, value]) => (
                                <tr key={field}>
                                    <td className="field-name">{field}</td>
                                    <td>
                                        {decided ? (
                                            <span className="mono">
                                                {formatFieldValue(
                                                    decidedFields && field in decidedFields
                                                        ? decidedFields[field]
                                                        : value,
                                                )}
                                            </span>
                                        ) : (
                                            <input
                                                className="field-input"
                                                aria-label={field}
                                                value={edits[field] ?? ""}
                                                onChange={(e) =>
                                                    setEdits((prev) => ({
                                                        ...prev,
                                                        [field]: e.target.value,
                                                    }))
                                                }
                                            />
                                        )}
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>

                    {decided && (
                        <div className="muted queue-row-sub" style={{ marginTop: 10 }}>
                            {item.status === "approved" ? "Approved as extracted" : "Corrected"}
                            {item.decidedAt && ` · ${longDate(item.decidedAt.slice(0, 10))}`}
                        </div>
                    )}

                    {!decided && (
                        <div className="queue-actions">
                            <button
                                className="theme-toggle"
                                onClick={handleApprove}
                                disabled={submitting}
                            >
                                Approve as extracted
                            </button>
                            <button
                                className="theme-toggle"
                                onClick={handleCorrect}
                                disabled={submitting}
                            >
                                Save correction
                            </button>
                        </div>
                    )}
                    {actionError && (
                        <code style={{ color: "var(--critical)", display: "block", marginTop: 10 }}>
                            {actionError}
                        </code>
                    )}
                </div>

                <DocumentViewer fundId={item.fundId} document={item.document} />
            </div>
        </div>
    );
}

/** The source PDF, rendered by the browser's own viewer.
 *
 *  Fetched into a blob rather than pointed at directly: `/internal/**` needs
 *  the CSRF header on every request and an `<iframe src>` can't send one.
 *  The object URL is revoked when the selection changes, so flicking through
 *  a queue doesn't leak one blob per document viewed. */
function DocumentViewer({ fundId, document: documentName }: { fundId: string; document: string }) {
    const [url, setUrl] = useState<string | null>(null);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        let cancelled = false;
        let objectUrl: string | null = null;
        setUrl(null);
        setError(null);

        fetchDocumentPdf(fundId, documentName)
            .then((blob) => {
                if (cancelled) return;
                objectUrl = URL.createObjectURL(blob);
                setUrl(objectUrl);
            })
            .catch((e: unknown) => {
                if (!cancelled) setError(e instanceof Error ? e.message : String(e));
            });

        return () => {
            cancelled = true;
            if (objectUrl) URL.revokeObjectURL(objectUrl);
        };
    }, [fundId, documentName]);

    if (error) {
        return (
            <div className="pdf-frame pdf-placeholder">
                <span className="muted">Could not load the source PDF.</span>
                <code>{error}</code>
            </div>
        );
    }
    if (!url) {
        return (
            <div className="pdf-frame pdf-placeholder">
                <span className="muted">Loading document…</span>
            </div>
        );
    }
    // #view=FitH asks the browser's PDF viewer to fit the page to the frame's
    // width. Without it a half-width pane renders the page at a default zoom
    // and clips the right-hand column behind a horizontal scrollbar — which
    // hides exactly the numbers a reviewer is here to check. A viewer that
    // ignores the fragment simply falls back to its own default.
    return (
        <iframe
            className="pdf-frame"
            src={`${url}#view=FitH`}
            title={`${documentName} — source document`}
        />
    );
}
