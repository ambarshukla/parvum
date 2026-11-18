"""Hold two implementations of the internal API to one contract.

The Java service (serving/) and the .NET service (serving-dotnet/) are started
against the same Postgres. This script seeds that database, sends both services
the same requests, and fails if their answers differ.

Reads are compared directly: same database, same request, so the JSON must be
the same. Writes cannot be sent twice to the same row, so each write case seeds
two identical rows ("twins"), decides one through each service, and compares
what came back and what each left in the audit table.

Run through compose (see compose.yml); exits non-zero on any difference.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from decimal import Decimal

import psycopg

JAVA = os.environ["JAVA_URL"]
DOTNET = os.environ["DOTNET_URL"]
PASSWORD = os.environ["PARITY_PASSWORD"]
SERVICES = {"java": JAVA, "dotnet": DOTNET}
COOKIE = "parvum_internal_session"
HEADER = {"X-Parvum-Internal": "1"}

failures: list[str] = []
passed = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global passed
    if ok:
        passed += 1
        print(f"  ok    {name}")
    else:
        failures.append(name)
        print(f"  FAIL  {name}\n        {detail}")


# ---- HTTP ----------------------------------------------------------------------------


class Reply:
    def __init__(self, status: int, headers, body: bytes):
        self.status = status
        self.headers = headers
        self.body = body

    def json(self):
        # Decimal, not float: 0.850 and 0.85 are the same number and must compare equal,
        # while a float round-trip could make two correct answers look different.
        return json.loads(self.body, parse_float=Decimal)


def call(base: str, method: str, path: str, *, headers=None, cookie=None, body=None) -> Reply:
    request = urllib.request.Request(base + path, method=method, data=body)
    for key, value in (headers or {}).items():
        request.add_header(key, value)
    if cookie:
        request.add_header("Cookie", f"{COOKIE}={cookie}")
    if body is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return Reply(response.status, response.headers, response.read())
    except urllib.error.HTTPError as error:
        return Reply(error.code, error.headers, error.read())


def wait_until_up(name: str, url: str) -> None:
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3) as response:
                if response.status == 200:
                    return
        except OSError:
            pass
        time.sleep(1)
    sys.exit(f"{name} did not come up at {url}")


# ---- comparison ----------------------------------------------------------------------

_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")


def normalise(value):
    """Reduce a JSON value to what it means, so only real differences remain.

    The two runtimes print the same instant differently (trailing zeros in the
    fraction, 'Z' against '+00:00'). Parsing timestamps makes those compare equal
    without hiding a genuinely different time.
    """
    if isinstance(value, dict):
        return {key: normalise(item) for key, item in value.items()}
    if isinstance(value, list):
        return [normalise(item) for item in value]
    if isinstance(value, str) and _TIMESTAMP.match(value):
        return datetime.fromisoformat(value)
    return value


def first_difference(a, b, path="$") -> str:
    if type(a) is not type(b) and not (isinstance(a, (int, Decimal)) and isinstance(b, (int, Decimal))):
        return f"{path}: {a!r} vs {b!r}"
    if isinstance(a, dict):
        for key in sorted(set(a) | set(b)):
            if key not in a or key not in b:
                return f"{path}.{key}: present in only one answer"
            if a[key] != b[key]:
                return first_difference(a[key], b[key], f"{path}.{key}")
    if isinstance(a, list):
        if len(a) != len(b):
            return f"{path}: {len(a)} items vs {len(b)}"
        for index, (x, y) in enumerate(zip(a, b)):
            if x != y:
                return first_difference(x, y, f"{path}[{index}]")
    return f"{path}: {a!r} vs {b!r}"


def same_status(name: str, method: str, path: str, expected: int, **kwargs) -> None:
    got = {service: call(base, method, path, **kwargs).status for service, base in SERVICES.items()}
    check(f"{name} -> {expected}", set(got.values()) == {expected}, f"{got}")


def same_json(name: str, path: str, cookie: str) -> None:
    replies = {s: call(base, "GET", path, headers=HEADER, cookie=cookie) for s, base in SERVICES.items()}
    if {r.status for r in replies.values()} != {200}:
        check(name, False, f"statuses { {s: r.status for s, r in replies.items()} }")
        return
    java, dotnet = normalise(replies["java"].json()), normalise(replies["dotnet"].json())
    rows = f" ({len(java)} rows)" if isinstance(java, list) else ""
    check(f"{name}{rows}", java == dotnet, first_difference(java, dotnet))


# ---- seed ----------------------------------------------------------------------------

PDF = b"%PDF-1.4\n% parity suite document\n%%EOF\n"

FIELDS = {
    "fund_name": "Wraithmoor Capital Partners IV",
    "call_amount": 450000.0,
    "due_date": "2025-12-31",
    "currency": "USD",
    "notes": None,
}


def seed(connection) -> dict[str, int]:
    """Fill both tenant schemas and the review queue. Returns queue ids by label."""
    ids: dict[str, int] = {}
    with connection.cursor() as cur:
        for tenant in ("tenant_aldergate", "tenant_stonefield"):
            cur.execute(f'set search_path to "{tenant}"')
            cur.execute("truncate dq_metrics, cde_registry, slo_attainment")
            cur.executemany(
                "insert into dq_metrics values (%s, %s, %s, %s, %s, %s, now())",
                [
                    ("2026-01-02", "freshness", "bronze_days_behind", "0", True, "fresh"),
                    ("2026-01-01", "accuracy", "cash_consistency_rate", "0.345678", False, "22 of 64"),
                    ("2026-01-02", "accuracy", "cash_consistency_rate", "1", True, "64 of 64"),
                    ("2026-01-02", "exceptions", "plausibility_breaks_count", "3", None, "trend only"),
                    ("2026-01-02", "governance", "columns_classified_rate", "1.000000", True, "363 of 363"),
                    ("2026-01-02", "completeness", "feed_files_landed_rate", "0.909091", False, "10 of 11"),
                ],
            )
            cur.executemany(
                "insert into cde_registry (table_name, column_name, layer, description, tier, owner, "
                "definition, quality_rules, quality_rule_count, control_gap, slo, slo_measured_by, "
                "slo_target, rebuilt_at, slo_objective, slo_attainment_objective, slo_window_days) "
                "values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now(), %s, %s, %s)",
                [
                    ("gold.client_wealth", "total_wealth_usd", "gold", "Total wealth", "critical", "wealth-data",
                     "Sum of positions, cash and alts", "wealth_components_sum,allocation_value_matches_wealth", 2,
                     None, "cross_field_consistency", "cross_field_invariant_rate", ">= 1.0",
                     "Published figures agree with each other", "0.990000", 30),
                    ("gold.alts_holdings", "moic", "gold", "Multiple on invested capital", "critical", "alts-ops",
                     "(distributed + NAV) / called", None, 0, "Needs an independent ratio recomputation",
                     None, None, None, None, None, None),
                    ("silver.positions", "quantity", "silver", "Units held", "supporting", "wealth-data",
                     None, None, 0, None, None, None, None, None, None, None),
                    ("bronze.file_registry", "sha256", "bronze", "Digest of the landed file", "operational",
                     "platform", None, None, 0, None, None, None, None, None, None, None),
                    ("gold.new_table", "new_column", "gold", "Not yet classified", None, None,
                     None, None, 0, None, None, None, None, None, None, None),
                ],
            )
            cur.executemany(
                "insert into slo_attainment values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())",
                [
                    ("feed_completeness", "Every expected file lands", "feed_files_landed_rate", ">= 1.0",
                     "1.000000", 30, "2025-12-04", "2026-01-02", 22, 22, "1.000000", True, False, "0.00", 0, None),
                    ("cash_ledger_integrity", "Cash ledgers reconcile", "cash_consistency_rate", ">= 1.0",
                     "0.950000", 30, "2025-12-04", "2026-01-02", 22, 10, "0.454545", False, False, "1.10", 12,
                     "-9.909091"),
                    ("holdings_agreement", "Custodian formats agree", "holdings_match_rate", ">= 1.0",
                     "0.950000", 30, "2025-12-04", "2026-01-02", 22, 0, "0.000000", False, False, "1.10", 22,
                     "-19.000000"),
                    ("fx_integrity", "FX rates are plausible", "fx_rate_plausibility_rate", ">= 1.0",
                     "0.990000", 30, "2025-12-04", "2026-01-02", 1, 1, "1.000000", None, True, "0.30", 0,
                     "1.000000"),
                ],
            )

        cur.execute("set search_path to internal")
        cur.execute("truncate alts_review_audit, alts_review_queue, alts_documents restart identity cascade")

        def queue(label, fund, document, *, status="pending", minutes_ago, decided=False, notes=None, stale=False):
            # Distinct load times, because the list is ordered by loaded_at alone and a tie
            # would let two correct services return rows in different orders.
            cur.execute(
                "insert into alts_review_queue (fund_id, document, doc_type, sequence_number, period_end, "
                "extracted_fields, confidence, validation_notes, status, decided_fields, decided_at, stale, "
                "loaded_at) values (%s, %s, 'capital_call', %s, %s, %s::jsonb, %s, %s, %s, %s::jsonb, %s, %s, "
                "now() - make_interval(mins => %s)) returning id",
                (fund, document, 1, "2025-12-31", json.dumps(FIELDS), "0.612", notes, status,
                 json.dumps(FIELDS) if decided else None, "2026-01-02T09:30:00.123456Z" if decided else None,
                 stale, minutes_ago),
            )
            ids[label] = cur.fetchone()[0]

        queue("pending", "FUND-US01", "capital_call_01.pdf", minutes_ago=10, notes="amount disagrees with statement")
        queue("stale", "FUND-US01", "capital_call_02.pdf", minutes_ago=20, stale=True)
        queue("decided", "FUND-EU01", "distribution_01.pdf", status="approved", minutes_ago=30, decided=True)
        for case in ("approve", "correct", "double", "race"):
            queue(f"{case}-java", "FUND-J", f"{case}.pdf", minutes_ago=40)
            queue(f"{case}-dotnet", "FUND-N", f"{case}.pdf", minutes_ago=41)

        cur.execute(
            "insert into alts_documents (fund_id, document, content, byte_size, sha256) values (%s, %s, %s, %s, %s)",
            ("FUND-US01", "capital call 01.pdf", PDF, len(PDF), "parity"),
        )
    connection.commit()
    return ids


def audit_rows(connection, queue_id: int) -> list[tuple]:
    with connection.cursor() as cur:
        cur.execute(
            "select action, before_fields, after_fields from internal.alts_review_audit "
            "where queue_id = %s order by id",
            (queue_id,),
        )
        return cur.fetchall()


# ---- the cases -----------------------------------------------------------------------


def login(base: str, password: str) -> Reply:
    return call(base, "POST", "/internal/auth/login", headers=HEADER, body=json.dumps({"password": password}).encode())


def cookie_from(reply: Reply) -> str:
    return reply.headers["Set-Cookie"].split(";")[0].split("=", 1)[1]


def cookie_attributes(reply: Reply) -> dict[str, str]:
    wanted = {"path", "max-age", "secure", "httponly", "samesite"}
    parts = [part.strip() for part in reply.headers["Set-Cookie"].split(";")[1:]]
    pairs = (part.split("=", 1) + [""] for part in parts)
    return {p[0].lower(): p[1].lower() for p in pairs if p[0].lower() in wanted}


def twin_view(item: dict) -> dict:
    """A decided twin with the fields that are meant to differ taken out."""
    view = {k: v for k, v in normalise(item).items() if k not in ("id", "fundId", "loadedAt", "decidedAt")}
    view["decidedAtPresent"] = item["decidedAt"] is not None
    for field in ("extractedFields", "decidedFields"):
        view[field] = json.loads(item[field], parse_float=Decimal)
    return view


def main() -> int:
    wait_until_up("java", JAVA + "/q/health")
    wait_until_up("dotnet", DOTNET + "/healthz")
    connection = psycopg.connect(os.environ["DATABASE_URL"])
    ids = seed(connection)

    print("\nThe gate")
    for path in ("/internal/auth/session", "/internal/alts/queue", "/internal/no-such-route"):
        same_status(f"no custom header: GET {path}", "GET", path, 403)
        same_status(f"header but no session: GET {path}", "GET", path, 401, headers=HEADER)
    same_status("a forged cookie", "GET", "/internal/auth/session", 401, headers=HEADER, cookie="4102444800.forged")

    print("\nLogin")
    for label, password, expected in (("wrong password", "nope", 401), ("empty password", "", 401),
                                      ("real password", PASSWORD, 204), ("demo password", "parvum-showcase", 204)):
        got = {s: login(base, password).status for s, base in SERVICES.items()}
        check(f"{label} -> {expected}", set(got.values()) == {expected}, f"{got}")
    logins = {s: login(base, PASSWORD) for s, base in SERVICES.items()}
    cookies = {s: cookie_from(r) for s, r in logins.items()}
    attributes = {s: cookie_attributes(r) for s, r in logins.items()}
    check("session cookie carries the same attributes", attributes["java"] == attributes["dotnet"], f"{attributes}")
    # The property that makes a gradual cutover possible: one login, either service.
    check("a cookie issued by Java is accepted by .NET",
          call(DOTNET, "GET", "/internal/auth/session", headers=HEADER, cookie=cookies["java"]).status == 204)
    check("a cookie issued by .NET is accepted by Java",
          call(JAVA, "GET", "/internal/auth/session", headers=HEADER, cookie=cookies["dotnet"]).status == 204)
    logouts = {s: call(base, "POST", "/internal/auth/logout", headers=HEADER) for s, base in SERVICES.items()}
    check("logout -> 204 and an expired cookie",
          all(r.status == 204 and cookie_attributes(r).get("max-age") == "0" for r in logouts.values()),
          f"{ {s: (r.status, r.headers['Set-Cookie']) for s, r in logouts.items()} }")
    cookie = cookies["java"]
    signed_in = {"headers": HEADER, "cookie": cookie}

    print("\nOperations views")
    for view in ("dq-metrics", "cde-registry", "slo-attainment"):
        same_json(f"GET {view}", f"/internal/tenants/aldergate/{view}", cookie)
    same_json("GET dq-metrics for the other tenant", "/internal/tenants/stonefield/dq-metrics", cookie)
    for tenant in ("unknown", "ALDERGATE", "tenant_template", "alder-gate"):
        same_status(f"tenant '{tenant}'", "GET", f"/internal/tenants/{tenant}/dq-metrics", 404, **signed_in)

    print("\nReview queue: reads")
    same_json("GET queue", "/internal/alts/queue", cookie)
    for status in ("pending", "approved", "corrected", "no-such-status"):
        same_json(f"GET queue?status={status}", f"/internal/alts/queue?status={status}", cookie)
    for label in ("pending", "stale", "decided"):
        same_json(f"GET queue item ({label})", f"/internal/alts/queue/{ids[label]}", cookie)
    same_status("a queue item that does not exist", "GET", "/internal/alts/queue/999999", 404, **signed_in)
    same_status("a queue id that is not a number", "GET", "/internal/alts/queue/abc", 404, **signed_in)

    document = "/internal/alts/documents/FUND-US01/capital%20call%2001.pdf"
    pdfs = {s: call(base, "GET", document, **signed_in) for s, base in SERVICES.items()}
    check("source PDF: same bytes", all(r.status == 200 and r.body == PDF for r in pdfs.values()),
          f"{ {s: (r.status, len(r.body)) for s, r in pdfs.items()} }")
    check("source PDF: same content type and file name",
          len({(r.headers.get_content_type(), r.headers["Content-Disposition"]) for r in pdfs.values()}) == 1,
          f"{ {s: (r.headers['Content-Type'], r.headers['Content-Disposition']) for s, r in pdfs.items()} }")
    same_status("a document that does not exist", "GET", "/internal/alts/documents/FUND-US01/missing.pdf", 404,
                **signed_in)

    print("\nReview queue: decisions")
    correction = json.dumps({**FIELDS, "call_amount": 475000.5, "notes": "confirmed with the administrator"}).encode()

    def decide(case: str, action: str, body=None) -> dict[str, Reply]:
        return {s: call(base, "POST", f"/internal/alts/queue/{ids[f'{case}-{s}']}/{action}", body=body, **signed_in)
                for s, base in SERVICES.items()}

    for case, action, body in (("approve", "approve", None), ("correct", "correct", correction)):
        replies = decide(case, action, body)
        if {r.status for r in replies.values()} != {200}:
            check(f"{action} a pending item", False, f"{ {s: (r.status, r.body[:200]) for s, r in replies.items()} }")
            continue
        views = {s: twin_view(r.json()) for s, r in replies.items()}
        check(f"{action}: same answer", views["java"] == views["dotnet"], first_difference(views["java"], views["dotnet"]))
        audits = {s: audit_rows(connection, ids[f"{case}-{s}"]) for s in SERVICES}
        check(f"{action}: one audit row each, with the same content",
              len(audits["java"]) == 1 and audits["java"] == audits["dotnet"], f"{audits}")
        check(f"{action}: deciding it again -> 409",
              {r.status for r in decide(case, action, body).values()} == {409})

    for label, body in (("an empty object", b"{}"), ("an array", b"[1, 2]"), ("text that is not JSON", b"not json")):
        got = {s: r.status for s, r in decide("double", "correct", body).items()}
        check(f"correcting with {label} -> 400", set(got.values()) == {400}, f"{got}")
    for action in ("approve", "correct"):
        same_status(f"{action} an item that does not exist", "POST", f"/internal/alts/queue/999999/{action}", 404,
                    body=correction if action == "correct" else None, **signed_in)
    connection.commit()
    check("a refused correction leaves the item pending and unaudited",
          all(audit_rows(connection, ids[f"double-{s}"]) == [] for s in SERVICES))

    # Twenty reviewers approve the same item at the same instant. Exactly one may win.
    print("\nReview queue: the same item decided twenty times at once")
    for service, base in SERVICES.items():
        path = f"/internal/alts/queue/{ids[f'race-{service}']}/approve"
        with ThreadPoolExecutor(max_workers=20) as pool:
            statuses = list(pool.map(lambda _: call(base, "POST", path, **signed_in).status, range(20)))
        connection.commit()
        rows = len(audit_rows(connection, ids[f"race-{service}"]))
        check(f"{service}: exactly one approval is accepted and audited",
              statuses.count(200) == 1 and statuses.count(409) == 19 and rows == 1,
              f"{statuses.count(200)} accepted, {statuses.count(409)} refused, {rows} audit row(s)")

    print(f"\n{passed} passed, {len(failures)} failed")
    for name in failures:
        print(f"  FAIL  {name}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
