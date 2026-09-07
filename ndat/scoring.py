"""Named fantasy-scoring profiles and the small canonical scoring engine."""

from __future__ import annotations

import math
import tomllib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal


RuleType = Literal["linear", "event", "buckets"]


@dataclass(frozen=True)
class Bucket:
    minimum: float
    maximum: float | None
    points: float

    def contains(self, value: float) -> bool:
        return value >= self.minimum and (
            self.maximum is None or value <= self.maximum
        )


@dataclass(frozen=True)
class ScoringRule:
    name: str
    type: RuleType
    category: str
    entity: str
    points: float | None = None
    points_per_unit: float | None = None
    buckets: tuple[Bucket, ...] = ()

    @property
    def source_fields(self) -> tuple[str, ...]:
        """Compatibility/introspection access through the shared source map."""
        mapping = PLAYER_STATS_MAPPINGS.get(self.name)
        return mapping.fields if mapping else ()


@dataclass(frozen=True)
class ScoringProfile:
    name: str
    description: str
    rules: Mapping[str, ScoringRule]
    path: Path


@dataclass(frozen=True)
class ScoreResult:
    total_points: float
    component_points: Mapping[str, float]
    unsupported_components: tuple[str, ...]


@dataclass(frozen=True)
class SourceMapping:
    fields: tuple[str, ...]
    transform: Literal["sum", "field_goal_buckets"] = "sum"
    coverage: str = "directly supported"
    note: str = ""


# This boundary intentionally contains NFLverse names; profile files never do.
PLAYER_STATS_MAPPINGS: Mapping[str, SourceMapping] = {
    "passing_yards": SourceMapping(("passing_yards",)),
    "passing_td": SourceMapping(("passing_tds",)),
    "passing_2pt_conversion": SourceMapping(("passing_2pt_conversions",)),
    "passing_interception": SourceMapping(("passing_interceptions",)),
    "rushing_yards": SourceMapping(("rushing_yards",)),
    "rushing_td": SourceMapping(("rushing_tds",)),
    "rushing_2pt_conversion": SourceMapping(("rushing_2pt_conversions",)),
    "reception": SourceMapping(("receptions",)),
    "receiving_yards": SourceMapping(("receiving_yards",)),
    "receiving_td": SourceMapping(("receiving_tds",)),
    "receiving_2pt_conversion": SourceMapping(("receiving_2pt_conversions",)),
    "field_goal_distance": SourceMapping(
        (
            "fg_made_0_19",
            "fg_made_20_29",
            "fg_made_30_39",
            "fg_made_40_49",
            "fg_made_50_59",
            "fg_made_60_",
        ),
        "field_goal_buckets",
    ),
    "pat_made": SourceMapping(("pat_made",)),
    "field_goal_missed": SourceMapping(("fg_missed",)),
    "pat_missed": SourceMapping(("pat_missed",)),
    "special_teams_player_td": SourceMapping(("special_teams_tds",)),
    "fumble_lost": SourceMapping(("fumbles_lost_total",)),
    "fumble_recovery_td": SourceMapping(("fumble_recovery_tds",)),
    "sack": SourceMapping(("def_sacks",)),
    "total_tackle": SourceMapping(("def_tackles_solo", "def_tackles_with_assist")),
    "blocked_kick": SourceMapping(
        ("def_punt_blocks", "def_pat_blocks", "def_fg_blocks")
    ),
    "interception": SourceMapping(("def_interceptions",)),
    "fumble_recovery": SourceMapping(("fumble_recovery_opp",)),
    "forced_fumble": SourceMapping(("def_fumbles_forced",)),
    "safety": SourceMapping(("def_safeties",)),
    "pass_defended": SourceMapping(("def_pass_defended",)),
}


