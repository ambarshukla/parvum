"""Measure what the governance metadata is actually worth to an AI.

The claim every governance programme makes is that better metadata produces
better analytics. It is usually supported by someone else's number. This
module produces ours, on our own estate, and is built so the number can come
out unflattering.

**The method.** A fixed set of questions, each with a hand-written ground-truth
SQL answer. Each question is put to the same model twice:

* **bare** — the table and column *names* only. What a warehouse with no
  metadata looks like from the outside.
* **governed** — the same names, plus the catalog descriptions the jobs
  publish, the register's business definitions for critical elements, and the
  metric views' measure definitions.

Both answers are executed against the real warehouse and compared with the
ground truth. The score is the share of questions answered correctly.

**Why these questions.** Every one has a trap that metadata resolves and a
schema does not — a grain that invites summing across dates, a measure that is
not additive, a term that means something specific here. Questions a schema
alone answers fine are not evidence of anything and are left out. That makes
this a measurement of the metadata's value on the cases where metadata can
matter, which is the honest framing, and it is stated here rather than in a
footnote.

**What this is not.** It is not a benchmark, the sample is small, and one model
at one temperature on one estate generalises to nothing. It is our own number
about our own data, which is the only kind worth quoting.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import urllib.request
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from parvum_governance.metric_views import scan_metric_views
from parvum_governance.publish import build_snapshot

SCHEMA = "workspace.parvum"
DEFAULT_MODEL = "anthropic/claude-haiku-4.5"
DEFAULT_WAREHOUSE_ID = "0fb6ed828ed1e874"

#: Answers are money or counts, so compare at the cent. A model that is right
#: to the dollar and wrong in the last two places has still misunderstood
#: something, and hiding that behind a loose tolerance would flatter both arms
#: of the experiment equally but the governed one more.
TOLERANCE = Decimal("0.01")


@dataclass(frozen=True)
class Question:
    """One question, its correct answer, and the trap it is testing."""

    id: str
    question: str
    truth_sql: str
    #: What a model gets wrong when it has only column names to go on. Recorded
    #: so a reader can judge whether the question is a fair test or a gotcha.
    trap: str
    #: Tables the model is shown for this question — kept narrow so the test is
    #: about understanding, not about finding a needle in the whole catalog.
    tables: tuple[str, ...]


QUESTIONS: tuple[Question, ...] = (
    Question(
        id="latest_wealth",
        question="What is the total wealth of every client, on the most recent date in the data?",
        truth_sql=f"""
            SELECT SUM(total_wealth_usd) AS answer
            FROM {SCHEMA}.gold_client_wealth
            WHERE as_of = (SELECT MAX(as_of) FROM {SCHEMA}.gold_client_wealth)
        """,
        trap=(
            "The table is one row per client per day. Summing it without pinning a date "
            "adds up every day in the series and returns a number roughly 95 times too "
            "large, which still looks like money."
        ),
        tables=("gold_client_wealth",),
    ),
    Question(
        id="net_flow",
        question=(
            "How much money did clients themselves put in or take out, in total, "
            "across the whole period? Not the change in their wealth — the money "
            "that moved in or out."
        ),
        truth_sql=f"SELECT SUM(external_flow_usd) AS answer FROM {SCHEMA}.gold_performance",
        trap=(
            "'Flow' has a specific meaning here: client money entering or leaving, as "
            "opposed to trades and income, which move value between the portfolio's own "
            "pockets. Without the definition a model may reach for the change in wealth."
        ),
        tables=("gold_performance",),
    ),
    Question(
        id="restatement",
        question=(
            "How much of the change in Hartwell Family's wealth came from something "
            "other than market movement or client money?"
        ),
        truth_sql=f"""
            SELECT SUM(restatement_adjustment_usd) AS answer
            FROM {SCHEMA}.gold_performance
            WHERE client_name = 'Hartwell Family'
        """,
        trap=(
            "`restatement_adjustment_usd` is the answer and its name does not say so. "
            "The column comment does: a value change on a declared book-restatement day "
            "that the market did not produce."
        ),
        tables=("gold_performance",),
    ),
    Question(
        id="alts_share",
        question=(
            "On the most recent date, what is the total USD value held in the "
            "Alternatives asset class across all clients?"
        ),
        truth_sql=f"""
            SELECT SUM(value_usd) AS answer
            FROM {SCHEMA}.gold_asset_allocation
            WHERE asset_class = 'Alternatives'
              AND as_of = (SELECT MAX(as_of) FROM {SCHEMA}.gold_asset_allocation)
        """,
        trap=(
            "Same grain trap as the first question, one table over, plus the need to "
            "know that Alternatives is an asset class in this table rather than a "
            "separate one."
        ),
        tables=("gold_asset_allocation",),
    ),
    Question(
        id="called_capital",
        question="What is the total capital called to date across all private-fund positions?",
        truth_sql=f"SELECT SUM(called_to_date_usd) AS answer FROM {SCHEMA}.gold_alts_holdings",
        trap=(
            "`called_to_date_usd` and `total_commitment_usd` sit next to each other and "
            "a model may pick the wrong one, or sum `unfunded_commitment_usd` believing "
            "it is the complement it needs rather than the one it has."
        ),
        tables=("gold_alts_holdings",),
    ),
    Question(
        id="unreconciled_clients",
        question=(
            "How many distinct clients had at least one date where their books did not reconcile?"
        ),
        truth_sql=f"""
            SELECT COUNT(DISTINCT client_id) AS answer
            FROM {SCHEMA}.gold_client_wealth
            WHERE books_reconcile = false
        """,
        trap=(
            "One row per client per day again: counting rows rather than distinct "
            "clients answers a different question and returns a much larger number."
        ),
        tables=("gold_client_wealth",),
    ),
    Question(
        id="shared_account",
        question="How many accounts are owned by more than one client family?",
        truth_sql=f"""
            SELECT COUNT(DISTINCT account_id) AS answer
            FROM {SCHEMA}.gold_ownership
            WHERE owner_count > 1
        """,
        trap=(
            "`is_shared` and `owner_count` both exist; counting rows instead of distinct "
            "accounts double-counts a shared account exactly once per owner, which is "
            "the specific error the ownership tables are shaped to prevent."
        ),
        tables=("gold_ownership",),
    ),
    Question(
        id="income_total",
        question="What is the total dividend income across all clients and all months?",
        truth_sql=f"""
            SELECT SUM(income_usd) AS answer
            FROM {SCHEMA}.gold_income
            WHERE type = 'DIVIDEND'
        """,
        trap=(
            "`type` carries DIVIDEND and INTEREST and the question asks for one of them. "
            "Without knowing the vocabulary a model may return both, or filter on a "
            "value that does not exist."
        ),
        tables=("gold_income",),
    ),
)


@dataclass
class Answer:
    """One model answer in one condition."""

    question_id: str
    condition: str
    sql: str
    value: Decimal | None = None
    error: str | None = None
    correct: bool = False


@dataclass
class EvalResult:
    truth: dict[str, Decimal] = field(default_factory=dict)
    answers: list[Answer] = field(default_factory=list)

    def score(self, condition: str) -> tuple[int, int]:
        rows = [a for a in self.answers if a.condition == condition]
        return sum(1 for a in rows if a.correct), len(rows)


# --------------------------------------------------------------------------
# Context builders — the whole experiment is the difference between these two.
# --------------------------------------------------------------------------


def bare_context(repo_root: Path, tables: tuple[str, ...]) -> str:
    """Column names and nothing else: a warehouse with no metadata."""
    rows = [r for r in build_snapshot(repo_root) if r.table_name in tables]
    lines = []
    for table in tables:
        columns = [r.column_name for r in rows if r.table_name == table]
        lines.append(f"TABLE {SCHEMA}.{table}({', '.join(columns)})")
    return "\n".join(lines)


def governed_context(repo_root: Path, tables: tuple[str, ...]) -> str:
    """The same tables, plus every piece of metadata governance produces."""
    rows = [r for r in build_snapshot(repo_root) if r.table_name in tables]
    lines: list[str] = []
    for table in tables:
        lines.append(f"TABLE {SCHEMA}.{table}")
        for row in (r for r in rows if r.table_name == table):
            note = f"  {row.column_name}: {row.description}"
            if row.tier == "critical" and row.definition:
                note += f"\n    [critical] {' '.join(row.definition.split())}"
            lines.append(note)
        lines.append("")

    fields = scan_metric_views(repo_root / "spark" / "metric_views")
    if fields:
        lines.append("GOVERNED MEASURES (semantic layer):")
        for f in fields:
            if f.kind == "measure":
                lines.append(f"  {f.view}.{f.name} = {f.expr} — {f.description}")
    return "\n".join(lines)


PROMPT = """You are writing a single Databricks SQL query against a lakehouse.

