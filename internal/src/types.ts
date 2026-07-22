// Shapes returned by the internal serving API
// (dev.parvum.serving.internal.InternalProjectionResource). Money and
// weights arrive as JSON numbers; formatted at the edge.

export type DqDimension = "freshness" | "completeness" | "accuracy" | "exceptions";

export interface DqMetricRow {
    asOf: string;
    dimension: DqDimension;
    metric: string;
    value: number;
    passed: boolean | null;
    detail: string;
}

export type QueueStatus = "pending" | "approved" | "corrected";
export type DocType = "capital_call" | "distribution" | "capital_account_statement";

// dev.parvum.serving.internal.AltsReviewResource.QueueItem. extractedFields
// and decidedFields arrive as JSON *text*, not a parsed object -- the field
// set differs by docType, so the server keeps them as a JSONB/String column
// rather than a fixed shape (see V1__alts_review_queue.sql).
export interface QueueItem {
    id: number;
    fundId: string;
    document: string;
    docType: DocType;
    sequenceNumber: number | null;
    periodEnd: string | null;
    extractedFields: string;
    confidence: number;
    validationNotes: string | null;
    status: QueueStatus;
    stale: boolean;
    decidedFields: string | null;
    decidedAt: string | null;
    loadedAt: string;
}
