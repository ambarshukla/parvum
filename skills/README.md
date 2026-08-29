# skills/

Agent skills, versioned in the repo like any other artefact.

A skill is a procedure an AI assistant loads when a task matches it. Keeping
them here rather than in someone's personal configuration is the same argument
the CDE register makes about ownership: a procedure that lives in one person's
tooling is that person's habit, and a procedure in the repo is the team's
method — reviewable in a pull request, and correctable when it turns out to be
wrong.

| Skill | What it does |
|---|---|
| [`dataset-discovery-brief`](dataset-discovery-brief/SKILL.md) | Produces a stakeholder-facing brief on a table: what it is, what it answers alone, **what it cannot**, what combines, how it is really used, what is measured about it, and who owns it. |
| [`wrong-number-triage`](wrong-number-triage/SKILL.md) | Investigates a figure that looks wrong. The method derived from D-070, D-072 and D-073 — three defects that reached a live dashboard and were all found by a person rather than a control. |

## Why these two

They are the two things this project actually had to do repeatedly, and both
encode something the estate learned rather than something generically true.

**The discovery brief's load-bearing section is "what you cannot learn from
this alone".** A dataset handed over without its limits gets used past them,
and the wrong answer that results is confident and traceable to nobody. That is
the same instinct as the register's `control_gap`: an admitted gap is
manageable, an unstated one is a surprise.

**The triage skill exists because the same defect shape occurred three times.**
Every figure individually correct; two figures disagreeing about what happened.
It carries the diagnostic question that found D-072 — *does this number move
when the thing it claims to measure has not moved?* — and the citation test
from D-073, which is the discipline that keeps a coverage number honest.

## They read the estate's own metadata

Both skills are instructed to start from `governance/cde_registry.yml`, the
`COLUMN_COMMENTS` in the Spark jobs, and `spark/metric_views/`. That is the
point: the governance work exists so that a person *or a model* arriving cold
can find out what a figure means without asking anyone. A skill that ignored it
and guessed would be evidence the metadata was not worth writing.

How much that metadata is actually worth to a model is measured, not asserted —
see [`docs/GOVERNANCE_EVAL.md`](../docs/GOVERNANCE_EVAL.md).
