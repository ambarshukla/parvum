package dev.parvum.serving.internal;

import jakarta.enterprise.context.ApplicationScoped;
import java.util.function.Function;
import org.jooq.DSLContext;
import org.jooq.impl.DSL;

/**
 * Runs a query against the internal schema — the same "{@code SET LOCAL search_path} as the first
 * statement of a transaction" mechanism {@link dev.parvum.serving.tenancy.TenantQuery} uses for
 * tenant schemas, fixed to the one non-tenant schema instead of resolving one per request (there is
 * nothing to resolve: every {@code /internal/alts/**} request reads the same schema).
 */
@ApplicationScoped
public class InternalQuery {

  private final DSLContext dsl;

  public InternalQuery(DSLContext dsl) {
    this.dsl = dsl;
  }

  public <T> T run(Function<DSLContext, T> work) {
    return dsl.transactionResult(
        configuration -> {
          configuration
              .dsl()
              .execute("set local search_path to {0}", DSL.name(InternalSchema.SCHEMA));
          return work.apply(configuration.dsl());
        });
  }
}
