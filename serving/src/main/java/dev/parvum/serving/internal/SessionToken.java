package dev.parvum.serving.internal;

import jakarta.enterprise.context.ApplicationScoped;
import java.nio.charset.StandardCharsets;
import java.security.GeneralSecurityException;
import java.security.MessageDigest;
import java.time.Duration;
import java.time.Instant;
import java.util.Base64;
import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import org.eclipse.microprofile.config.inject.ConfigProperty;

/**
 * Issues and verifies signed session tokens for the internal app's single shared login. Stateless
 * by design (no session table): the token is just an expiry timestamp, HMAC-signed with a
 * server-held secret, so verification never touches the database and a pooled connection carries no
 * session state between requests.
 */
@ApplicationScoped
public class SessionToken {

  private static final String ALGORITHM = "HmacSHA256";
  private static final Base64.Encoder ENCODER = Base64.getUrlEncoder().withoutPadding();

  private final byte[] secretKey;

  public SessionToken(@ConfigProperty(name = "parvum.internal.session-secret") String secret) {
    this.secretKey = secret.getBytes(StandardCharsets.UTF_8);
  }

  public String issue(Duration ttl) {
    String payload = Long.toString(Instant.now().plus(ttl).getEpochSecond());
    return payload + "." + sign(payload);
  }

  /** True if the token's signature is intact and its expiry has not passed. */
  public boolean isValid(String token) {
    if (token == null) {
      return false;
    }
    int dot = token.indexOf('.');
    if (dot < 0) {
      return false;
    }
    String payload = token.substring(0, dot);
    byte[] expected = sign(payload).getBytes(StandardCharsets.UTF_8);
    byte[] actual = token.substring(dot + 1).getBytes(StandardCharsets.UTF_8);
    if (!MessageDigest.isEqual(expected, actual)) {
      return false;
    }
    try {
      return Instant.now().getEpochSecond() < Long.parseLong(payload);
    } catch (NumberFormatException e) {
      return false;
    }
  }

  private String sign(String payload) {
    try {
      Mac mac = Mac.getInstance(ALGORITHM);
      mac.init(new SecretKeySpec(secretKey, ALGORITHM));
      return ENCODER.encodeToString(mac.doFinal(payload.getBytes(StandardCharsets.UTF_8)));
    } catch (GeneralSecurityException e) {
      throw new IllegalStateException("failed to sign session token", e);
    }
  }
}
