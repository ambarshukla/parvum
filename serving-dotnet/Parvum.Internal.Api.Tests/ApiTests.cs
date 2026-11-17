using System.Net;
using System.Net.Http.Json;
using System.Text;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.DependencyInjection.Extensions;
using Xunit;

namespace Parvum.Internal.Api.Tests;

/// <summary>
/// Starts the real application in memory with fake stores behind it, so these tests exercise
/// the gate, the routing and the status codes without a database. What the SQL does is tested
/// where it can be compared with the Java service's: the parity suite at the repo root.
/// </summary>
public sealed class ApiFactory : WebApplicationFactory<Program>
{
    public const string Password = "test-only-password";

    public FakeReviewStore Review { get; } = new();
    public FakeOpsStore Ops { get; } = new();

    static ApiFactory()
    {
        // Program reads its settings before the test host can override them, so they are
        // supplied the way a deployment supplies them: through the environment.
        Environment.SetEnvironmentVariable("Parvum__Internal__Password", Password);
        Environment.SetEnvironmentVariable("Parvum__Internal__SessionSecret", "test-only-signing-key");
        Environment.SetEnvironmentVariable("Parvum__Tenants", "aldergate,stonefield");
        Environment.SetEnvironmentVariable("ConnectionStrings__Parvum", "Host=unused.invalid");
    }

    protected override void ConfigureWebHost(IWebHostBuilder builder)
    {
        builder.ConfigureServices(services =>
        {
            services.RemoveAll<IReviewStore>();
            services.RemoveAll<IOpsStore>();
            services.AddSingleton<IReviewStore>(Review);
            services.AddSingleton<IOpsStore>(Ops);
        });
    }

    /// <summary>A client that sends the header the gate requires, and keeps cookies.</summary>
    public HttpClient CreateAppClient()
    {
        var client = CreateClient();
        client.DefaultRequestHeaders.Add("X-Parvum-Internal", "1");
        return client;
    }

    public async Task<HttpClient> CreateLoggedInClientAsync()
    {
        var client = CreateAppClient();
        var response = await client.PostAsJsonAsync("/internal/auth/login", new { password = Password });
        response.EnsureSuccessStatusCode();
        return client;
    }
}

public sealed class FakeReviewStore : IReviewStore
{
    private static readonly DateTime Loaded = new(2026, 1, 1, 12, 0, 0, DateTimeKind.Utc);

    public Dictionary<long, QueueItem> Items { get; } = new()
    {
        [1] = Item(1, "pending"),
        [2] = Item(2, "approved"),
    };

    public string? LastStatusFilter { get; private set; }
    public (long Id, string Action, string? Fields)? LastDecision { get; private set; }

    private static QueueItem Item(long id, string status) => new(
        id, "FUND-US01", $"capital_call_0{id}.pdf", "capital_call", (int)id, new DateOnly(2025, 12, 31),
        """{"amount": 1000}""", 0.850m, null, status, false, null, null, Loaded);

    public Task<IReadOnlyList<QueueItem>> ListAsync(string? status, CancellationToken ct)
    {
        LastStatusFilter = status;
        return Task.FromResult<IReadOnlyList<QueueItem>>(
            Items.Values.Where(i => status is null || i.Status == status).ToList());
    }

    public Task<QueueItem?> GetAsync(long id, CancellationToken ct) =>
        Task.FromResult(Items.GetValueOrDefault(id));

    public Task<byte[]?> GetDocumentAsync(string fundId, string document, CancellationToken ct) =>
        Task.FromResult(fundId == "FUND-US01" ? Encoding.ASCII.GetBytes("%PDF-1.4 test") : null);

    public Task<Decision> DecideAsync(long id, string action, string? correctedFieldsJson, CancellationToken ct)
    {
        if (!Items.TryGetValue(id, out var item))
        {
            return Task.FromResult(new Decision(DecisionOutcome.NotFound, null, null));
        }
        if (item.Status != "pending")
        {
            return Task.FromResult(new Decision(DecisionOutcome.AlreadyDecided, item, item.Status));
        }
        LastDecision = (id, action, correctedFieldsJson);
        Items[id] = item with { Status = action, DecidedFields = correctedFieldsJson ?? item.ExtractedFields };
        return Task.FromResult(new Decision(DecisionOutcome.Decided, Items[id], action));
    }
}

