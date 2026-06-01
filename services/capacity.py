"""
services.capacity — canonical capacity computation helpers.

Source of truth:
  available_capacity = total_capacity - count(active_placements where status='active')
"""

from __future__ import annotations


def available_capacity_sql(family_table_alias: str = "f") -> str:
    """
    Returns a SQL expression computing available capacity for a family row.

    Important:
      - Uses active_placements as the source of truth.
      - Filters to status='active' only.
    """
    a = family_table_alias
    return (
        f"({a}.total_capacity - COALESCE("
        f"(SELECT COUNT(*) FROM active_placements ap "
        f" WHERE ap.family_id = {a}.family_id AND ap.status = 'active'), 0))"
    )


def available_families_where_sql(family_table_alias: str = "f") -> str:
    """WHERE predicate to select active families with capacity > 0."""
    expr = available_capacity_sql(family_table_alias)
    a = family_table_alias
    return f"{a}.active = TRUE AND {expr} > 0"

