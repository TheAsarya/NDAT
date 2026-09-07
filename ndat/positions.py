"""Conservative position normalization without replacing source labels."""

from __future__ import annotations


POSITION_ALIASES = {
    "HB": "RB",
    "FB": "RB",
    "SAF": "S",
    "FS": "S",
    "SS": "S",
}


def normalize_position(
    raw_position: str | None,
    *,
    depth_chart_position: str | None = None,
    ngs_position: str | None = None,
) -> str | None:
    """Return a conservative analytical label while callers retain the raw value."""
    if ngs_position == "EDGE":
        return "EDGE"
    raw = raw_position.upper() if raw_position else None
    depth = depth_chart_position.upper() if depth_chart_position else None
    if raw == "LB" and depth in {"ILB", "MLB"}:
        return "LB"
    return POSITION_ALIASES.get(raw, raw)


def position_sql(column: str = "position") -> str:
    """Equivalent SQL expression for sources without roster/NGS evidence."""
    return (
        f"CASE upper({column}) "
        "WHEN 'HB' THEN 'RB' WHEN 'FB' THEN 'RB' "
        "WHEN 'SAF' THEN 'S' WHEN 'FS' THEN 'S' WHEN 'SS' THEN 'S' "
        f"ELSE upper({column}) END"
    )
