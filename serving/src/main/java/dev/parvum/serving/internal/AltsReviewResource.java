package dev.parvum.serving.internal;

import static dev.parvum.serving.jooq.internal.Tables.ALTS_DOCUMENTS;
import static dev.parvum.serving.jooq.internal.Tables.ALTS_REVIEW_AUDIT;
import static dev.parvum.serving.jooq.internal.Tables.ALTS_REVIEW_QUEUE;

import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.ws.rs.Consumes;
import jakarta.ws.rs.GET;
import jakarta.ws.rs.NotFoundException;
import jakarta.ws.rs.POST;
import jakarta.ws.rs.Path;
import jakarta.ws.rs.PathParam;
import jakarta.ws.rs.Produces;
import jakarta.ws.rs.QueryParam;
import jakarta.ws.rs.WebApplicationException;
import jakarta.ws.rs.core.MediaType;
import jakarta.ws.rs.core.Response;
import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.util.List;
import java.util.Map;
import org.jooq.JSON;

/**
 * The alts HITL review queue: documents {@code silver_alts_documents} routed to {@code
 * needs_review}, loaded from Databricks (a later export-side slice), reviewed here, and eventually
 * reverse-synced back (also later). This resource only reads/writes the queue and its append-only
 * audit trail — it never talks to Databricks directly.
 *
 * <p>Gated by {@link InternalAuthFilter} via the {@code /internal} path prefix, same as everything
 * else in this app.
 */
@Path("/internal/alts")
@Produces(MediaType.APPLICATION_JSON)
public class AltsReviewResource {

  private final InternalQuery query;
  private final ObjectMapper objectMapper;

  public AltsReviewResource(InternalQuery query, ObjectMapper objectMapper) {
    this.query = query;
    this.objectMapper = objectMapper;
  }

  @GET
  @Path("/queue")
  public List<QueueItem> queue(@QueryParam("status") String status) {
    return query.run(
        dsl -> {
          var select = dsl.selectFrom(ALTS_REVIEW_QUEUE);
          var rows =
              status == null
                  ? select.orderBy(ALTS_REVIEW_QUEUE.LOADED_AT.desc()).fetch()
                  : select
                      .where(ALTS_REVIEW_QUEUE.STATUS.eq(status))
                      .orderBy(ALTS_REVIEW_QUEUE.LOADED_AT.desc())
                      .fetch();
          return rows.map(AltsReviewResource::toQueueItem);
        });
  }

  @GET
  @Path("/queue/{id}")
  public QueueItem detail(@PathParam("id") long id) {
    return query.run(
        dsl -> {
          var record =
              dsl.selectFrom(ALTS_REVIEW_QUEUE).where(ALTS_REVIEW_QUEUE.ID.eq(id)).fetchOne();
          if (record == null) {
            throw new NotFoundException("no queue item: " + id);
          }
          return toQueueItem(record);
        });
  }

  /**
   * The source PDF a queued document was extracted from, so a reviewer can read the document itself
   * next to the extracted values rather than taking them on faith (D-057).
   *
   * <p>The bytes come from Postgres, mirrored there by the exporter — this app has no Databricks
   * credentials and no route to the landing volume, deliberately (D-006).
   *
   * <p>Note for callers: {@link InternalAuthFilter} requires the {@code X-Parvum-Internal} header
   * on every {@code /internal/**} request, and an {@code <iframe src>} cannot set one. The browser
   * has to fetch this with {@code fetch()} and render the resulting blob, which is what {@code
   * internal/}'s viewer does.
   */
  @GET
  @Path("/documents/{fundId}/{document}")
  @Produces("application/pdf")
  public Response document(
      @PathParam("fundId") String fundId, @PathParam("document") String document) {
    byte[] content =
        query.run(
            dsl -> {
              var record =
                  dsl.select(ALTS_DOCUMENTS.CONTENT)
                      .from(ALTS_DOCUMENTS)
                      .where(
                          ALTS_DOCUMENTS
                              .FUND_ID
                              .eq(fundId)
                              .and(ALTS_DOCUMENTS.DOCUMENT.eq(document)))
                      .fetchOne();
              if (record == null) {
                throw new NotFoundException("no document: " + fundId + "/" + document);
              }
              return record.value1();
            });

    return Response.ok(content)
        .header("Content-Disposition", "inline; filename=\"" + safeFilename(document) + "\"")
        .build();
  }

