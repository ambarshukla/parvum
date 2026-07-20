"""The generator's filename convention (``generate.py``), shared by
anything that needs to infer a document's type from its file name — the
bronze registration notebook and the extraction step — so it's taught in
one place, not copied and left to drift.
"""

DOC_TYPE_PREFIXES: dict[str, str] = {
    "capital_call_": "capital_call",
    "distribution_": "distribution",
    "capital_account_": "capital_account_statement",
}


def doc_type_for(file_name: str) -> str | None:
    return next(
        (dtype for prefix, dtype in DOC_TYPE_PREFIXES.items() if file_name.startswith(prefix)),
        None,
    )
