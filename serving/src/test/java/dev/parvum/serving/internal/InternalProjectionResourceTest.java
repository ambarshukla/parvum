package dev.parvum.serving.internal;

import static io.restassured.RestAssured.given;
import static org.hamcrest.Matchers.comparesEqualTo;
import static org.hamcrest.Matchers.is;
import static org.hamcrest.Matchers.nullValue;

import io.agroal.api.AgroalDataSource;
import io.quarkus.test.junit.QuarkusTest;
import io.restassured.config.JsonConfig;
import io.restassured.config.RestAssuredConfig;
import io.restassured.http.ContentType;
import io.restassured.path.json.config.JsonPathConfig;
import jakarta.inject.Inject;
import java.math.BigDecimal;
import java.sql.Connection;
import java.sql.Statement;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

/**
 * Drives {@code /internal/tenants/{id}/dq-metrics} — moved here from the public {@code
 * ProjectionEndpointsTest} when the endpoint moved behind auth (D-046).
 */
@QuarkusTest
class InternalProjectionResourceTest {

  private static final String CSRF_HEADER = "X-Parvum-Internal";
  private static final RestAssuredConfig BIG_DECIMALS =
      RestAssuredConfig.config()
          .jsonConfig(
              JsonConfig.jsonConfig()
                  .numberReturnType(JsonPathConfig.NumberReturnType.BIG_DECIMAL));

  @Inject AgroalDataSource dataSource;

  @BeforeEach
  void seed() throws Exception {
    exec(
        "tenant_aldergate",
        "truncate table client_wealth, asset_allocation, income, top_holdings, ownership, "
            + "performance, performance_summary, dq_metrics");
    exec(
        "tenant_aldergate",
        """
        insert into dq_metrics values
          ('2026-06-30','completeness','files_landed_rate', 1.000000, true, '11 of 11 expected files parsed', now()),
          ('2026-06-30','accuracy','holdings_cross_format_match_rate', 0.950000, false, '3 cross-format findings across 60 positions', now()),
          ('2026-06-30','exceptions','holdings_findings_count', 3.000000, null, '3 cross-format findings', now());
        """);
  }

  @Test
  void requiresAValidSessionEvenWithTheCsrfHeader() {
    given()
        .header(CSRF_HEADER, "1")
        .when()
        .get("/internal/tenants/aldergate/dq-metrics")
        .then()
        .statusCode(401);
  }

  @Test
  void dqMetricsExposesTheRollupIncludingNullPassedForExceptions() {
    String cookie = login();

    given()
        .config(BIG_DECIMALS)
        .header(CSRF_HEADER, "1")
        .cookie("parvum_internal_session", cookie)
        .when()
        .get("/internal/tenants/aldergate/dq-metrics")
        .then()
        .statusCode(200)
        .body("size()", is(3))
        // Ordered by dimension, metric, as_of: accuracy < completeness < exceptions.
        .body("[0].dimension", is("accuracy"))
        .body("[0].metric", is("holdings_cross_format_match_rate"))
        .body("[0].value", comparesEqualTo(new BigDecimal("0.950000")))
        .body("[0].passed", is(false))
        .body("[1].dimension", is("completeness"))
        .body("[1].passed", is(true))
        .body("[2].dimension", is("exceptions"))
        .body("[2].passed", is(nullValue()))
        .body("[2].detail", is("3 cross-format findings"));
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
        .cookie("parvum_internal_session");
  }

  private void exec(String schema, String sql) throws Exception {
    try (Connection connection = dataSource.getConnection();
        Statement statement = connection.createStatement()) {
      statement.execute("set search_path to \"" + schema + "\"");
      statement.execute(sql);
    }
  }
}
