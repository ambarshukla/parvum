package dev.parvum.serving.internal;

import io.agroal.api.AgroalDataSource;
import io.quarkus.logging.Log;
import io.quarkus.runtime.StartupEvent;
import jakarta.enterprise.context.ApplicationScoped;
import jakarta.enterprise.event.Observes;
import org.flywaydb.core.Flyway;

/**
 * Migrates the single non-tenant "internal" schema at startup — firm-ops data (the alts review
 * queue and its audit trail, D-050/D-051) that belongs to no one advisory firm, so it doesn't live
 * in a {@code tenant_*} schema the way everything {@link dev.parvum.serving.tenancy.TenantSchemas}
 * manages does. A separate migration location ({@code classpath:db/migration_internal}) keeps this
 * schema's DDL from ever being applied to a tenant schema by accident, and vice versa.
 */
@ApplicationScoped
public class InternalSchema {

  public static final String SCHEMA = "internal";

  private final AgroalDataSource dataSource;

  public InternalSchema(AgroalDataSource dataSource) {
    this.dataSource = dataSource;
  }

  void onStart(@Observes StartupEvent event) {
    migrate();
  }

  void migrate() {
    Flyway.configure()
        .dataSource(dataSource)
        .schemas(SCHEMA)
        .defaultSchema(SCHEMA)
        .createSchemas(true)
        .locations("classpath:db/migration_internal")
        .load()
        .migrate();
    Log.infof("migrations up to date in schema %s", SCHEMA);
  }
}
