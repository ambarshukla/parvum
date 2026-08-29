"""The eval harness, driven by a scripted model and a fake warehouse.

No network and no lakehouse: the point of these tests is that the *experiment*
is sound — that both arms get the same question, that the two contexts really
do differ in the way claimed, and that a wrong-but-runnable answer scores as
wrong rather than as an error.
"""

from __future__ import annotations

from decimal import Decimal

from parvum_governance.check import find_repo_root
from parvum_governance.evaluation import (
    QUESTIONS,
    bare_context,
    clean_sql,
    governed_context,
    render,
    run_eval,
)

ROOT = find_repo_root()


def test_every_question_names_the_trap_it_is_testing():
    # A question with no stated trap is a gotcha, and a reader cannot tell
    # whether the experiment is fair without seeing what each one tests.
    for question in QUESTIONS:
        assert question.trap.strip(), question.id
        assert question.tables
        assert "answer" in question.truth_sql


def test_question_ids_are_unique():
    ids = [q.id for q in QUESTIONS]
    assert len(ids) == len(set(ids))


def test_the_bare_context_really_is_bare():
    # If the "without" arm leaked descriptions the whole result would be
    # meaningless, so this is the assertion the experiment rests on.
    question = next(q for q in QUESTIONS if q.id == "latest_wealth")
    bare = bare_context(ROOT, question.tables)
    assert "total_wealth_usd" in bare
    assert "headline" not in bare.lower()
    assert "grain" not in bare.lower()
    # One line per table, and nothing else.
    assert len(bare.splitlines()) == len(question.tables)


def test_the_governed_context_carries_definitions_and_measures():
    question = next(q for q in QUESTIONS if q.id == "latest_wealth")
    governed = governed_context(ROOT, question.tables)
    assert "total_wealth_usd" in governed
    assert "[critical]" in governed
    assert "GOVERNED MEASURES" in governed
    assert len(governed) > len(bare_context(ROOT, question.tables))


def test_clean_sql_strips_fences_and_semicolons():
    assert clean_sql("```sql\nSELECT 1 AS answer;\n```") == "SELECT 1 AS answer"
    assert clean_sql("SELECT 1 AS answer") == "SELECT 1 AS answer"


def test_a_runnable_wrong_answer_scores_as_wrong_not_as_an_error():
    """The failure mode the whole exercise is about: a number that looks fine."""
    truth = {q.id: Decimal("100") for q in QUESTIONS}

    def execute(sql: str) -> Decimal:
        if sql.startswith("TRUTH:"):
            return truth[sql.removeprefix("TRUTH:")]
        return Decimal("100") if "governed" in sql else Decimal("9500")

    def fake_execute(sql: str) -> Decimal:
        for question in QUESTIONS:
            if sql == question.truth_sql:
                return truth[question.id]
        return execute(sql)

    def ask(prompt: str) -> str:
        # The governed context is the one carrying definitions, so key off it.
        return "SELECT governed" if "[critical]" in prompt else "SELECT bare"

    result = run_eval(ROOT, ask=ask, execute=fake_execute)

    assert result.score("bare") == (0, len(QUESTIONS))
    assert result.score("governed") == (len(QUESTIONS), len(QUESTIONS))
    bare_answers = [a for a in result.answers if a.condition == "bare"]
    assert all(a.error is None for a in bare_answers), "wrong is not the same as broken"
    assert all(a.value == Decimal("9500") for a in bare_answers)


def test_an_answer_that_fails_to_run_is_recorded_rather_than_raised():
    def ask(prompt: str) -> str:
        return "SELECT nonsense"

    def execute(sql: str) -> Decimal:
        for question in QUESTIONS:
            if sql == question.truth_sql:
                return Decimal("1")
        raise RuntimeError("syntax error")

    result = run_eval(ROOT, ask=ask, execute=execute)
    assert result.score("bare") == (0, len(QUESTIONS))
    assert all(a.error for a in result.answers)
    assert "syntax error" in result.answers[0].error


def test_the_report_shows_both_scores():
    def ask(prompt: str) -> str:
        return "SELECT 1"

    def execute(sql: str) -> Decimal:
        return Decimal("1")

    report = render(run_eval(ROOT, ask=ask, execute=execute))
    assert "bare:" in report
    assert "governed:" in report