{context}

Question: {question}

Return ONLY the SQL. It must return exactly one row and one column, aliased as
`answer`. No explanation, no markdown fences."""


# --------------------------------------------------------------------------
# Execution
# --------------------------------------------------------------------------


def _token(host: str) -> str:
    token = os.environ.get("DATABRICKS_TOKEN")
    if token:
        return token
    out = subprocess.run(
        ["databricks", "auth", "token", "--host", host],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(out.stdout)["access_token"]


def run_sql(statement: str) -> Decimal:
    """Run a one-cell query and return its value."""
    host = os.environ["DATABRICKS_HOST"].rstrip("/")
    warehouse = os.environ.get("DATABRICKS_WAREHOUSE_ID", DEFAULT_WAREHOUSE_ID)
    body = json.dumps(
        {"warehouse_id": warehouse, "statement": statement, "wait_timeout": "50s"}
    ).encode()
    request = urllib.request.Request(
        f"{host}/api/2.0/sql/statements",
        data=body,
        headers={
            "Authorization": f"Bearer {_token(host)}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request) as response:
        result = json.load(response)
    state = result.get("status", {}).get("state")
    if state != "SUCCEEDED":
        message = result.get("status", {}).get("error", {}).get("message", state)
        raise RuntimeError(str(message)[:300])
    data = (result.get("result") or {}).get("data_array") or []
    if not data or data[0][0] is None:
        raise RuntimeError("query returned no value")
    return Decimal(str(data[0][0]))


_FENCE = re.compile(r"```(?:sql)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


def clean_sql(raw: str) -> str:
    """Models add fences and prose however firmly the prompt asks them not to."""
    match = _FENCE.search(raw)
    text = match.group(1) if match else raw
    return text.strip().rstrip(";").strip()


# --------------------------------------------------------------------------
# The run
# --------------------------------------------------------------------------


def ask_openrouter(prompt: str, model: str = DEFAULT_MODEL) -> str:
    """One completion. Temperature 0 so a re-run is comparable, not a new sample."""
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY is not set")
    body = json.dumps(
        {
            "model": model,
            "temperature": 0,
            "messages": [{"role": "user", "content": prompt}],
        }
    ).encode()
    request = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request) as response:
        payload = json.load(response)
    return payload["choices"][0]["message"]["content"]


def ask_anthropic(prompt: str, model: str = "claude-haiku-4-5-20251001") -> str:
    """The same completion through the Anthropic API — two providers, one shape.

    Mirrors the alts pipeline's provider abstraction (D-052): whichever one has
    credit can run the eval, and the result is comparable because the prompt
    and the temperature are identical.
    """
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")
    body = json.dumps(
        {
            "model": model,
            "max_tokens": 1024,
            "temperature": 0,
            "messages": [{"role": "user", "content": prompt}],
        }
    ).encode()
    request = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=body,
        headers={
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request) as response:
        payload = json.load(response)
    return "".join(block.get("text", "") for block in payload.get("content", []))


PROVIDERS = {"openrouter": ask_openrouter, "anthropic": ask_anthropic}


def run_eval(repo_root: Path, ask=ask_openrouter, execute=run_sql) -> EvalResult:
    """Both conditions, every question, against the real warehouse.

    `ask` and `execute` are injected so the harness is testable without a
    network — the tests drive it with a scripted model and a fake warehouse.
    """
    result = EvalResult()
    for question in QUESTIONS:
        result.truth[question.id] = execute(question.truth_sql)

    for question in QUESTIONS:
        for condition, builder in (("bare", bare_context), ("governed", governed_context)):
            prompt = PROMPT.format(
                context=builder(repo_root, question.tables), question=question.question
            )
            answer = Answer(question_id=question.id, condition=condition, sql="")
            try:
                answer.sql = clean_sql(ask(prompt))
                answer.value = execute(answer.sql)
                # A wrong answer that runs is the interesting failure: it looks
                # like an answer. An answer that errors is merely useless.
                answer.correct = abs(answer.value - result.truth[question.id]) <= TOLERANCE
            except Exception as error:
                answer.error = str(error)[:200]
            result.answers.append(answer)
    return result


def render(result: EvalResult) -> str:
    """A report that shows the working, not just the score.

    Deliberately ASCII: this prints to a Windows console under cp1252 as
    readily as to a UTF-8 one, and a report that crashes the run it is
    reporting on is not a report.
    """
    lines = ["Governance eval - does the metadata change the answer?", ""]
    lines.append(f"{'question':<22} {'truth':>18}  {'bare':>24}  {'governed':>24}")
    lines.append("-" * 94)
    by_key = {(a.question_id, a.condition): a for a in result.answers}
    for question in QUESTIONS:
        truth = result.truth.get(question.id)
        cells = []
        for condition in ("bare", "governed"):
            answer = by_key.get((question.id, condition))
            if answer is None:
                cells.append("—")
            elif answer.error:
                cells.append("ERROR")
            else:
                mark = "ok" if answer.correct else "WRONG"
                cells.append(f"{answer.value} {mark}")
        lines.append(f"{question.id:<22} {truth!s:>18}  {cells[0]:>24}  {cells[1]:>24}")

    lines.append("")
    for condition in ("bare", "governed"):
        correct, total = result.score(condition)
        pct = 100.0 * correct / total if total else 0.0
        lines.append(f"{condition:>9}: {correct}/{total} correct ({pct:.0f}%)")
    return "\n".join(lines)
