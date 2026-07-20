package dev.parvum.serving.internal;

import jakarta.annotation.Priority;
import jakarta.ws.rs.Priorities;
import jakarta.ws.rs.container.ContainerRequestContext;
import jakarta.ws.rs.container.ContainerRequestFilter;
import jakarta.ws.rs.container.PreMatching;
import jakarta.ws.rs.core.Cookie;
import jakarta.ws.rs.core.Response;
import jakarta.ws.rs.ext.Provider;
import java.util.Set;

/**
 * Gates every {@code /internal/**} endpoint behind a valid session cookie, except the login/logout
 * endpoints that establish or clear one.
 *
 * <p>A custom header is required on every {@code /internal/**} request, including the exempt ones —
 * a cheap CSRF mitigation, since a cross-site form submission cannot set a custom header but
 * same-origin fetch calls from the internal app's own code always do (see {@code api.ts}).
 */
@Provider
@PreMatching
@Priority(Priorities.AUTHENTICATION)
public class InternalAuthFilter implements ContainerRequestFilter {

  private static final String COOKIE_NAME = "parvum_internal_session";
  private static final String CSRF_HEADER = "X-Parvum-Internal";
  private static final Set<String> AUTH_EXEMPT =
      Set.of("internal/auth/login", "internal/auth/logout");

  private final SessionToken sessionToken;

  public InternalAuthFilter(SessionToken sessionToken) {
    this.sessionToken = sessionToken;
  }

  @Override
  public void filter(ContainerRequestContext ctx) {
    // getPath()'s leading slash is spec-optional and this engine includes it, so strip it
    // rather than rely on a convention that could vary by implementation.
    String path = ctx.getUriInfo().getPath();
    if (path.startsWith("/")) {
      path = path.substring(1);
    }
    if (!path.startsWith("internal/")) {
      return;
    }
    if (ctx.getHeaderString(CSRF_HEADER) == null) {
      ctx.abortWith(Response.status(Response.Status.FORBIDDEN).build());
      return;
    }
    if (AUTH_EXEMPT.contains(path)) {
      return;
    }
    Cookie cookie = ctx.getCookies().get(COOKIE_NAME);
    if (cookie == null || !sessionToken.isValid(cookie.getValue())) {
      ctx.abortWith(Response.status(Response.Status.UNAUTHORIZED).build());
    }
  }
}
