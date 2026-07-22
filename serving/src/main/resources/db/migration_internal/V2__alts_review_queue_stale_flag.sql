-- A pending review item whose document silver no longer routes to
-- needs_review (a re-extraction fixed it, or it now auto_accepts) is
-- flagged rather than deleted by the export-side loader: a reviewer may
-- already be looking at it, and "this no longer needs review" is itself
-- worth surfacing, not silently hiding the row. The next load un-stales it
-- automatically if the document flickers back into needs_review.

alter table alts_review_queue add column stale boolean not null default false;
comment on column alts_review_queue.stale is
    'True when the loader''s last run no longer found this pending document in needs_review upstream -- the extraction may have been fixed, or auto_accepts now. Reset to false the next time the document reappears in needs_review. Never set on a decided (approved/corrected) row.';
