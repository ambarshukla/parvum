package dev.parvum.serving.persistence;

import io.agroal.api.AgroalDataSource;
import jakarta.enterprise.context.ApplicationScoped;
import jakarta.enterprise.inject.Produces;
import org.jooq.DSLContext;
import org.jooq.SQLDialect;
import org.jooq.conf.Settings;
import org.jooq.impl.DSL;

/**
 * Makes a single application-scoped {@link DSLContext} available for injection, built over the
 * Quarkus-managed Agroal connection pool.
 *
 * <p>{@code renderSchema=false} is the load-bearing setting: the generated tables carry no schema
 * qualifier, so every query renders a bare table name (e.g. {@code client_wealth}). Which tenant's
 * table that resolves to is decided by the connection's {@code search_path}, set per request in
 * {@link dev.parvum.serving.tenancy.TenantQuery}. That is what lets one generated set of classes
 * serve every tenant schema.
 */
@ApplicationScoped
public class JooqProducer {

  @Produces
  @ApplicationScoped
  public DSLContext dslContext(AgroalDataSource dataSource) {
    Settings settings = new Settings().withRenderSchema(false);
    return DSL.using(dataSource, SQLDialect.POSTGRES, settings);
  }
}
