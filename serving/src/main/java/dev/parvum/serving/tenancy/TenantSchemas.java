package dev.parvum.serving.tenancy;

import io.agroal.api.AgroalDataSource;
import io.quarkus.logging.Log;
import io.quarkus.runtime.StartupEvent;
import jakarta.enterprise.context.ApplicationScoped;
import jakarta.enterprise.event.Observes;
import java.util.List;
import java.util.regex.Pattern;
import java.util.stream.Stream;
import org.eclipse.microprofile.config.inject.ConfigProperty;
import org.flywaydb.core.Flyway;

/**
 * Schema-per-tenant: each advisory firm gets its own Postgres schema with an identical layout, so
 * tenant isolation is a property of the schema boundary rather than of a WHERE clause every query
 * must remember. This bean applies the shared migration set to every tenant schema at startup.
 *
 * <p>The template schema carries no data; it exists so jOOQ code generation has one canonical
 * schema to read, with the tenant schema substituted at render time.
 */
@ApplicationScoped
public class TenantSchemas {

  public static final String TEMPLATE_SCHEMA = "tenant_template";

  /**
   * Schema names cannot be bound as JDBC parameters, so the tenant id becomes part of an SQL
   * identifier. Restricting it to this shape is what makes that safe.
   */
  private static final Pattern SAFE_TENANT_ID = Pattern.compile("[a-z][a-z0-9_]*");

  private final AgroalDataSource dataSource;
  private final List<String> tenantIds;

  public TenantSchemas(
      AgroalDataSource dataSource,
      @ConfigProperty(name = "parvum.tenants") List<String> tenantIds) {
    this.dataSource = dataSource;
    this.tenantIds = List.copyOf(tenantIds);
  }

  void onStart(@Observes StartupEvent event) {
    migrateAll();
  }

  /** Every schema this instance manages: the codegen template plus one per configured tenant. */
  public List<String> schemas() {
    return Stream.concat(
            Stream.of(TEMPLATE_SCHEMA), tenantIds.stream().map(TenantSchemas::schemaFor))
        .toList();
  }

  public List<String> tenantIds() {
    return tenantIds;
  }

  public static String schemaFor(String tenantId) {
    if (!SAFE_TENANT_ID.matcher(tenantId).matches()) {
      throw new IllegalArgumentException(
          "tenant id must match " + SAFE_TENANT_ID.pattern() + ": " + tenantId);
    }
    return "tenant_" + tenantId;
  }

  void migrateAll() {
    for (String schema : schemas()) {
      Flyway.configure()
          .dataSource(dataSource)
          .schemas(schema)
          .defaultSchema(schema)
          .createSchemas(true)
          .locations("classpath:db/migration")
          .load()
          .migrate();
      Log.infof("migrations up to date in schema %s", schema);
    }
  }
}
