using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;
using Npgsql;
using Parvum.Internal.Api;

// The internal operations API: login, the alternatives review queue with its audit trail, and
// the three read-only operations views. It serves the same /internal/** contract as the Java
// service in serving/, against the same Postgres. It owns no schema: the Java service's Flyway
// migrations remain the single source of truth for every table read or written here.

var builder = WebApplication.CreateBuilder(args);
var config = builder.Configuration;

// No fallbacks for the two secrets. A deployment that forgets one should fail to start, not run
// with a credential that is written down in a repository.
string Required(string key) =>
    config[key] is { Length: > 0 } value ? value : throw new InvalidOperationException($"{key} is not configured");

var password = Encoding.UTF8.GetBytes(Required("Parvum:Internal:Password"));
// Public by design: the demo credential is embedded in a shareable link, so it has a default.
var demoPassword = Encoding.UTF8.GetBytes(config["Parvum:Internal:DemoPassword"] ?? "parvum-showcase");
var cookieSecure = config.GetValue("Parvum:Internal:CookieSecure", true);
var cookieSameSite = Enum.Parse<SameSiteMode>(config["Parvum:Internal:CookieSameSite"] ?? "None", ignoreCase: true);
var corsOrigins = (config["Parvum:Cors:Origins"] ?? "")
    .Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);

builder.Services.AddSingleton(TimeProvider.System);
builder.Services.AddSingleton(sp => new SessionToken(Required("Parvum:Internal:SessionSecret"), sp.GetRequiredService<TimeProvider>()));
builder.Services.AddSingleton(Tenants.Parse(config["Parvum:Tenants"]));
// Built lazily, so the process starts (and the auth endpoints answer) before the database does.
builder.Services.AddSingleton(_ => NpgsqlDataSource.Create(Required("ConnectionStrings:Parvum")));
builder.Services.AddSingleton<IReviewStore, PostgresReviewStore>();
builder.Services.AddSingleton<IOpsStore, PostgresOpsStore>();
builder.Services.AddCors();

var app = builder.Build();

const string CookieName = "parvum_internal_session";
const string CsrfHeader = "X-Parvum-Internal";
var sessionTtl = TimeSpan.FromHours(12);

if (corsOrigins.Length > 0)
{
    // The internal app is hosted on a different origin from this API, and its session cookie
    // only travels cross-origin if the server names the origin and allows credentials.
    app.UseCors(policy => policy.WithOrigins(corsOrigins).AllowCredentials().AllowAnyHeader().AllowAnyMethod());
}

// The gate. It runs before routing decides anything, so a path that does not exist is refused
// the same way as one that does, and an unauthenticated caller cannot map the API by probing.
app.Use(async (context, next) =>
{
    var path = context.Request.Path.Value ?? "";
    if (!path.StartsWith("/internal/", StringComparison.Ordinal))
    {
        await next(context);
        return;
    }
    // Required on every internal request, including login. A form posted from another site
    // cannot set a custom header; the app's own fetch calls always do. That makes this a cheap
    // defence against cross-site request forgery.
    if (!context.Request.Headers.ContainsKey(CsrfHeader))
    {
        context.Response.StatusCode = StatusCodes.Status403Forbidden;
        return;
    }
    if (path is "/internal/auth/login" or "/internal/auth/logout")
    {
        await next(context);
        return;
    }
    var tokens = context.RequestServices.GetRequiredService<SessionToken>();
    if (!tokens.IsValid(context.Request.Cookies[CookieName]))
    {
        context.Response.StatusCode = StatusCodes.Status401Unauthorized;
        return;
    }
    await next(context);
});

// Liveness only: says the process is up, deliberately without touching the database.
app.MapGet("/healthz", () => Results.Text("ok"));

// ---- login -------------------------------------------------------------------------------

void SetSessionCookie(HttpResponse response, string value) =>
    response.Cookies.Append(CookieName, value, new CookieOptions
    {
        Path = "/",
        HttpOnly = true,
        Secure = cookieSecure,
        SameSite = cookieSameSite,
        MaxAge = value.Length == 0 ? TimeSpan.Zero : sessionTtl,
    });

var auth = app.MapGroup("/internal/auth");

