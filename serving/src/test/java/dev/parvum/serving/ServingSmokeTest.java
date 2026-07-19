package dev.parvum.serving;

import static io.restassured.RestAssured.given;
import static org.hamcrest.CoreMatchers.is;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import dev.parvum.serving.tenancy.TenantSchemas;
import io.agroal.api.AgroalDataSource;
import io.quarkus.test.junit.QuarkusTest;
import jakarta.inject.Inject;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.util.List;
import org.junit.jupiter.api.Test;

/**
 * Boots the whole application against a throwaway Postgres (Quarkus Dev Services), so a green run
 * proves: the app starts, connects, migrates every tenant schema, and reports healthy.
 */
@QuarkusTest
class ServingSmokeTest {

  private static final List<String> PROJECTION_TABLES =
      List.of(
          "client_wealth",
          "asset_allocation",
          "income",
          "top_holdings",
          "ownership",
          "performance",
          "performance_summary",
          "dq_metrics");

  @Inject AgroalDataSource dataSource;
  @Inject TenantSchemas tenantSchemas;

  @Test
  void readinessReportsUpOnceMigrationsRan() {
    given().when().get("/q/health/ready").then().statusCode(200).body("status", is("UP"));
  }

  @Test
  void everyTenantSchemaHasEveryProjectionTable() throws Exception {
    assertEquals(
        List.of("tenant_template", "tenant_aldergate", "tenant_stonefield"),
        tenantSchemas.schemas());
    try (Connection connection = dataSource.getConnection()) {
      for (String schema : tenantSchemas.schemas()) {
        for (String table : PROJECTION_TABLES) {
          assertTrue(tableExists(connection, schema, table), schema + "." + table + " is missing");
        }
      }
    }
  }

  @Test
  void tenantIdsThatCouldEscapeAnIdentifierAreRejected() {
    assertThrows(IllegalArgumentException.class, () -> TenantSchemas.schemaFor("bad\"id"));
    assertThrows(IllegalArgumentException.class, () -> TenantSchemas.schemaFor("Tenant"));
    assertThrows(IllegalArgumentException.class, () -> TenantSchemas.schemaFor(""));
  }

  private static boolean tableExists(Connection connection, String schema, String table)
      throws Exception {
    try (PreparedStatement statement =
        connection.prepareStatement(
            "select 1 from information_schema.tables where table_schema = ? and table_name = ?")) {
      statement.setString(1, schema);
      statement.setString(2, table);
      try (ResultSet resultSet = statement.executeQuery()) {
        return resultSet.next();
      }
    }
  }
}
