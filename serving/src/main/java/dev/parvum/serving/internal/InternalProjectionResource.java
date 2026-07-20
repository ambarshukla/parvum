package dev.parvum.serving.internal;

import static dev.parvum.serving.jooq.Tables.DQ_METRICS;

import dev.parvum.serving.tenancy.TenantQuery;
import jakarta.ws.rs.GET;
import jakarta.ws.rs.Path;
import jakarta.ws.rs.PathParam;
import jakarta.ws.rs.Produces;
import jakarta.ws.rs.core.MediaType;
import java.math.BigDecimal;
import java.time.LocalDate;
import java.util.List;

/**
 * Projections that belong to internal staff, not clients — gated by {@link InternalAuthFilter} via
 * the {@code /internal} path prefix, unlike the read-only endpoints in {@link
 * dev.parvum.serving.api.ProjectionResource}.
 */
@Path("/internal/tenants/{tenantId}")
@Produces(MediaType.APPLICATION_JSON)
public class InternalProjectionResource {

  private final TenantQuery tenantQuery;

  public InternalProjectionResource(TenantQuery tenantQuery) {
    this.tenantQuery = tenantQuery;
  }

  /**
   * The DQ metrics rollup — the full series, for pipeline-wide trend charts. Not scoped to this
   * tenant's clients (see V4__dq_metrics.sql): identical rows regardless of which tenant is
   * selected, since the underlying pipeline is the same one every firm's data comes from.
   */
  @GET
  @Path("/dq-metrics")
  public List<DqMetricRow> dqMetrics(@PathParam("tenantId") String tenantId) {
    return tenantQuery.inTenant(
        tenantId,
        dsl ->
            dsl.selectFrom(DQ_METRICS)
                .orderBy(DQ_METRICS.DIMENSION, DQ_METRICS.METRIC, DQ_METRICS.AS_OF)
                .fetch(
                    r ->
                        new DqMetricRow(
                            r.getAsOf(),
                            r.getDimension(),
                            r.getMetric(),
                            r.getValue(),
                            r.getPassed(),
                            r.getDetail())));
  }

  public record DqMetricRow(
      LocalDate asOf,
      String dimension,
      String metric,
      BigDecimal value,
      Boolean passed,
      String detail) {}
}
