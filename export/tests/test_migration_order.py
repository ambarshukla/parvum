"""The test fixtures must apply migrations in Flyway's order, not the filesystem's.

These loader tests exist to prove one schema serves both sides (D-029), which
only holds if the fixture builds the schema the way the serving app does. A
plain filename sort agrees with Flyway's version ordering only while every
version is a single digit — so this went unnoticed through V1-V9 and broke on
V10, which sorts lexicographically right after V1 and therefore altered a table
three migrations before it was created.

Pure Python: no Postgres, so this guard runs everywhere the suite does.
"""

from pathlib import Path

import pytest

from conftest import _INTERNAL_MIGRATIONS, _MIGRATIONS, _flyway_order


def _versions(paths: list[Path]) -> list[int]:
    return [int(p.name.split("__", 1)[0][1:]) for p in _flyway_order(paths)]


def test_double_digit_versions_sort_after_single_digit_ones():
    # The exact failure V10 caused: "V10" < "V2" as a string, so the ALTER ran
    # before the CREATE. Names are otherwise irrelevant here.
    names = ["V10__ten.sql", "V2__two.sql", "V1__one.sql", "V9__nine.sql"]
    assert _versions([Path(n) for n in names]) == [1, 2, 9, 10]


def test_the_real_projection_migrations_are_ordered_by_version():
    versions = _versions(list(_MIGRATIONS.glob("V*.sql")))
    assert versions == sorted(versions)
    assert versions == list(range(1, len(versions) + 1)), (
        f"projection migrations should be a gapless V1..Vn series, got {versions}"
    )


def test_the_real_internal_migrations_are_ordered_by_version():
    versions = _versions(list(_INTERNAL_MIGRATIONS.glob("V*.sql")))
    assert versions == sorted(versions)


def test_performance_is_created_before_it_is_altered():
    # The specific invariant the CI break violated, pinned against the real
    # files rather than a synthetic list: whichever migration creates the
    # `performance` table must be applied before any migration that alters it.
    ordered = _flyway_order(list(_MIGRATIONS.glob("V*.sql")))
    creates_at = None
    for index, path in enumerate(ordered):
        body = path.read_text(encoding="utf-8").lower()
        if "create table performance (" in body:
            creates_at = index
        if "alter table performance " in body:
            assert creates_at is not None and creates_at < index, (
                f"{path.name} alters `performance` before any migration creates it"
            )


def test_an_unversioned_file_fails_loudly_rather_than_sorting_somewhere():
    # Silently ordering a file the fixture cannot parse would reintroduce the
    # same class of bug with a different shape.
    with pytest.raises(AssertionError, match="not a Flyway-versioned migration"):
        _flyway_order([Path("R__repeatable.sql")])