  /**
   * A header value can carry no quotes or line breaks. The name came from a database row rather
   * than straight off the request, so this is defence in depth rather than the only guard — but a
   * header built by concatenation should never be the place that assumption gets tested.
   */
  private static String safeFilename(String document) {
    return document.replaceAll("[^A-Za-z0-9._-]", "_");
  }

  /** Accepts the extracted fields exactly as read — no edits. */
  @POST
  @Path("/queue/{id}/approve")
  public QueueItem approve(@PathParam("id") long id) {
    return decide(id, "approved", null);
  }

  /** Records the reviewer's corrected fields in place of the extraction. */
  @POST
  @Path("/queue/{id}/correct")
  @Consumes(MediaType.APPLICATION_JSON)
  public QueueItem correct(@PathParam("id") long id, Map<String, Object> correctedFields) {
    if (correctedFields == null || correctedFields.isEmpty()) {
      throw new WebApplicationException("correctedFields must be a non-empty object", 400);
    }
    return decide(id, "corrected", correctedFields);
  }

  private QueueItem decide(long id, String action, Map<String, Object> correctedFields) {
    return query.run(
        dsl -> {
          var record =
              dsl.selectFrom(ALTS_REVIEW_QUEUE).where(ALTS_REVIEW_QUEUE.ID.eq(id)).fetchOne();
          if (record == null) {
            throw new NotFoundException("no queue item: " + id);
          }
          if (!"pending".equals(record.getStatus())) {
            throw new WebApplicationException(
                "queue item " + id + " is already " + record.getStatus(), Response.Status.CONFLICT);
          }

          JSON before = record.getExtractedFields();
          JSON after = "approved".equals(action) ? before : toJsonb(correctedFields);
          OffsetDateTime now = OffsetDateTime.now();

          record.setStatus(action);
          record.setDecidedFields(after);
          record.setDecidedAt(now);
          record.store();

          dsl.insertInto(ALTS_REVIEW_AUDIT)
              .set(ALTS_REVIEW_AUDIT.QUEUE_ID, id)
              .set(ALTS_REVIEW_AUDIT.ACTION, action)
              .set(ALTS_REVIEW_AUDIT.BEFORE_FIELDS, before)
              .set(ALTS_REVIEW_AUDIT.AFTER_FIELDS, after)
              .set(ALTS_REVIEW_AUDIT.DECIDED_AT, now)
              .execute();

          return toQueueItem(record);
        });
  }

  private JSON toJsonb(Map<String, Object> fields) {
    try {
      return JSON.valueOf(objectMapper.writeValueAsString(fields));
    } catch (Exception e) {
      throw new WebApplicationException(
          "could not serialize correctedFields: " + e.getMessage(), 400);
    }
  }

  private static QueueItem toQueueItem(
      dev.parvum.serving.jooq.internal.tables.records.AltsReviewQueueRecord r) {
    return new QueueItem(
        r.getId(),
        r.getFundId(),
        r.getDocument(),
        r.getDocType(),
        r.getSequenceNumber(),
        r.getPeriodEnd(),
        r.getExtractedFields().data(),
        r.getConfidence(),
        r.getValidationNotes(),
        r.getStatus(),
        r.getStale(),
        r.getDecidedFields() == null ? null : r.getDecidedFields().data(),
        r.getDecidedAt(),
        r.getLoadedAt());
  }

  public record QueueItem(
      long id,
      String fundId,
      String document,
      String docType,
      Integer sequenceNumber,
      LocalDate periodEnd,
      String extractedFields,
      BigDecimal confidence,
      String validationNotes,
      String status,
      boolean stale,
      String decidedFields,
      OffsetDateTime decidedAt,
      OffsetDateTime loadedAt) {}
}
