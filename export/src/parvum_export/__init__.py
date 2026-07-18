"""Gold → serving Postgres exporter.

The lakehouse is the system of record; the serving store is a rebuildable
projection of it (D-029). This package pulls the four gold tables over the
Databricks SQL Statements API — pull, not push, because Free Edition compute
has no egress to Postgres (D-006) — splits the rows per tenant, and
truncate-reloads each tenant's schema in one transaction.
"""