auth.MapPost("/login", async (HttpContext context, SessionToken tokens) =>
{
    LoginRequest? request;
    try
    {
        // No JSON body at all is simply a login with no password, refused like any wrong one.
        request = !context.Request.HasJsonContentType() || context.Request.ContentLength == 0
            ? null
            : await context.Request.ReadFromJsonAsync<LoginRequest>(context.RequestAborted);
    }
    catch (JsonException)
    {
        return Results.BadRequest();
    }
    // Two live secrets compared directly, in constant time. Password hashing protects a stored
    // table of many users' passwords against a database leak; there is no such table here.
    var submitted = Encoding.UTF8.GetBytes(request?.Password ?? "");
    var ok = CryptographicOperations.FixedTimeEquals(password, submitted)
        | CryptographicOperations.FixedTimeEquals(demoPassword, submitted);
    if (!ok) return Results.Unauthorized();

    SetSessionCookie(context.Response, tokens.Issue(sessionTtl));
    return Results.NoContent();
});

auth.MapPost("/logout", (HttpContext context) =>
{
    SetSessionCookie(context.Response, "");
    return Results.NoContent();
});

// Reaching this handler means the gate above already accepted the cookie. It exists so the
// browser can ask "am I still logged in?" cheaply.
auth.MapGet("/session", () => Results.NoContent());

// ---- the review queue ----------------------------------------------------------------------

var alts = app.MapGroup("/internal/alts");

alts.MapGet("/queue", (string? status, IReviewStore store, CancellationToken ct) => store.ListAsync(status, ct));

alts.MapGet("/queue/{id:long}", async (long id, IReviewStore store, CancellationToken ct) =>
    await store.GetAsync(id, ct) is { } item ? Results.Ok(item) : Results.NotFound());

// The source PDF, so a reviewer reads the document beside the values extracted from it rather
// than taking the extraction on trust.
alts.MapGet("/documents/{fundId}/{document}", async (
    string fundId, string document, HttpContext context, IReviewStore store, CancellationToken ct) =>
{
    var content = await store.GetDocumentAsync(fundId, document, ct);
    if (content is null) return Results.NotFound();
    // The name goes into a header by concatenation, so it is reduced to characters that cannot
    // end the quoted value or start a new header line.
    var safeName = Regex.Replace(document, "[^A-Za-z0-9._-]", "_");
    context.Response.Headers.ContentDisposition = $"inline; filename=\"{safeName}\"";
    return Results.Bytes(content, "application/pdf");
});

static IResult ToResult(Decision decision, long id) => decision.Outcome switch
{
    DecisionOutcome.Decided => Results.Ok(decision.Item),
    DecisionOutcome.NotFound => Results.NotFound(),
    _ => Results.Conflict($"queue item {id} is already {decision.CurrentStatus}"),
};

// Accepts the extracted fields exactly as read.
alts.MapPost("/queue/{id:long}/approve", async (long id, IReviewStore store, CancellationToken ct) =>
    ToResult(await store.DecideAsync(id, "approved", null, ct), id));

// Records the reviewer's corrected fields in place of the extraction.
alts.MapPost("/queue/{id:long}/correct", async (long id, HttpContext context, IReviewStore store, CancellationToken ct) =>
{
    JsonElement body;
    try
    {
        body = await context.Request.ReadFromJsonAsync<JsonElement>(ct);
    }
    catch (JsonException)
    {
        return Results.BadRequest("correctedFields must be a non-empty object");
    }
    if (body.ValueKind != JsonValueKind.Object || !body.EnumerateObject().Any())
    {
        return Results.BadRequest("correctedFields must be a non-empty object");
    }
    return ToResult(await store.DecideAsync(id, "corrected", body.GetRawText(), ct), id);
});

// ---- operations views ----------------------------------------------------------------------

// These three describe the pipeline, not any one firm's clients, so every tenant schema holds
// the same rows. The tenant id is still validated: an unknown one never reaches the database.
var ops = app.MapGroup("/internal/tenants/{tenantId}");

async Task<IResult> InTenant<T>(string tenantId, Tenants tenants, Func<string, Task<IReadOnlyList<T>>> read) =>
    tenants.SchemaFor(tenantId) is { } schema ? Results.Ok(await read(schema)) : Results.NotFound();

ops.MapGet("/dq-metrics", (string tenantId, Tenants tenants, IOpsStore store, CancellationToken ct) =>
    InTenant(tenantId, tenants, schema => store.DqMetricsAsync(schema, ct)));

ops.MapGet("/cde-registry", (string tenantId, Tenants tenants, IOpsStore store, CancellationToken ct) =>
    InTenant(tenantId, tenants, schema => store.CdeRegistryAsync(schema, ct)));

ops.MapGet("/slo-attainment", (string tenantId, Tenants tenants, IOpsStore store, CancellationToken ct) =>
    InTenant(tenantId, tenants, schema => store.SloAttainmentAsync(schema, ct)));

app.Run();

/// <summary>Exposed so the test project can start the real application in memory.</summary>
public partial class Program;