public sealed class FakeOpsStore : IOpsStore
{
    public List<string> SchemasRead { get; } = [];

    public Task<IReadOnlyList<DqMetricRow>> DqMetricsAsync(string schema, CancellationToken ct)
    {
        SchemasRead.Add(schema);
        return Task.FromResult<IReadOnlyList<DqMetricRow>>(
            [new DqMetricRow(new DateOnly(2026, 1, 1), "freshness", "bronze_days_behind", 0m, true, "fresh")]);
    }

    public Task<IReadOnlyList<CdeRegistryRow>> CdeRegistryAsync(string schema, CancellationToken ct)
    {
        SchemasRead.Add(schema);
        return Task.FromResult<IReadOnlyList<CdeRegistryRow>>([]);
    }

    public Task<IReadOnlyList<SloAttainmentRow>> SloAttainmentAsync(string schema, CancellationToken ct)
    {
        SchemasRead.Add(schema);
        return Task.FromResult<IReadOnlyList<SloAttainmentRow>>([]);
    }
}

public class TheGate(ApiFactory factory) : IClassFixture<ApiFactory>
{
    [Theory]
    [InlineData("/internal/auth/session")]
    [InlineData("/internal/auth/login")]
    [InlineData("/internal/alts/queue")]
    [InlineData("/internal/no-such-route")]
    public async Task Without_the_custom_header_every_internal_path_is_forbidden(string path)
    {
        var response = await factory.CreateClient().GetAsync(path);

        Assert.Equal(HttpStatusCode.Forbidden, response.StatusCode);
    }

    [Theory]
    [InlineData("/internal/auth/session")]
    [InlineData("/internal/alts/queue")]
    [InlineData("/internal/tenants/aldergate/dq-metrics")]
    // A route that does not exist answers 401, not 404: nobody without a session can use the
    // difference to learn which paths are real.
    [InlineData("/internal/no-such-route")]
    public async Task With_the_header_but_no_session_the_answer_is_unauthorized(string path)
    {
        var response = await factory.CreateAppClient().GetAsync(path);

        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
    }

    [Fact]
    public async Task A_made_up_cookie_is_not_a_session()
    {
        var client = factory.CreateAppClient();
        client.DefaultRequestHeaders.Add("Cookie", "parvum_internal_session=4102444800.forged");

        var response = await client.GetAsync("/internal/auth/session");

        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
    }

    [Fact]
    public async Task Paths_outside_internal_are_not_gated()
    {
        var response = await factory.CreateClient().GetAsync("/healthz");

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
    }
}

public class Login(ApiFactory factory) : IClassFixture<ApiFactory>
{
    [Theory]
    [InlineData("wrong")]
    [InlineData("")]
    public async Task A_wrong_password_is_refused(string password)
    {
        var response = await factory.CreateAppClient().PostAsJsonAsync("/internal/auth/login", new { password });

        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
        Assert.False(response.Headers.Contains("Set-Cookie"));
    }

    [Fact]
    public async Task A_login_with_no_body_is_refused_not_an_error()
    {
        var response = await factory.CreateAppClient().PostAsync("/internal/auth/login", null);

        Assert.Equal(HttpStatusCode.Unauthorized, response.StatusCode);
    }

