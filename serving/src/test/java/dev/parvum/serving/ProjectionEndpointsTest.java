package dev.parvum.serving;

import static io.restassured.RestAssured.given;
import static org.hamcrest.Matchers.comparesEqualTo;
import static org.hamcrest.Matchers.contains;
import static org.hamcrest.Matchers.hasItem;
import static org.hamcrest.Matchers.is;
import static org.hamcrest.Matchers.not;

import io.agroal.api.AgroalDataSource;
import io.quarkus.test.junit.QuarkusTest;
import io.restassured.config.JsonConfig;
import io.restassured.config.RestAssuredConfig;
import io.restassured.path.json.config.JsonPathConfig;
import jakarta.inject.Inject;
import java.math.BigDecimal;
import java.sql.Connection;
import java.sql.Statement;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

/**
 * Drives the projection endpoints against seeded data. The exporter's real source is the lakehouse,
 * which the tests cannot reach, so each test seeds rows straight into a tenant schema and then
 * reads them back through the HTTP API — exercising the full path: routing, search_path, jOOQ,
 * JSON.
 */
@QuarkusTest
class ProjectionEndpointsTest {

  // JSON numbers come back as BigDecimal so money and weights compare exactly (by value).
  private static final RestAssuredConfig BIG_DECIMALS =
      RestAssuredConfig.config()
          .jsonConfig(
              JsonConfig.jsonConfig()
                  .numberReturnType(JsonPathConfig.NumberReturnType.BIG_DECIMAL));

  @Inject AgroalDataSource dataSource;

  @BeforeEach
  void seed() throws Exception {
    // Aldergate: the Hartwell family, with two wealth dates so "latest only" is testable, plus one
    // row in each of the other three projections.
    reset("tenant_aldergate");
    exec(
        "tenant_aldergate",
        """
        insert into client_wealth values
          ('2026-05-15','HART','Hartwell', 1000000.00, 0.00, 1000000.00, 1.1000, '2026-05-15', true, now()),
          ('2026-06-30','HART','Hartwell', 40000000.00, 1091835.83, 41091835.83, 1.1435, '2026-06-30', true, now());
        insert into asset_allocation values
          ('2026-06-30','HART','Hartwell','Equity', 40000000.00, 0.9734312757, now()),
          ('2026-06-30','HART','Hartwell','Cash',    1091835.83, 0.0265687243, now());
        insert into income values
          ('HART','Hartwell','2026-06-01','DIVIDEND', 125000.00, 4, now());
        insert into top_holdings values
          ('2026-06-30','HART','Hartwell', 1, 'Apple Inc','US-CUSIP','037833100','Equity', 8000000.00, 0.20, now());
        """);

    // Stonefield: Okafor. Only wealth is needed here — enough to prove one tenant never sees the
    // other's rows.
    reset("tenant_stonefield");
    exec(
        "tenant_stonefield",
        """
        insert into client_wealth values
          ('2026-06-30','OKAF','Okafor', 2800000.00, 67257.58, 2867257.58, 1.1435, '2026-06-30', true, now());
        """);
  }

  @Test
  void wealthReturnsTheLatestDateOnlyForTheTenantsOwnClients() {
    given()
        .config(BIG_DECIMALS)
        .when()
        .get("/tenants/aldergate/wealth")
        .then()
        .statusCode(200)
        .body("size()", is(1))
        .body("[0].clientId", is("HART"))
        .body("[0].asOf", is("2026-06-30"))
        .body("[0].totalWealthUsd", comparesEqualTo(new BigDecimal("41091835.83")))
        .body("[0].booksReconcile", is(true));
  }

  @Test
  void eachTenantSeesOnlyItsOwnData() {
    given()
        .when()
        .get("/tenants/aldergate/wealth")
        .then()
        .statusCode(200)
        .body("clientId", contains("HART"))
        .body("clientId", not(hasItem("OKAF")));

    given()
        .when()
        .get("/tenants/stonefield/wealth")
        .then()
        .statusCode(200)
        .body("clientId", contains("OKAF"))
        .body("clientId", not(hasItem("HART")));
  }

  @Test
  void allocationIncomeAndHoldingsAreServedAndMapped() {
    given()
        .when()
        .get("/tenants/aldergate/allocation")
        .then()
        .statusCode(200)
        .body("size()", is(2))
        .body("assetClass", contains("Equity", "Cash")); // ordered by weight desc

    given()
        .when()
        .get("/tenants/aldergate/income")
        .then()
        .statusCode(200)
        .body("size()", is(1))
        .body("[0].type", is("DIVIDEND"))
        .body("[0].movements", is(4));

    given()
        .when()
        .get("/tenants/aldergate/holdings")
        .then()
        .statusCode(200)
        .body("size()", is(1))
        .body("[0].securityName", is("Apple Inc"))
        .body("[0].rank", is(1));
  }

  @Test
  void unknownOrMalformedTenantsAre404() {
    given().when().get("/tenants/ghost/wealth").then().statusCode(404);
    // Uppercase cannot be a schema id (see TenantSchemas.SAFE_TENANT_ID); it is not in the tenant
    // list either, so it is rejected before any identifier is built.
    given().when().get("/tenants/Aldergate/wealth").then().statusCode(404);
  }

  private void reset(String schema) throws Exception {
    exec(schema, "truncate table client_wealth, asset_allocation, income, top_holdings");
  }

  /** Runs semicolon-separated statements inside {@code schema} via a temporary search_path. */
  private void exec(String schema, String sql) throws Exception {
    try (Connection connection = dataSource.getConnection();
        Statement statement = connection.createStatement()) {
      statement.execute("set search_path to \"" + schema + "\"");
      statement.execute(sql);
    }
  }
}
