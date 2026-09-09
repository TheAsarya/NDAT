/* Weekly retrieval for the registered historical.parlay-wr1-envelope analysis.
   DuckDB selects each season's WR cohort, enumerates four-player weekly
   combinations, designates each player once as the reduced-yardage leg, and
   returns weekly hit rates. Python performs sorting and percentile statistics. */
WITH season_wr AS (
    SELECT
        season,
        player_id,
        max(player_display_name) AS player_name,
        sum(receiving_yards) AS season_receiving_yards
    FROM player_game
    WHERE season BETWEEN $start_season AND $end_season
      AND season_type = 'REG'
      AND canonical_position = 'WR'
    GROUP BY season, player_id
),

ranked_wr AS (
    SELECT
        *,
        row_number() OVER (
            PARTITION BY season
            ORDER BY season_receiving_yards DESC, player_id
        ) AS season_wr_rank
    FROM season_wr
),

cohort AS (
    SELECT
        season,
        player_id,
        player_name,
        season_receiving_yards,
        season_wr_rank
    FROM ranked_wr
    WHERE season_wr_rank <= $cohort_size
),

weekly AS (
    SELECT
        pg.season,
        pg.week,
        pg.game_id,
        pg.player_id,
        pg.player_display_name,
        pg.team,
        pg.receiving_yards
    FROM player_game AS pg
    INNER JOIN cohort AS t
        ON pg.season = t.season
       AND pg.player_id = t.player_id
    WHERE pg.season BETWEEN $start_season AND $end_season
      AND pg.season_type = 'REG'
),

quartets AS (
    SELECT
        a.season,
        a.week,

        a.player_id AS p1_id,
        b.player_id AS p2_id,
        c.player_id AS p3_id,
        d.player_id AS p4_id,

        a.receiving_yards AS p1_yards,
        b.receiving_yards AS p2_yards,
        c.receiving_yards AS p3_yards,
        d.receiving_yards AS p4_yards

    FROM weekly a
    JOIN weekly b
      ON b.season = a.season
     AND b.week = a.week
     AND b.player_id > a.player_id
    JOIN weekly c
      ON c.season = a.season
     AND c.week = a.week
     AND c.player_id > b.player_id
    JOIN weekly d
      ON d.season = a.season
     AND d.week = a.week
     AND d.player_id > c.player_id
),

designated AS (
    SELECT
        season,
        week,
        p1_yards >= $reduced_yards
            AND p2_yards >= $standard_yards
            AND p3_yards >= $standard_yards
            AND p4_yards >= $standard_yards AS hit
    FROM quartets

    UNION ALL

    SELECT
        season,
        week,
        p1_yards >= $standard_yards
            AND p2_yards >= $reduced_yards
            AND p3_yards >= $standard_yards
            AND p4_yards >= $standard_yards
    FROM quartets

    UNION ALL

    SELECT
        season,
        week,
        p1_yards >= $standard_yards
            AND p2_yards >= $standard_yards
            AND p3_yards >= $reduced_yards
            AND p4_yards >= $standard_yards
    FROM quartets

    UNION ALL

    SELECT
        season,
        week,
        p1_yards >= $standard_yards
            AND p2_yards >= $standard_yards
            AND p3_yards >= $standard_yards
            AND p4_yards >= $reduced_yards
    FROM quartets
),

weekly_rates AS (
    SELECT
        season,
        week,
        count(*) AS combinations,
        sum(CASE WHEN hit THEN 1 ELSE 0 END) AS hits,
        avg(CASE WHEN hit THEN 1.0 ELSE 0.0 END) AS hit_rate
    FROM designated
    GROUP BY season, week
)

SELECT
    season,
    week,
    combinations,
    hits,
    hit_rate
FROM weekly_rates
ORDER BY season, week
