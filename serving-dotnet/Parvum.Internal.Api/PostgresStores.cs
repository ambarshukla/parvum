using Npgsql;
using NpgsqlTypes;

namespace Parvum.Internal.Api;

/// <summary>
/// Runs work inside one transaction whose first statement points the connection at one schema.
/// </summary>
/// <remarks>
/// <c>SET LOCAL</c> lasts until the transaction ends and no longer, so a pooled connection can
/// never carry one request's schema into the next. Table names in every query below are
/// therefore unqualified, exactly as in the Java service. Callers pass only a schema that is a
/// constant or has come through <see cref="Tenants.SchemaFor"/>.
/// </remarks>
internal static class SchemaScope
{
    public static async Task<T> RunAsync<T>(
        NpgsqlDataSource dataSource,
        string schema,
        Func<NpgsqlConnection, NpgsqlTransaction, Task<T>> work,
        CancellationToken ct)
    {
        await using var connection = await dataSource.OpenConnectionAsync(ct);
        await using var transaction = await connection.BeginTransactionAsync(ct);
        await using (var scope = new NpgsqlCommand($"set local search_path to \"{schema}\"", connection, transaction))
        {
            await scope.ExecuteNonQueryAsync(ct);
        }
        var result = await work(connection, transaction);
        await transaction.CommitAsync(ct);
        return result;
    }

    public static async Task<List<T>> QueryAsync<T>(
        NpgsqlCommand command, Func<NpgsqlDataReader, T> map, CancellationToken ct)
    {
        var rows = new List<T>();
        await using var reader = await command.ExecuteReaderAsync(ct);
        while (await reader.ReadAsync(ct))
        {
            rows.Add(map(reader));
        }
        return rows;
    }

    public static string? Text(this NpgsqlDataReader r, int i) => r.IsDBNull(i) ? null : r.GetString(i);

    public static T? Value<T>(this NpgsqlDataReader r, int i) where T : struct =>
        r.IsDBNull(i) ? null : r.GetFieldValue<T>(i);
}

public sealed class PostgresReviewStore(NpgsqlDataSource dataSource, TimeProvider clock) : IReviewStore
{
    private const string Schema = "internal";

    // extracted_fields and decided_fields are jsonb; selecting them as text returns Postgres's
    // own rendering of the document, which is what the Java service hands back too.
    private const string Columns =
        "id, fund_id, document, doc_type, sequence_number, period_end, extracted_fields::text, " +
        "confidence, validation_notes, status, stale, decided_fields::text, decided_at, loaded_at";

    private static QueueItem Map(NpgsqlDataReader r) => new(
        r.GetInt64(0),
        r.GetString(1),
        r.GetString(2),
        r.GetString(3),
        r.Value<int>(4),
        r.Value<DateOnly>(5),
        r.GetString(6),
        r.GetDecimal(7),
        r.Text(8),
        r.GetString(9),
        r.GetBoolean(10),
        r.Text(11),
        r.Value<DateTime>(12),
        r.GetDateTime(13));

    public Task<IReadOnlyList<QueueItem>> ListAsync(string? status, CancellationToken ct) =>
        SchemaScope.RunAsync<IReadOnlyList<QueueItem>>(dataSource, Schema, async (connection, transaction) =>
        {
            var filter = status is null ? "" : "where status = @status ";
            await using var command = new NpgsqlCommand(
                $"select {Columns} from alts_review_queue {filter}order by loaded_at desc", connection, transaction);
            if (status is not null) command.Parameters.AddWithValue("status", status);
            return await SchemaScope.QueryAsync(command, Map, ct);
        }, ct);

    public Task<QueueItem?> GetAsync(long id, CancellationToken ct) =>
        SchemaScope.RunAsync(dataSource, Schema, (connection, transaction) => FetchAsync(connection, transaction, id, ct), ct);

    private static async Task<QueueItem?> FetchAsync(
        NpgsqlConnection connection, NpgsqlTransaction transaction, long id, CancellationToken ct)
    {
        await using var command = new NpgsqlCommand(
            $"select {Columns} from alts_review_queue where id = @id", connection, transaction);
        command.Parameters.AddWithValue("id", id);
        return (await SchemaScope.QueryAsync(command, Map, ct)).FirstOrDefault();
    }

    public Task<byte[]?> GetDocumentAsync(string fundId, string document, CancellationToken ct) =>
        SchemaScope.RunAsync(dataSource, Schema, async (connection, transaction) =>
        {
            await using var command = new NpgsqlCommand(
                "select content from alts_documents where fund_id = @fund and document = @document",
                connection, transaction);
            command.Parameters.AddWithValue("fund", fundId);
            command.Parameters.AddWithValue("document", document);
            return await command.ExecuteScalarAsync(ct) as byte[];
        }, ct);

