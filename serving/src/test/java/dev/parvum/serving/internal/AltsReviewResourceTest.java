package dev.parvum.serving.internal;

import static io.restassured.RestAssured.given;
import static org.hamcrest.Matchers.is;
import static org.hamcrest.Matchers.notNullValue;
import static org.hamcrest.Matchers.nullValue;

import io.agroal.api.AgroalDataSource;
import io.quarkus.test.junit.QuarkusTest;
import io.restassured.http.ContentType;
import jakarta.inject.Inject;
import java.sql.Connection;
import java.sql.Statement;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

/**
 * Drives the alts review queue: list, detail, approve, correct, and the audit trail each leaves.
 */
@QuarkusTest
class AltsReviewResourceTest {

  private static final String CSRF_HEADER = "X-Parvum-Internal";
  private static final String COOKIE = "parvum_internal_session";

  @Inject AgroalDataSource dataSource;

  @BeforeEach
  void seed() throws Exception {
    exec(
        "truncate table alts_review_audit, alts_review_queue, alts_documents"
            + " restart identity cascade");
    exec(
        """
        insert into alts_review_queue
          (fund_id, document, doc_type, sequence_number, period_end, extracted_fields,
           confidence, validation_notes, status, loaded_at)
        values
          ('FUND-PE01', 'capital_call_02.pdf', 'capital_call', 2, null,
           '{"call_amount": "100000.00", "cumulative_called": "1751000.00"}',
           0.700, 'cumulative_called 1751000.00 != running sum 1750000.00', 'pending', now()),
          ('FUND-PE01', 'capital_call_03.pdf', 'capital_call', 3, null,
           '{"call_amount": "750000.00"}', 0.900, null, 'pending', now());
        """);
  }

  @Test
  void listingRequiresAValidSession() {
    given().header(CSRF_HEADER, "1").when().get("/internal/alts/queue").then().statusCode(401);
  }

  @Test
  void listsSeededQueueItems() {
    String cookie = login();
    given()
        .header(CSRF_HEADER, "1")
        .cookie(COOKIE, cookie)
        .when()
        .get("/internal/alts/queue")
        .then()
        .statusCode(200)
        .body("size()", is(2))
        .body("status", org.hamcrest.Matchers.everyItem(is("pending")));
  }

  @Test
  void filtersByStatus() {
    String cookie = login();
    given()
        .header(CSRF_HEADER, "1")
        .cookie(COOKIE, cookie)
        .queryParam("status", "approved")
        .when()
        .get("/internal/alts/queue")
        .then()
        .statusCode(200)
        .body("size()", is(0));
  }

  @Test
  void detailReturns404ForAnUnknownId() {
    String cookie = login();
    given()
        .header(CSRF_HEADER, "1")
        .cookie(COOKIE, cookie)
        .when()
        .get("/internal/alts/queue/999999")
        .then()
        .statusCode(404);
  }

  @Test
  void approvingCopiesExtractedFieldsAndWritesAnAuditRow() {
    String cookie = login();
    long id = firstQueueId();

    given()
        .header(CSRF_HEADER, "1")
        .cookie(COOKIE, cookie)
        .when()
        .post("/internal/alts/queue/{id}/approve", id)
        .then()
        .statusCode(200)
        .body("status", is("approved"))
        .body(
            "decidedFields",
            is("{\"call_amount\": \"100000.00\", \"cumulative_called\": \"1751000.00\"}"))
        .body("decidedAt", notNullValue());

    assertAuditRow(id, "approved");
  }

  @Test
  void correctingStoresTheReviewersFieldsAndWritesAnAuditRow() {
    String cookie = login();
    long id = firstQueueId();

    given()
        .header(CSRF_HEADER, "1")
        .cookie(COOKIE, cookie)
        .contentType(ContentType.JSON)
        .body("{\"call_amount\": \"1000000.00\", \"cumulative_called\": \"1750000.00\"}")
        .when()
        .post("/internal/alts/queue/{id}/correct", id)
        .then()
        .statusCode(200)
        .body("status", is("corrected"))
        .body("decidedAt", notNullValue());

    assertAuditRow(id, "corrected");
  }

  @Test
  void correctingWithAnEmptyBodyIsRejected() {
    String cookie = login();
    long id = firstQueueId();

    given()
        .header(CSRF_HEADER, "1")
        .cookie(COOKIE, cookie)
        .contentType(ContentType.JSON)
        .body("{}")
        .when()
        .post("/internal/alts/queue/{id}/correct", id)
        .then()
        .statusCode(400);
  }

