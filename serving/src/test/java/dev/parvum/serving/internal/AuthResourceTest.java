package dev.parvum.serving.internal;

import static io.restassured.RestAssured.given;

import io.quarkus.test.junit.QuarkusTest;
import io.restassured.http.ContentType;
import org.junit.jupiter.api.Test;

@QuarkusTest
class AuthResourceTest {

  private static final String CSRF_HEADER = "X-Parvum-Internal";
  private static final String COOKIE = "parvum_internal_session";

  @Test
  void rejectsRequestsMissingTheCsrfHeader() {
    given().when().get("/internal/auth/session").then().statusCode(403);
  }

  @Test
  void rejectsAnUnauthenticatedSession() {
    given().header(CSRF_HEADER, "1").when().get("/internal/auth/session").then().statusCode(401);
  }

  @Test
  void rejectsTheWrongPassword() {
    given()
        .header(CSRF_HEADER, "1")
        .contentType(ContentType.JSON)
        .body("{\"password\":\"nope\"}")
        .when()
        .post("/internal/auth/login")
        .then()
        .statusCode(401);
  }

  @Test
  void logsInAndReachesAnAuthenticatedEndpointWithTheSessionCookie() {
    String cookie =
        given()
            .header(CSRF_HEADER, "1")
            .contentType(ContentType.JSON)
            .body("{\"password\":\"test-only-password\"}")
            .when()
            .post("/internal/auth/login")
            .then()
            .statusCode(204)
            .extract()
            .cookie(COOKIE);

    given()
        .header(CSRF_HEADER, "1")
        .cookie(COOKIE, cookie)
        .when()
        .get("/internal/auth/session")
        .then()
        .statusCode(204);
  }

  // Sessions are stateless (no session table, see SessionToken) — logout can only tell the
  // browser to drop its cookie (maxAge=0), not revoke the token server-side. A replayed token
  // therefore still validates until it expires; that trade is recorded in D-046.
  @Test
  void logoutTellsTheBrowserToDropTheCookie() {
    given()
        .header(CSRF_HEADER, "1")
        .when()
        .post("/internal/auth/logout")
        .then()
        .statusCode(204)
        .cookie(COOKIE, org.hamcrest.Matchers.is(""));
  }
}