    public Task<Decision> DecideAsync(long id, string action, string? correctedFieldsJson, CancellationToken ct) =>
        SchemaScope.RunAsync(dataSource, Schema, async (connection, transaction) =>
        {
            // One statement does three things that must not come apart: it checks the item is
            // still pending, records the decision, and writes the audit row. The check lives in
            // the UPDATE's WHERE clause rather than in a SELECT beforehand, so two reviewers
            // deciding the same item at the same moment cannot both succeed: the second UPDATE
            // waits for the first, then finds the row no longer pending and changes nothing.
            // The audit INSERT reads from the UPDATE's result, so there is never a decision
            // without an audit row or an audit row without a decision.
            const string sql = """
                with decided as (
                    update alts_review_queue
                       set status = @action,
                           decided_fields = coalesce(@after, extracted_fields),
                           decided_at = @now
                     where id = @id and status = 'pending'
                 returning id, extracted_fields, decided_fields
                ), audited as (
                    insert into alts_review_audit (queue_id, action, before_fields, after_fields, decided_at)
                    select id, @action, extracted_fields, decided_fields, @now from decided
                )
                select count(*) from decided
                """;
            await using (var command = new NpgsqlCommand(sql, connection, transaction))
            {
                command.Parameters.AddWithValue("id", id);
                command.Parameters.AddWithValue("action", action);
                command.Parameters.AddWithValue("now", clock.GetUtcNow().UtcDateTime);
                command.Parameters.Add(new NpgsqlParameter("after", NpgsqlDbType.Jsonb)
                {
                    Value = (object?)correctedFieldsJson ?? DBNull.Value,
                });
                var decided = (long)(await command.ExecuteScalarAsync(ct))!;
                if (decided == 1)
                {
                    return new Decision(DecisionOutcome.Decided, await FetchAsync(connection, transaction, id, ct), action);
                }
            }

            // Nothing changed: either there is no such item, or someone has already decided it.
            var current = await FetchAsync(connection, transaction, id, ct);
            return current is null
                ? new Decision(DecisionOutcome.NotFound, null, null)
                : new Decision(DecisionOutcome.AlreadyDecided, current, current.Status);
        }, ct);
}

public sealed class PostgresOpsStore(NpgsqlDataSource dataSource) : IOpsStore
{
    public Task<IReadOnlyList<DqMetricRow>> DqMetricsAsync(string schema, CancellationToken ct) =>
        SchemaScope.RunAsync<IReadOnlyList<DqMetricRow>>(dataSource, schema, async (connection, transaction) =>
        {
            await using var command = new NpgsqlCommand(
                "select as_of, dimension, metric, value, passed, detail from dq_metrics " +
                "order by dimension, metric, as_of", connection, transaction);
            return await SchemaScope.QueryAsync(command, r => new DqMetricRow(
                r.GetFieldValue<DateOnly>(0), r.GetString(1), r.GetString(2), r.GetDecimal(3),
                r.Value<bool>(4), r.GetString(5)), ct);
        }, ct);

    public Task<IReadOnlyList<CdeRegistryRow>> CdeRegistryAsync(string schema, CancellationToken ct) =>
        SchemaScope.RunAsync<IReadOnlyList<CdeRegistryRow>>(dataSource, schema, async (connection, transaction) =>
        {
            // Critical elements first, then supporting, then plumbing: the register is read
            // top-down, and the top is where the obligations are.
            await using var command = new NpgsqlCommand(
                """
                select table_name, column_name, layer, description, tier, owner, definition,
                       quality_rules, quality_rule_count, control_gap, slo, slo_measured_by, slo_target
                  from cde_registry
                 order by case tier when 'critical' then 0 when 'supporting' then 1
                                    when 'operational' then 2 else 3 end,
                          table_name, column_name
                """, connection, transaction);
            return await SchemaScope.QueryAsync(command, r => new CdeRegistryRow(
                r.GetString(0), r.GetString(1), r.GetString(2), r.GetString(3), r.Text(4), r.Text(5),
                r.Text(6), r.Text(7), r.GetInt32(8), r.Text(9), r.Text(10), r.Text(11), r.Text(12)), ct);
        }, ct);

    public Task<IReadOnlyList<SloAttainmentRow>> SloAttainmentAsync(string schema, CancellationToken ct) =>
        SchemaScope.RunAsync<IReadOnlyList<SloAttainmentRow>>(dataSource, schema, async (connection, transaction) =>
        {
            // Breaches first, then service levels with too little history to judge, then the
            // ones being met. The screen is a work list, not a scoreboard.
            await using var command = new NpgsqlCommand(
                """
                select slo, objective, measured_by, target, attainment_objective, window_days,
                       window_start, window_end, days_measured, days_met, attainment, meets_objective,
                       insufficient_history, error_budget_days, budget_consumed_days, budget_remaining_pct
                  from slo_attainment
                 order by case when meets_objective is false then 0
                               when meets_objective is null then 1 else 2 end,
                          slo
                """, connection, transaction);
            return await SchemaScope.QueryAsync(command, r => new SloAttainmentRow(
                r.GetString(0), r.GetString(1), r.GetString(2), r.GetString(3), r.GetDecimal(4),
                r.GetInt32(5), r.GetFieldValue<DateOnly>(6), r.GetFieldValue<DateOnly>(7), r.GetInt32(8),
                r.GetInt32(9), r.GetDecimal(10), r.Value<bool>(11), r.GetBoolean(12), r.GetDecimal(13),
                r.GetInt32(14), r.Value<decimal>(15)), ct);
        }, ct);
}
