package dev.parvum.serving.api;

import static dev.parvum.serving.jooq.Tables.ALTS_HOLDINGS;
import static dev.parvum.serving.jooq.Tables.ASSET_ALLOCATION;
import static dev.parvum.serving.jooq.Tables.CLIENT_WEALTH;
import static dev.parvum.serving.jooq.Tables.INCOME;
import static dev.parvum.serving.jooq.Tables.OWNERSHIP;
import static dev.parvum.serving.jooq.Tables.PERFORMANCE;
import static dev.parvum.serving.jooq.Tables.PERFORMANCE_SUMMARY;
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
 * Read-only endpoints over the gold projections, one advisory firm (tenant) at a time. The tenant
 * is the first path segment, so a firm's whole API lives under {@code /tenants/{id}/...} and every
 * call is routed to that firm's schema by {@link TenantQuery}.
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
                            r.getAltsUsd(),
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

  /**
   * The ownership graph: which clients own each account, at what fraction. Ordered so each
   * account's owners are grouped, largest share first — the shared 60/40 account shows both its
   * owners.
   */
  @GET
  @Path("/ownership")
  public List<OwnershipRow> ownership(@PathParam("tenantId") String tenantId) {
    return tenantQuery.inTenant(
        tenantId,
        dsl ->
            dsl.selectFrom(OWNERSHIP)
                .orderBy(OWNERSHIP.ACCOUNT_ID, OWNERSHIP.OWNERSHIP_PCT.desc())
                .fetch(
                    r ->
                        new OwnershipRow(
                            r.getAccountId(),
                            r.getClientId(),
                            r.getClientName(),
                            r.getOwnershipPct(),
                            r.getOwnerCount(),
                            r.getIsShared())));
  }

  /** Daily time-weighted return chain per client — the full series, for a time chart. */
  @GET
  @Path("/performance")
  public List<PerformanceRow> performance(@PathParam("tenantId") String tenantId) {
    return tenantQuery.inTenant(
        tenantId,
        dsl ->
            dsl.selectFrom(PERFORMANCE)
                .orderBy(PERFORMANCE.CLIENT_NAME, PERFORMANCE.AS_OF)
                .fetch(
                    r ->
                        new PerformanceRow(
                            r.getAsOf(),
                            r.getClientId(),
                            r.getClientName(),
                            r.getTotalWealthUsd(),
                            r.getExternalFlowUsd(),
                            r.getDailyTwrReturn(),
                            r.getTwrIndexSinceInception())));
  }

  /**
   * Since-inception return per client by three methodologies (time-weighted, Modified Dietz,
   * money-weighted IRR) — see docs/PERFORMANCE_METHODOLOGY.md for why they differ.
   */
  @GET
  @Path("/performance-summary")
  public List<PerformanceSummaryRow> performanceSummary(@PathParam("tenantId") String tenantId) {
    return tenantQuery.inTenant(
        tenantId,
        dsl ->
            dsl.selectFrom(PERFORMANCE_SUMMARY)
                .orderBy(PERFORMANCE_SUMMARY.CLIENT_NAME)
                .fetch(
                    r ->
                        new PerformanceSummaryRow(
                            r.getClientId(),
                            r.getClientName(),
                            r.getInceptionDate(),
                            r.getAsOf(),
                            r.getWealthBeginUsd(),
                            r.getWealthEndUsd(),
                            r.getNetExternalFlowUsd(),
                            r.getTwrSinceInception(),
                            r.getDietzSinceInception(),
                            r.getIrrSinceInceptionAnnualized())));
  }

  /**
   * Private-fund holdings behind the alts slice of a client's wealth (D-060) — commitment, capital
   * called/distributed, unfunded commitment, current NAV, and MOIC per (client, fund).
   */
  @GET
  @Path("/alts-holdings")
  public List<AltsHoldingRow> altsHoldings(@PathParam("tenantId") String tenantId) {
    return tenantQuery.inTenant(
        tenantId,
        dsl ->
            dsl.selectFrom(ALTS_HOLDINGS)
                .orderBy(ALTS_HOLDINGS.CLIENT_NAME, ALTS_HOLDINGS.FUND_NAME)
                .fetch(
                    r ->
                        new AltsHoldingRow(
                            r.getClientId(),
                            r.getClientName(),
                            r.getFundId(),
                            r.getFundName(),
                            r.getAccountId(),
                            r.getInceptionDate(),
                            r.getAsOf(),
                            r.getTotalCommitmentUsd(),
                            r.getCalledToDateUsd(),
                            r.getDistributedToDateUsd(),
                            r.getUnfundedCommitmentUsd(),
                            r.getCurrentNavUsd(),
                            r.getMoic(),
                            r.getPendingReviewDocuments())));
  }

  public record WealthRow(
      LocalDate asOf,
      String clientId,
      String clientName,
      BigDecimal positionsUsd,
      BigDecimal cashUsd,
      BigDecimal altsUsd,
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

  public record OwnershipRow(
      String accountId,
      String clientId,
      String clientName,
      BigDecimal ownershipPct,
      int ownerCount,
      boolean isShared) {}

  public record PerformanceRow(
      LocalDate asOf,
      String clientId,
      String clientName,
      BigDecimal totalWealthUsd,
      BigDecimal externalFlowUsd,
      BigDecimal dailyTwrReturn,
      BigDecimal twrIndexSinceInception) {}

  public record PerformanceSummaryRow(
      String clientId,
      String clientName,
      LocalDate inceptionDate,
      LocalDate asOf,
      BigDecimal wealthBeginUsd,
      BigDecimal wealthEndUsd,
      BigDecimal netExternalFlowUsd,
      BigDecimal twrSinceInception,
      BigDecimal dietzSinceInception,
      BigDecimal irrSinceInceptionAnnualized) {}

  public record AltsHoldingRow(
      String clientId,
      String clientName,
      String fundId,
      String fundName,
      String accountId,
      LocalDate inceptionDate,
      LocalDate asOf,
      BigDecimal totalCommitmentUsd,
      BigDecimal calledToDateUsd,
      BigDecimal distributedToDateUsd,
      BigDecimal unfundedCommitmentUsd,
      BigDecimal currentNavUsd,
      BigDecimal moic,
      int pendingReviewDocuments) {}
}
