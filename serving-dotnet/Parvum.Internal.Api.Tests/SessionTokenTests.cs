using Xunit;

namespace Parvum.Internal.Api.Tests;

public sealed class FixedClock(DateTimeOffset now) : TimeProvider
{
    public DateTimeOffset Now { get; set; } = now;

    public override DateTimeOffset GetUtcNow() => Now;
}

public class SessionTokenTests
{
    private const string Secret = "dev-and-test-only-signing-key-never-used-in-prod";
    private static readonly DateTimeOffset Noon = new(2026, 1, 1, 12, 0, 0, TimeSpan.Zero);

    [Fact]
    public void A_token_it_issued_is_valid_until_it_expires()
    {
        var clock = new FixedClock(Noon);
        var tokens = new SessionToken(Secret, clock);
        var token = tokens.Issue(TimeSpan.FromHours(12));

        Assert.True(tokens.IsValid(token));

        clock.Now = Noon.AddHours(12);
        Assert.False(tokens.IsValid(token));
    }

    /// <summary>
    /// The signature below was computed outside this codebase (HMAC-SHA256 of the payload under
    /// the secret, URL-safe base64, no padding), which is the format the Java service issues.
    /// If this test fails, a cookie from one service would stop working on the other.
    /// </summary>
    [Fact]
    public void It_accepts_a_token_in_the_format_the_Java_service_issues()
    {
        var tokens = new SessionToken(Secret, new FixedClock(Noon));

        Assert.True(tokens.IsValid("4102444800.WtPt6QsjEJSo0L-DIdc2iM10wLffVjvAxDvrHcR10_0"));
    }

    [Fact]
    public void Moving_the_expiry_later_breaks_the_signature()
    {
        var tokens = new SessionToken(Secret, new FixedClock(Noon));

        Assert.False(tokens.IsValid("4102444801.WtPt6QsjEJSo0L-DIdc2iM10wLffVjvAxDvrHcR10_0"));
    }

    [Fact]
    public void A_token_signed_with_another_secret_is_rejected()
    {
        var clock = new FixedClock(Noon);
        var forged = new SessionToken("some-other-secret", clock).Issue(TimeSpan.FromHours(1));

        Assert.False(new SessionToken(Secret, clock).IsValid(forged));
    }

    [Theory]
    [InlineData(null)]
    [InlineData("")]
    [InlineData("no-dot-at-all")]
    [InlineData(".")]
    [InlineData("not-a-number.abc")]
    public void Malformed_tokens_are_rejected_rather_than_thrown_on(string? token)
    {
        Assert.False(new SessionToken(Secret, new FixedClock(Noon)).IsValid(token));
    }
}

public class TenantsTests
{
    private static readonly Tenants Configured = Tenants.Parse("aldergate, stonefield");

    [Fact]
    public void A_configured_tenant_maps_to_its_own_schema()
    {
        Assert.Equal("tenant_aldergate", Configured.SchemaFor("aldergate"));
        Assert.Equal("tenant_stonefield", Configured.SchemaFor("stonefield"));
    }

    [Theory]
    [InlineData("unknown")]
    [InlineData("ALDERGATE")]
    [InlineData("")]
    [InlineData("aldergate\"; drop schema internal; --")]
    public void Anything_else_has_no_schema(string tenantId)
    {
        Assert.Null(Configured.SchemaFor(tenantId));
    }

    /// <summary>
    /// Being on the list is not enough. A misconfigured tenant id that could break out of a
    /// quoted identifier must still never become part of a statement.
    /// </summary>
    [Fact]
    public void A_listed_id_with_an_unsafe_shape_still_has_no_schema()
    {
        var careless = new Tenants(["bad\"name", "Upper", "9lives"]);

        Assert.Null(careless.SchemaFor("bad\"name"));
        Assert.Null(careless.SchemaFor("Upper"));
        Assert.Null(careless.SchemaFor("9lives"));
    }
}