# Coverage is broader than the one-row adapter above. It records how a future
# team-game adapter can obtain every LoB category without pretending it exists now.
SOURCE_FIELD_COVERAGE: Mapping[str, SourceMapping] = {
    **PLAYER_STATS_MAPPINGS,
    "stuff": SourceMapping(
        (
            "rush_attempt",
            "yards_gained",
            "tackle_for_loss_1_player_id",
            "solo_tackle_1_player_id",
            "tackle_with_assist_1_player_id",
        ),
        coverage="requires play-by-play aggregation",
        note=(
            "Zero/negative rushes use TFL credit when available on negative plays, "
            "otherwise primary tackle credit; shared credit is split."
        ),
    ),
    "defensive_td": SourceMapping(
        ("def_tds",),
        coverage="derivable from existing fields",
        note="Sum player_stats by defense/game.",
    ),
    "points_allowed": SourceMapping(
        ("home_score", "away_score"),
        coverage="derivable from existing fields",
        note="Select the opponent score from schedules for each team/game.",
    ),
    "yards_allowed": SourceMapping(
        ("posteam", "yards_gained"),
        coverage="requires play-by-play aggregation",
        note=(
            "Aggregate opponent offensive yards; formal total-yard semantics must "
            "be fixed before materializing a DST view."
        ),
    ),
    "defensive_sack": SourceMapping(
        ("def_sacks",),
        coverage="derivable from existing fields",
        note="Sum player_stats by defense/game; fractional sacks aggregate naturally.",
    ),
    "defensive_interception": SourceMapping(
        ("def_interceptions",),
        coverage="derivable from existing fields",
        note="Sum player_stats by defense/game.",
    ),
    "defensive_fumble_recovery": SourceMapping(
        ("fumble_recovery_opp",),
        coverage="derivable from existing fields",
        note=(
            "Sum defensive player recoveries by team/game; verify shared-credit "
            "behavior before materializing."
        ),
    ),
    "defensive_safety": SourceMapping(
        ("def_safeties",),
        coverage="derivable from existing fields",
        note="Sum player_stats by defense/game.",
    ),
    "defensive_forced_fumble": SourceMapping(
        ("def_fumbles_forced",),
        coverage="derivable from existing fields",
        note="Sum player_stats by defense/game.",
    ),
    "special_teams_defense_td": SourceMapping(
        ("return_touchdown", "return_team"),
        coverage="requires play-by-play aggregation",
        note="Classify special-teams returns and score the team unit.",
    ),
    "special_teams_defense_forced_fumble": SourceMapping(
        ("special_teams_play", "forced_fumble_player_1_team"),
        coverage="requires play-by-play aggregation",
        note="Requires play classification and team attribution.",
    ),
    "special_teams_defense_fumble_recovery": SourceMapping(
        ("special_teams_play", "fumble_recovery_1_team"),
        coverage="requires play-by-play aggregation",
        note="Requires play classification and team attribution.",
    ),
    "special_teams_player_forced_fumble": SourceMapping(
        ("special_teams_play", "forced_fumble_player_1_player_id"),
        coverage="requires play-by-play aggregation",
        note="No direct weekly player_stats field.",
    ),
    "special_teams_player_fumble_recovery": SourceMapping(
        ("special_teams_play", "fumble_recovery_1_player_id"),
        coverage="requires play-by-play aggregation",
        note="No direct weekly player_stats field.",
    ),
}


PROFILE_DIRECTORY = Path(__file__).with_name("scoring_profiles")
PROFILE_FILES = {"LoB": "lob.toml", "Stage3_IDP": "stage3_idp.toml"}


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{label} must be finite")
    return result


def validate_profile(data: Mapping[str, Any], *, path: Path) -> ScoringProfile:
    if data.get("schema_version") != 1:
        raise ValueError(f"{path}: unsupported or missing schema_version")
    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError(f"{path}: profile name must be a non-empty string")
    raw_rules = data.get("rules")
    if not isinstance(raw_rules, dict) or not raw_rules:
        raise ValueError(f"{path}: profile must contain rules")
    rules: dict[str, ScoringRule] = {}
    for rule_name, raw in raw_rules.items():
        if not isinstance(raw, dict):
            raise ValueError(f"{path}: rule {rule_name!r} must be a table")
        rule_type = raw.get("type")
        if rule_type not in {"linear", "event", "buckets"}:
            raise ValueError(f"{path}: rule {rule_name!r} has invalid type")
        category = raw.get("category")
        entity = raw.get("entity")
        if not isinstance(category, str) or not isinstance(entity, str):
            raise ValueError(f"{path}: rule {rule_name!r} needs category and entity")
        points = None
        points_per_unit = None
        buckets: tuple[Bucket, ...] = ()
        if rule_type == "linear":
            points_per_unit = _number(
                raw.get("points_per_unit"), f"{rule_name}.points_per_unit"
            )
        elif rule_type == "event":
            points = _number(raw.get("points"), f"{rule_name}.points")
        else:
            raw_buckets = raw.get("buckets")
            if not isinstance(raw_buckets, list) or not raw_buckets:
                raise ValueError(f"{path}: bucket rule {rule_name!r} needs buckets")
            parsed: list[Bucket] = []
            for index, raw_bucket in enumerate(raw_buckets):
                minimum = _number(
                    raw_bucket.get("min"), f"{rule_name}.buckets[{index}].min"
                )
                maximum = raw_bucket.get("max")
                maximum = (
                    None
                    if maximum is None
                    else _number(maximum, f"{rule_name}.buckets[{index}].max")
                )
                if maximum is not None and maximum < minimum:
                    raise ValueError(f"{path}: bucket maximum precedes minimum")
                parsed.append(
                    Bucket(
                        minimum,
                        maximum,
                        _number(
                            raw_bucket.get("points"),
                            f"{rule_name}.buckets[{index}].points",
                        ),
                    )
                )
            parsed.sort(key=lambda bucket: bucket.minimum)
            for previous, current in zip(parsed, parsed[1:]):
                if previous.maximum is None or current.minimum <= previous.maximum:
                    raise ValueError(f"{path}: overlapping buckets in {rule_name!r}")
            buckets = tuple(parsed)
        rules[rule_name] = ScoringRule(
            rule_name, rule_type, category, entity, points, points_per_unit, buckets
        )
    return ScoringProfile(
        name=name,
        description=str(data.get("description", "")),
        rules=rules,
        path=path,
    )


