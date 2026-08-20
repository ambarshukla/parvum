package dev.parvum.serving.internal;

import static dev.parvum.serving.jooq.Tables.CDE_REGISTRY;
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
import org.jooq.impl.DSL;

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

  /**
   * The Critical Data Element register — every column the platform publishes, with its tier, owner
   * and either the controls that test it or the gap where none exists. Unscoped for the same reason
   * as the DQ metrics above: it describes the pipeline, not any one firm's clients.
   *
   * <p>Ordered so the register reads the way it is meant to be consulted: the critical elements
   * first, then supporting, then plumbing — and within a tier, by where the column lives.
   */
  @GET
  @Path("/cde-registry")
  public List<CdeRegistryRow> cdeRegistry(@PathParam("tenantId") String tenantId) {
    return tenantQuery.inTenant(
        tenantId,
        dsl ->
            dsl.selectFrom(CDE_REGISTRY)
                .orderBy(
                    DSL.case_(CDE_REGISTRY.TIER)
                        .when("critical", 0)
                        .when("supporting", 1)
                        .when("operational", 2)
                        .else_(3),
                    CDE_REGISTRY.TABLE_NAME,
                    CDE_REGISTRY.COLUMN_NAME)
                .fetch(
                    r ->
                        new CdeRegistryRow(
                            r.getTableName(),
                            r.getColumnName(),
                            r.getLayer(),
                            r.getDescription(),
                            r.getTier(),
                            r.getOwner(),
                            r.getDefinition(),
                            r.getQualityRules(),
                            r.getQualityRuleCount(),
                            r.getControlGap(),
                            r.getSlo(),
                            r.getSloMeasuredBy(),
                            r.getSloTarget())));
  }

  public record CdeRegistryRow(
      String tableName,
      String columnName,
      String layer,
      String description,
      String tier,
      String owner,
      String definition,
      String qualityRules,
      Integer qualityRuleCount,
      String controlGap,
      String slo,
      String sloMeasuredBy,
      String sloTarget) {}

  public record DqMetricRow(
      LocalDate asOf,
      String dimension,
      String metric,
      BigDecimal value,
      Boolean passed,
      String detail) {}
}
