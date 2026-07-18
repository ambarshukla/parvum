package dev.parvum.serving.api;

import static dev.parvum.serving.jooq.Tables.ASSET_ALLOCATION;
import static dev.parvum.serving.jooq.Tables.CLIENT_WEALTH;
import static dev.parvum.serving.jooq.Tables.INCOME;
import static dev.parvum.serving.jooq.Tables.TOP_HOLDINGS;
import static org.jooq.impl.DSL.max;

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
 * Read-only endpoints over the four gold projections, one advisory firm (tenant) at a time. The
 * tenant is the first path segment, so a firm's whole API lives under {@code /tenants/{id}/...} and
 * every call is routed to that firm's schema by {@link TenantQuery}.
 *
 * <p>{@code rebuilt_at} is deliberately not exposed: it is an internal reload marker, not part of
 * the reported figures.
 */
@Path("/tenants/{tenantId}")
@Produces(MediaType.APPLICATION_JSON)
public class ProjectionResource {

  private final TenantQuery tenantQuery;

  public ProjectionResource(TenantQuery tenantQuery) {
    this.tenantQuery = tenantQuery;
  }

  /** Headline wealth per client, on the latest exported date. */
  @GET
  @Path("/wealth")
  public List<WealthRow> wealth(@PathParam("tenantId") String tenantId) {
    return tenantQuery.inTenant(
        tenantId,
        dsl ->
            dsl.selectFrom(CLIENT_WEALTH)
                .where(
                    CLIENT_WEALTH.AS_OF.eq(
                        dsl.select(max(CLIENT_WEALTH.AS_OF)).from(CLIENT_WEALTH)))
                .orderBy(CLIENT_WEALTH.CLIENT_NAME)
                .fetch(
                    r ->
                        new WealthRow(
                            r.getAsOf(),
                            r.getClientId(),
                            r.getClientName(),
                            r.getPositionsUsd(),
                            r.getCashUsd(),
                            r.getTotalWealthUsd(),
                            r.getFxRateUsed(),
                            r.getFxRateDate(),
                            r.getBooksReconcile())));
  }

  /** Asset-class breakdown per client, on the latest exported date. */
  @GET
  @Path("/allocation")
  public List<AllocationRow> allocation(@PathParam("tenantId") String tenantId) {
    return tenantQuery.inTenant(
        tenantId,
        dsl ->
            dsl.selectFrom(ASSET_ALLOCATION)
                .where(
                    ASSET_ALLOCATION.AS_OF.eq(
                        dsl.select(max(ASSET_ALLOCATION.AS_OF)).from(ASSET_ALLOCATION)))
                .orderBy(ASSET_ALLOCATION.CLIENT_NAME, ASSET_ALLOCATION.WEIGHT.desc())
                .fetch(
                    r ->
                        new AllocationRow(
                            r.getAsOf(),
                            r.getClientId(),
                            r.getClientName(),
                            r.getAssetClass(),
                            r.getValueUsd(),
                            r.getWeight())));
  }

  /** Monthly income per client — the full series, for a time chart. */
  @GET
  @Path("/income")
  public List<IncomeRow> income(@PathParam("tenantId") String tenantId) {
    return tenantQuery.inTenant(
        tenantId,
        dsl ->
            dsl.selectFrom(INCOME)
                .orderBy(INCOME.CLIENT_NAME, INCOME.MONTH, INCOME.TYPE)
                .fetch(
                    r ->
                        new IncomeRow(
                            r.getClientId(),
                            r.getClientName(),
                            r.getMonth(),
                            r.getType(),
                            r.getIncomeUsd(),
                            r.getMovements())));
  }

  /** Top holdings per client on the latest date (the projection already keeps only that date). */
  @GET
  @Path("/holdings")
  public List<HoldingRow> holdings(@PathParam("tenantId") String tenantId) {
    return tenantQuery.inTenant(
        tenantId,
        dsl ->
            dsl.selectFrom(TOP_HOLDINGS)
                .orderBy(TOP_HOLDINGS.CLIENT_NAME, TOP_HOLDINGS.RANK)
                .fetch(
                    r ->
                        new HoldingRow(
                            r.getAsOf(),
                            r.getClientId(),
                            r.getClientName(),
                            r.getRank(),
                            r.getSecurityName(),
                            r.getSecurityScheme(),
                            r.getSecurityId(),
                            r.getAssetClass(),
                            r.getOwnedUsd(),
                            r.getWeight())));
  }

  public record WealthRow(
      LocalDate asOf,
      String clientId,
      String clientName,
      BigDecimal positionsUsd,
      BigDecimal cashUsd,
      BigDecimal totalWealthUsd,
      BigDecimal fxRateUsed,
      LocalDate fxRateDate,
      boolean booksReconcile) {}

  public record AllocationRow(
      LocalDate asOf,
      String clientId,
      String clientName,
      String assetClass,
      BigDecimal valueUsd,
      BigDecimal weight) {}

  public record IncomeRow(
      String clientId,
      String clientName,
      LocalDate month,
      String type,
      BigDecimal incomeUsd,
      int movements) {}

  public record HoldingRow(
      LocalDate asOf,
      String clientId,
      String clientName,
      int rank,
      String securityName,
      String securityScheme,
      String securityId,
      String assetClass,
      BigDecimal ownedUsd,
      BigDecimal weight) {}
}
