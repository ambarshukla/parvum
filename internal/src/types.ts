// Shapes returned by the internal serving API
// (dev.parvum.serving.internal.InternalProjectionResource). Money and
// weights arrive as JSON numbers; formatted at the edge.

export type DqDimension = "freshness" | "completeness" | "accuracy" | "exceptions" | "governance";

export interface DqMetricRow {
    asOf: string;
    dimension: DqDimension;
    metric: string;
    value: number;
    passed: boolean | null;
    detail: string;
}

// dev.parvum.serving.internal.InternalProjectionResource.CdeRegistryRow.
// One row per column the platform publishes. tier/owner are nullable because
// the register covers published columns, not just classified ones -- an
// unclassified column is what columns_classified_rate measures.
export interface CdeRegistryRow {
    tableName: string;
    columnName: string;
    layer: string;
    description: string;
    tier: "critical" | "supporting" | "operational" | null;
    owner: string | null;
    definition: string | null;
    qualityRules: string | null;
    qualityRuleCount: number;
    controlGap: string | null;
    slo: string | null;
    sloMeasuredBy: string | null;
    sloTarget: string | null;
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
