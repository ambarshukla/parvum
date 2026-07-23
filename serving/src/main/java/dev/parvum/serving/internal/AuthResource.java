package dev.parvum.serving.internal;

import jakarta.ws.rs.Consumes;
import jakarta.ws.rs.GET;
import jakarta.ws.rs.NotAuthorizedException;
import jakarta.ws.rs.POST;
import jakarta.ws.rs.Path;
import jakarta.ws.rs.Produces;
import jakarta.ws.rs.core.MediaType;
import jakarta.ws.rs.core.NewCookie;
import jakarta.ws.rs.core.Response;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.Duration;
import org.eclipse.microprofile.config.inject.ConfigProperty;

/**
 * The internal app's login. Two credentials are accepted, both checked by direct constant-time
 * equality rather than a hashed-password lookup (bcrypt earns its keep defending a stored table of
 * many hashes against a database leak, which doesn't apply to comparing against one or two live
 * secret values): the real password (an SSM-stored secret in prod, mirroring the RDS password's
 * trust model — see D-046), and a public demo password (D-059) that a shareable link uses to log a
 * portfolio viewer in without anyone having to send it out of band.
 */
@Path("/internal/auth")
@Produces(MediaType.APPLICATION_JSON)
public class AuthResource {

  private static final String COOKIE_NAME = "parvum_internal_session";
  private static final Duration SESSION_TTL = Duration.ofHours(12);

  private final SessionToken sessionToken;
  private final String password;
  private final String demoPassword;
  private final boolean cookieSecure;
  private final NewCookie.SameSite cookieSameSite;

  public AuthResource(
      SessionToken sessionToken,
      @ConfigProperty(name = "parvum.internal.password") String password,
      @ConfigProperty(name = "parvum.internal.demo-password") String demoPassword,
      @ConfigProperty(name = "parvum.internal.cookie-secure", defaultValue = "true")
          boolean cookieSecure,
      @ConfigProperty(name = "parvum.internal.cookie-samesite", defaultValue = "None")
          String cookieSameSite) {
    this.sessionToken = sessionToken;
    this.password = password;
    this.demoPassword = demoPassword;
    this.cookieSecure = cookieSecure;
    this.cookieSameSite = NewCookie.SameSite.valueOf(cookieSameSite.toUpperCase());
  }

  public record LoginRequest(String password) {}

  @POST
  @Path("/login")
  @Consumes(MediaType.APPLICATION_JSON)
  public Response login(LoginRequest request) {
    String submitted = request == null || request.password() == null ? "" : request.password();
    byte[] actual = submitted.getBytes(StandardCharsets.UTF_8);
    boolean ok =
        MessageDigest.isEqual(password.getBytes(StandardCharsets.UTF_8), actual)
            || MessageDigest.isEqual(demoPassword.getBytes(StandardCharsets.UTF_8), actual);
    if (!ok) {
      throw new NotAuthorizedException("invalid password");
    }
    return Response.noContent().cookie(sessionCookie(sessionToken.issue(SESSION_TTL))).build();
  }

  @POST
  @Path("/logout")
  public Response logout() {
    return Response.noContent().cookie(sessionCookie("")).build();
  }

  /**
   * Reaching this method at all means {@link InternalAuthFilter} already accepted the request's
   * cookie — its only job is to give the frontend a cheap way to ask "am I still logged in?"
   * without repeating that check itself.
   */
  @GET
  @Path("/session")
  public Response session() {
    return Response.noContent().build();
  }

  private NewCookie sessionCookie(String value) {
    return new NewCookie.Builder(COOKIE_NAME)
        .value(value)
        .path("/")
        .httpOnly(true)
        .secure(cookieSecure)
        .sameSite(cookieSameSite)
        .maxAge(value.isEmpty() ? 0 : (int) SESSION_TTL.toSeconds())
        .build();
  }
}