def load_profile(name: str) -> ScoringProfile:
    """Load and validate a stable, human-readable named profile."""
    try:
        path = PROFILE_DIRECTORY / PROFILE_FILES[name]
    except KeyError as error:
        raise ValueError(
            f"Unknown scoring profile {name!r}; choose one of: {', '.join(PROFILE_FILES)}"
        ) from error
    with path.open("rb") as stream:
        return validate_profile(tomllib.load(stream), path=path)


def _score_bucket(rule: ScoringRule, value: float) -> float:
    for bucket in rule.buckets:
        if bucket.contains(value):
            return bucket.points
    raise ValueError(f"Value {value} is outside all buckets for {rule.name!r}")


def score_record(
    record: Mapping[str, Any],
    profile: str | ScoringProfile = "LoB",
    *,
    entity: str = "player",
) -> ScoreResult:
    """Score canonical NDAT stats, retaining components and unavailable names."""
    scoring_profile = load_profile(profile) if isinstance(profile, str) else profile
    components: dict[str, float] = {}
    unsupported: list[str] = []
    for name, rule in scoring_profile.rules.items():
        if rule.entity != entity:
            continue
        if name not in record:
            unsupported.append(name)
            continue
        value = record[name]
        if value is None:
            components[name] = 0.0
            continue
        if rule.type == "buckets":
            values: Iterable[Any] = (
                value if isinstance(value, (list, tuple)) else (value,)
            )
            component = sum(
                _score_bucket(rule, _number(item, name))
                for item in values
                if item is not None
            )
        else:
            numeric = _number(value, name)
            multiplier = rule.points_per_unit if rule.type == "linear" else rule.points
            component = numeric * float(multiplier)
        components[name] = float(component)
    return ScoreResult(float(sum(components.values())), components, tuple(unsupported))


def canonicalize_player_stats(
    record: Mapping[str, Any],
) -> tuple[dict[str, Any], tuple[str, ...]]:
    """Translate one NFLverse weekly player-stat record to canonical NDAT stats."""
    canonical: dict[str, Any] = {}
    unavailable: list[str] = []
    bucket_representatives = (0, 20, 30, 40, 50, 60)
    for name, mapping in PLAYER_STATS_MAPPINGS.items():
        if not all(field in record for field in mapping.fields):
            unavailable.append(name)
            continue
        if mapping.transform == "field_goal_buckets":
            distances: list[int] = []
            for field, representative in zip(
                mapping.fields, bucket_representatives, strict=True
            ):
                count = record[field]
                count = 0 if count is None else int(count)
                distances.extend([representative] * count)
            canonical[name] = distances
        else:
            canonical[name] = sum(
                0.0 if record[field] is None else float(record[field])
                for field in mapping.fields
            )
    return canonical, tuple(unavailable)


def score_player(
    record: Mapping[str, Any], profile: str | ScoringProfile = "LoB"
) -> ScoreResult:
    """Score one NFLverse weekly player-stat row through the canonical mapping."""
    canonical, _ = canonicalize_player_stats(record)
    return score_record(canonical, profile, entity="player")


def player_stats_scoring_sql(
    profile: str | ScoringProfile = "LoB", *, table_alias: str = "pg"
) -> tuple[dict[str, str], tuple[str, ...]]:
    """Compile supported player-profile components to inspectable DuckDB SQL."""
    scoring_profile = load_profile(profile) if isinstance(profile, str) else profile
    expressions: dict[str, str] = {}
    unsupported: list[str] = []
    for name, rule in scoring_profile.rules.items():
        if rule.entity != "player":
            continue
        mapping = PLAYER_STATS_MAPPINGS.get(name)
        if mapping is None:
            unsupported.append(name)
            continue
        fields = [f'coalesce({table_alias}."{field}", 0)' for field in mapping.fields]
        if mapping.transform == "field_goal_buckets":
            representatives = (0, 20, 30, 40, 50, 60)
            terms = [
                f"({field}) * {_score_bucket(rule, representative)}"
                for field, representative in zip(fields, representatives, strict=True)
            ]
            expressions[name] = " + ".join(terms)
        else:
            multiplier = rule.points_per_unit if rule.type == "linear" else rule.points
            expressions[name] = f"({' + '.join(fields)}) * {float(multiplier)}"
    return expressions, tuple(unsupported)