    [Theory]
    [InlineData(ApiFactory.Password)]
    [InlineData("parvum-showcase")] // the public demo credential
    public async Task Either_credential_opens_a_session_the_gate_then_accepts(string password)
    {
        var client = factory.CreateAppClient();

        var login = await client.PostAsJsonAsync("/internal/auth/login", new { password });
        Assert.Equal(HttpStatusCode.NoContent, login.StatusCode);

        var cookie = Assert.Single(login.Headers.GetValues("Set-Cookie"));
        Assert.StartsWith("parvum_internal_session=", cookie);
        // Not readable by script, sent only over HTTPS, and allowed cross-site (the app and the
        // API live on different origins in production).
        Assert.Contains("httponly", cookie, StringComparison.OrdinalIgnoreCase);
        Assert.Contains("secure", cookie, StringComparison.OrdinalIgnoreCase);
        Assert.Contains("samesite=none", cookie, StringComparison.OrdinalIgnoreCase);
        Assert.Contains("max-age=43200", cookie, StringComparison.OrdinalIgnoreCase);

        // The test client drops a Secure cookie on its plain-http connection, so present the
        // token by hand, as a browser on HTTPS would.
        var token = cookie.Split(';')[0];
        var request = new HttpRequestMessage(HttpMethod.Get, "/internal/auth/session");
        request.Headers.Add("Cookie", token);
        var session = await client.SendAsync(request);
        Assert.Equal(HttpStatusCode.NoContent, session.StatusCode);
    }

    [Fact]
    public async Task Logging_out_expires_the_cookie()
    {
        var response = await factory.CreateAppClient().PostAsync("/internal/auth/logout", null);

        Assert.Equal(HttpStatusCode.NoContent, response.StatusCode);
        var cookie = Assert.Single(response.Headers.GetValues("Set-Cookie"));
        Assert.StartsWith("parvum_internal_session=;", cookie);
        Assert.Contains("max-age=0", cookie, StringComparison.OrdinalIgnoreCase);
    }
}

public class ReviewQueue : IClassFixture<ApiFactory>
{
    private readonly ApiFactory _factory;
    private readonly HttpClient _client;

    public ReviewQueue(ApiFactory factory)
    {
        _factory = factory;
        _client = factory.CreateAppClient();
        // A real, signed token for the test secret, far in the future.
        var token = new SessionToken("test-only-signing-key", TimeProvider.System).Issue(TimeSpan.FromHours(1));
        _client.DefaultRequestHeaders.Add("Cookie", $"parvum_internal_session={token}");
    }

    [Fact]
    public async Task The_status_filter_reaches_the_store()
    {
        var response = await _client.GetAsync("/internal/alts/queue?status=pending");

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        Assert.Equal("pending", _factory.Review.LastStatusFilter);
    }

    [Fact]
    public async Task An_item_is_served_in_the_shape_the_review_screen_is_typed_against()
    {
        var json = await _client.GetStringAsync("/internal/alts/queue/2");

        Assert.Contains("\"fundId\":\"FUND-US01\"", json);
        Assert.Contains("\"periodEnd\":\"2025-12-31\"", json);
        Assert.Contains("\"confidence\":0.850", json);
        // JSON carried as text, not as a nested object.
        Assert.Contains("\"extractedFields\":\"{", json);
        Assert.Contains("\"decidedAt\":null", json);
        Assert.Contains("\"loadedAt\":\"2026-01-01T12:00:00Z\"", json);
    }

    [Theory]
    [InlineData("/internal/alts/queue/999")]
    [InlineData("/internal/alts/queue/not-a-number")]
    [InlineData("/internal/alts/documents/FUND-XX99/missing.pdf")]
    public async Task What_is_not_there_is_not_found(string path)
    {
        var response = await _client.GetAsync(path);

        Assert.Equal(HttpStatusCode.NotFound, response.StatusCode);
    }

    [Fact]
    public async Task A_document_is_served_inline_under_a_name_that_cannot_break_the_header()
    {
        var response = await _client.GetAsync("/internal/alts/documents/FUND-US01/call%22%0Ax.pdf");

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        Assert.Equal("application/pdf", response.Content.Headers.ContentType?.MediaType);
        Assert.Equal("inline; filename=\"call__x.pdf\"", response.Content.Headers.GetValues("Content-Disposition").Single());
    }

