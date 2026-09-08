WITH population AS (
    SELECT *
    FROM player_game
    WHERE season BETWEEN $start_season AND $end_season
      AND season_type = 'REG'
      AND canonical_position = upper($position)
), qualifying AS (
    SELECT *
    FROM population
    WHERE coalesce(receiving_yards, 0) >= $yards
      AND coalesce(receiving_tds, 0) >= $touchdowns
), totals AS (
    SELECT
        count(*) AS denominator_player_games,
        (SELECT count(*) FROM qualifying) AS qualifying_player_games
    FROM population
), by_season AS (
    SELECT
        season,
        count(*) AS denominator_player_games,
        count(*) FILTER (
            WHERE coalesce(receiving_yards, 0) >= $yards
              AND coalesce(receiving_tds, 0) >= $touchdowns
        ) AS qualifying_player_games
    FROM population
    GROUP BY season
)
SELECT
    by_season.season,
    q.week,
    q.game_id,
    q.player_id,
    q.player_display_name AS player_name,
    q.canonical_position AS position,
    q.team,
    q.receiving_yards,
    q.receiving_tds,
    q.player_id IS NOT NULL AS qualifies,
    totals.qualifying_player_games AS matches,
    totals.denominator_player_games AS population,
    round(100.0 * totals.qualifying_player_games / nullif(totals.denominator_player_games, 0), 6)
        AS pct,
    round(totals.denominator_player_games::DOUBLE / nullif(totals.qualifying_player_games, 0), 2)
        AS one_in_n,
    by_season.qualifying_player_games AS season_matches,
    by_season.denominator_player_games AS season_population
FROM by_season
LEFT JOIN qualifying AS q USING (season)
CROSS JOIN totals
ORDER BY by_season.season, q.week NULLS FIRST, q.game_id, q.player_id
