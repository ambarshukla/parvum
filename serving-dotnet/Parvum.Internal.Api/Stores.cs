using System.Text.RegularExpressions;

namespace Parvum.Internal.Api;

/// <summary>The review queue and its audit trail (the non-tenant <c>internal</c> schema).</summary>
public interface IReviewStore
{
    Task<IReadOnlyList<QueueItem>> ListAsync(string? status, CancellationToken ct);

    Task<QueueItem?> GetAsync(long id, CancellationToken ct);

    Task<byte[]?> GetDocumentAsync(string fundId, string document, CancellationToken ct);

    /// <summary>
    /// Records a decision and its audit row together, or does neither.
    /// </summary>
    /// <param name="action"><c>approved</c> or <c>corrected</c>.</param>
    /// <param name="correctedFieldsJson">The reviewer's fields, or null to accept the extraction as read.</param>
    Task<Decision> DecideAsync(long id, string action, string? correctedFieldsJson, CancellationToken ct);
}

/// <summary>Pipeline-wide operations data, read through a tenant's schema.</summary>
public interface IOpsStore
{
    Task<IReadOnlyList<DqMetricRow>> DqMetricsAsync(string schema, CancellationToken ct);

    Task<IReadOnlyList<CdeRegistryRow>> CdeRegistryAsync(string schema, CancellationToken ct);

    Task<IReadOnlyList<SloAttainmentRow>> SloAttainmentAsync(string schema, CancellationToken ct);
}

/// <summary>
/// The advisory firms this instance serves, and the one place a tenant id becomes a schema name.
/// </summary>
/// <remarks>
/// A schema name cannot be sent as a bound parameter, so the tenant id ends up inside the SQL
/// text. Two checks make that safe, and both must hold: the id must be in the configured list,
/// and it must match a shape that cannot contain a quote, a space or a semicolon.
/// </remarks>
public sealed partial class Tenants(IEnumerable<string> tenantIds)
{
    private readonly HashSet<string> _ids = new(tenantIds, StringComparer.Ordinal);

    [GeneratedRegex("^[a-z][a-z0-9_]*$")]
    private static partial Regex SafeTenantId();

    /// <summary>The schema for a tenant, or null if the id is unknown or malformed.</summary>
    public string? SchemaFor(string tenantId) =>
        _ids.Contains(tenantId) && SafeTenantId().IsMatch(tenantId) ? $"tenant_{tenantId}" : null;

    public static Tenants Parse(string? commaSeparated) =>
        new((commaSeparated ?? "").Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries));
}