    [Fact]
    public async Task Approving_accepts_the_extraction_as_read()
    {
        var factory = new ApiFactory();
        var client = await ClientFor(factory);

        var response = await client.PostAsync("/internal/alts/queue/1/approve", null);

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        Assert.Equal((1, "approved", null), factory.Review.LastDecision);
    }

    [Fact]
    public async Task Correcting_records_the_reviewers_fields()
    {
        var factory = new ApiFactory();
        var client = await ClientFor(factory);

        var response = await client.PostAsJsonAsync("/internal/alts/queue/1/correct", new { amount = 1250 });

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        Assert.Equal((1, "corrected", """{"amount":1250}"""), factory.Review.LastDecision);
    }

    [Theory]
    [InlineData("{}")]
    [InlineData("[1, 2]")]
    [InlineData("\"text\"")]
    [InlineData("not json")]
    public async Task A_correction_must_be_a_non_empty_object(string body)
    {
        var response = await _client.PostAsync(
            "/internal/alts/queue/1/correct", new StringContent(body, Encoding.UTF8, "application/json"));

        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
    }

    [Fact]
    public async Task An_item_already_decided_cannot_be_decided_again()
    {
        var approve = await _client.PostAsync("/internal/alts/queue/2/approve", null);
        var correct = await _client.PostAsJsonAsync("/internal/alts/queue/2/correct", new { amount = 1 });

        Assert.Equal(HttpStatusCode.Conflict, approve.StatusCode);
        Assert.Equal(HttpStatusCode.Conflict, correct.StatusCode);
    }

    [Fact]
    public async Task Deciding_an_item_that_does_not_exist_is_not_found()
    {
        var response = await _client.PostAsync("/internal/alts/queue/999/approve", null);

        Assert.Equal(HttpStatusCode.NotFound, response.StatusCode);
    }

    private static Task<HttpClient> ClientFor(ApiFactory factory)
    {
        var client = factory.CreateAppClient();
        var token = new SessionToken("test-only-signing-key", TimeProvider.System).Issue(TimeSpan.FromHours(1));
        client.DefaultRequestHeaders.Add("Cookie", $"parvum_internal_session={token}");
        return Task.FromResult(client);
    }
}

public class OperationsViews : IClassFixture<ApiFactory>
{
    private readonly ApiFactory _factory;
    private readonly HttpClient _client;

    public OperationsViews(ApiFactory factory)
    {
        _factory = factory;
        _client = factory.CreateAppClient();
        var token = new SessionToken("test-only-signing-key", TimeProvider.System).Issue(TimeSpan.FromHours(1));
        _client.DefaultRequestHeaders.Add("Cookie", $"parvum_internal_session={token}");
    }

    [Theory]
    [InlineData("dq-metrics")]
    [InlineData("cde-registry")]
    [InlineData("slo-attainment")]
    public async Task A_known_tenant_is_read_from_its_own_schema(string view)
    {
        var response = await _client.GetAsync($"/internal/tenants/stonefield/{view}");

        Assert.Equal(HttpStatusCode.OK, response.StatusCode);
        Assert.Contains("tenant_stonefield", _factory.Ops.SchemasRead);
    }

    [Theory]
    [InlineData("unknown")]
    [InlineData("ALDERGATE")]
    [InlineData("aldergate%22")]
    public async Task An_unknown_tenant_is_not_found_and_never_reaches_the_store(string tenant)
    {
        var before = _factory.Ops.SchemasRead.Count;

        var response = await _client.GetAsync($"/internal/tenants/{tenant}/dq-metrics");

        Assert.Equal(HttpStatusCode.NotFound, response.StatusCode);
        Assert.Equal(before, _factory.Ops.SchemasRead.Count);
    }

    [Fact]
    public async Task Dates_and_decimals_keep_the_form_the_screen_expects()
    {
        var json = await _client.GetStringAsync("/internal/tenants/aldergate/dq-metrics");

        Assert.Equal(
            """[{"asOf":"2026-01-01","dimension":"freshness","metric":"bronze_days_behind","value":0,"passed":true,"detail":"fresh"}]""",
            json);
    }
}
