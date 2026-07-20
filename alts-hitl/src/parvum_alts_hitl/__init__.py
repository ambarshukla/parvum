"""Parvum alts (private-fund) document pipeline: canonical model, a
deterministic synthetic fund book, defect injection, and PDF rendering.
"""

from parvum_alts_hitl.book import FundBook, build_fund_book
from parvum_alts_hitl.defects import (
    DefectConfig,
    DefectType,
    InjectionRecord,
    inject_call,
    inject_distribution,
    inject_statement,
)
from parvum_alts_hitl.model import (
    CapitalAccountStatement,
    CapitalCallNotice,
    DistributionNotice,
    DistributionSource,
    FundCommitment,
)

__all__ = [
    "CapitalAccountStatement",
    "CapitalCallNotice",
    "DefectConfig",
    "DefectType",
    "DistributionNotice",
    "DistributionSource",
    "FundBook",
    "FundCommitment",
    "InjectionRecord",
    "build_fund_book",
    "inject_call",
    "inject_distribution",
    "inject_statement",
]
