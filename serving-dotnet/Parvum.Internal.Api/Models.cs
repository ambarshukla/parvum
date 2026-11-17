namespace Parvum.Internal.Api;

// The JSON these records serialise to is the contract the internal React app is typed against
// (internal/src/types.ts) and the one the Java service already serves. Field names, nullability
// and order of rows are all part of it; parity/parity.py holds both services to it.

/// <summary>One document in the review queue.</summary>
/// <remarks>
/// <c>ExtractedFields</c> and <c>DecidedFields</c> are JSON carried as text, not nested objects.
/// The field set differs by document type, so the API passes it through untouched and the
/// reviewer's screen decides how to lay it out.
/// </remarks>
public sealed record QueueItem(
    long Id,
    string FundId,
    string Document,
    string DocType,
    int? SequenceNumber,
    DateOnly? PeriodEnd,
    string ExtractedFields,
    decimal Confidence,
    string? ValidationNotes,
    string Status,
    bool Stale,
    string? DecidedFields,
    DateTime? DecidedAt,
    DateTime LoadedAt);

public sealed record DqMetricRow(
    DateOnly AsOf,
    string Dimension,
    string Metric,
    decimal Value,
    bool? Passed,
    string Detail);

public sealed record CdeRegistryRow(
    string TableName,
    string ColumnName,
    string Layer,
    string Description,
    string? Tier,
    string? Owner,
    string? Definition,
    string? QualityRules,
    int QualityRuleCount,
    string? ControlGap,
    string? Slo,
    string? SloMeasuredBy,
    string? SloTarget);

public sealed record SloAttainmentRow(
    string Slo,
    string Objective,
    string MeasuredBy,
    string Target,
    decimal AttainmentObjective,
    int WindowDays,
    DateOnly WindowStart,
    DateOnly WindowEnd,
    int DaysMeasured,
    int DaysMet,
    decimal Attainment,
    bool? MeetsObjective,
    bool InsufficientHistory,
    decimal ErrorBudgetDays,
    int BudgetConsumedDays,
    decimal? BudgetRemainingPct);

public sealed record LoginRequest(string? Password);

/// <summary>What happened when a reviewer tried to decide a queue item.</summary>
public enum DecisionOutcome
{
    Decided,
    NotFound,
    AlreadyDecided,
}

public sealed record Decision(DecisionOutcome Outcome, QueueItem? Item, string? CurrentStatus);
