using System.Globalization;
using System.Security.Cryptography;
using System.Text;

namespace Parvum.Internal.Api;

/// <summary>
/// Issues and verifies the internal app's session token.
///
/// The format is fixed by the Java service and reproduced here byte for byte:
/// <c>&lt;expiry as Unix seconds&gt;.&lt;base64url(HMAC-SHA256(expiry)), no padding&gt;</c>, keyed
/// with the UTF-8 bytes of a shared secret. Matching it exactly is what lets both services sit
/// behind one hostname: a cookie issued by either is accepted by the other, so a request can be
/// routed to whichever implementation owns that path without the user logging in twice.
///
/// Stateless on purpose. There is no session table, so verifying a request never touches the
/// database.
/// </summary>
public sealed class SessionToken(string secret, TimeProvider clock)
{
    private readonly byte[] _key = Encoding.UTF8.GetBytes(secret);

    public string Issue(TimeSpan ttl)
    {
        var payload = clock.GetUtcNow().Add(ttl).ToUnixTimeSeconds().ToString(CultureInfo.InvariantCulture);
        return $"{payload}.{Sign(payload)}";
    }

    /// <summary>True if the signature is intact and the expiry has not passed.</summary>
    public bool IsValid(string? token)
    {
        if (token is null) return false;
        var dot = token.IndexOf('.');
        if (dot < 0) return false;

        var payload = token[..dot];
        var expected = Encoding.UTF8.GetBytes(Sign(payload));
        var actual = Encoding.UTF8.GetBytes(token[(dot + 1)..]);
        // Constant-time: comparing signatures with == would leak, through timing, how many
        // leading characters of a forged signature were correct.
        if (!CryptographicOperations.FixedTimeEquals(expected, actual)) return false;

        return long.TryParse(payload, NumberStyles.AllowLeadingSign, CultureInfo.InvariantCulture, out var expiry)
            && clock.GetUtcNow().ToUnixTimeSeconds() < expiry;
    }

    private string Sign(string payload)
    {
        var mac = HMACSHA256.HashData(_key, Encoding.UTF8.GetBytes(payload));
        // URL-safe alphabet without padding, which is what java.util.Base64's URL encoder
        // produces with withoutPadding().
        return Convert.ToBase64String(mac).TrimEnd('=').Replace('+', '-').Replace('/', '_');
    }
}