  @Test
  void aDecidedItemCannotBeDecidedAgain() {
    String cookie = login();
    long id = firstQueueId();

    given()
        .header(CSRF_HEADER, "1")
        .cookie(COOKIE, cookie)
        .post("/internal/alts/queue/{id}/approve", id);

    given()
        .header(CSRF_HEADER, "1")
        .cookie(COOKIE, cookie)
        .when()
        .post("/internal/alts/queue/{id}/approve", id)
        .then()
        .statusCode(409);
  }

  @Test
  void anUndecidedItemHasNoDecidedFieldsYet() {
    String cookie = login();
    given()
        .header(CSRF_HEADER, "1")
        .cookie(COOKIE, cookie)
        .when()
        .get("/internal/alts/queue")
        .then()
        .statusCode(200)
        .body("decidedFields", org.hamcrest.Matchers.everyItem(nullValue()));
  }

  @Test
  void servesTheSourcePdfBytesForADocument() throws Exception {
    // decode(...) is the literal bytes "%PDF-1.4" — a real (tiny) PDF header,
    // so this also proves bytea round-trips without any encoding applied.
    exec(
        """
        insert into alts_documents (fund_id, document, content, byte_size, sha256)
        values ('FUND-PE01', 'capital_call_02.pdf',
                decode('255044462d312e34', 'hex'), 8, 'abc123');
        """);
    String cookie = login();

    byte[] body =
        given()
            .header(CSRF_HEADER, "1")
            .cookie(COOKIE, cookie)
            .when()
            .get("/internal/alts/documents/{fundId}/{document}", "FUND-PE01", "capital_call_02.pdf")
            .then()
            .statusCode(200)
            .contentType("application/pdf")
            .extract()
            .asByteArray();

    org.junit.jupiter.api.Assertions.assertArrayEquals(
        "%PDF-1.4".getBytes(java.nio.charset.StandardCharsets.US_ASCII), body);
  }

  @Test
  void anUnknownDocumentIs404() {
    String cookie = login();
    given()
        .header(CSRF_HEADER, "1")
        .cookie(COOKIE, cookie)
        .when()
        .get("/internal/alts/documents/{fundId}/{document}", "FUND-NOPE", "missing.pdf")
        .then()
        .statusCode(404);
  }

  @Test
  void theSourcePdfStillNeedsASession() {
    given()
        .header(CSRF_HEADER, "1")
        .when()
        .get("/internal/alts/documents/{fundId}/{document}", "FUND-PE01", "capital_call_02.pdf")
        .then()
        .statusCode(401);
  }

  private long firstQueueId() {
    String cookie = login();
    return given()
        .header(CSRF_HEADER, "1")
        .cookie(COOKIE, cookie)
        .queryParam("status", "pending")
        .when()
        .get("/internal/alts/queue")
        .then()
        .extract()
        .jsonPath()
        .getLong("find { it.document == 'capital_call_02.pdf' }.id");
  }

  private void assertAuditRow(long queueId, String action) {
    try (Connection connection = dataSource.getConnection();
        Statement statement = connection.createStatement()) {
      statement.execute("set search_path to \"internal\"");
      var rs =
          statement.executeQuery(
              "select action from alts_review_audit where queue_id = " + queueId);
      org.junit.jupiter.api.Assertions.assertTrue(rs.next(), "expected an audit row");
      org.junit.jupiter.api.Assertions.assertEquals(action, rs.getString("action"));
      org.junit.jupiter.api.Assertions.assertFalse(rs.next(), "expected exactly one audit row");
    } catch (Exception e) {
      throw new RuntimeException(e);
    }
  }

  private String login() {
    return given()
        .header(CSRF_HEADER, "1")
        .contentType(ContentType.JSON)
        .body("{\"password\":\"test-only-password\"}")
        .when()
        .post("/internal/auth/login")
        .then()
        .statusCode(204)
        .extract()
        .cookie(COOKIE);
  }

  private void exec(String sql) throws Exception {
    try (Connection connection = dataSource.getConnection();
        Statement statement = connection.createStatement()) {
      statement.execute("set search_path to \"internal\"");
      statement.execute(sql);
    }
  }
}
