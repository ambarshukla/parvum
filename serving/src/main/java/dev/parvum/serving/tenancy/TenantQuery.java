package dev.parvum.serving.tenancy;

import jakarta.enterprise.context.ApplicationScoped;
import jakarta.ws.rs.NotFoundException;
import java.util.function.Function;
import org.jooq.DSLContext;
import org.jooq.impl.DSL;

/**
 * Runs a query against a single tenant's schema. Every read the API serves goes through here, so
 * tenant isolation is enforced in one place rather than trusted to each endpoint.
 *
 * <p>The routing itself is a {@code SET LOCAL search_path} issued as the first statement of a
 * transaction. {@code LOCAL} scopes it to that transaction, so it is reset automatically when the
 * transaction ends — a pooled connection can never carry one tenant's search_path into the next
 * request. The schema name is both validated in shape ({@link TenantSchemas#schemaFor}) and
 * rendered as a quoted identifier ({@link DSL#name}), so an unexpected tenant id cannot become
 * injected SQL.
 */
@ApplicationScoped
public class TenantQuery {

  private final DSLContext dsl;
  private final TenantSchemas tenants;

  public TenantQuery(DSLContext dsl, TenantSchemas tenants) {
    this.dsl = dsl;
    this.tenants = tenants;
  }

  /** Runs {@code work} with the connection's search_path pointed at {@code tenantId}'s schema. */
  public <T> T inTenant(String tenantId, Function<DSLContext, T> work) {
    String schema = resolveSchema(tenantId);
    return dsl.transactionResult(
        configuration -> {
          configuration.dsl().execute("set local search_path to {0}", DSL.name(schema));
          return work.apply(configuration.dsl());
        });
  }

  /**
   * Maps a request's tenant id to its schema, rejecting anything not in the configured tenant list
   * with a 404 — an unknown or malformed tenant is indistinguishable from a missing resource, and
   * neither should reach the database.
   */
  private String resolveSchema(String tenantId) {
    if (!tenants.tenantIds().contains(tenantId)) {
      throw new NotFoundException("unknown tenant: " + tenantId);
    }
    return TenantSchemas.schemaFor(tenantId);
  }
}
