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
