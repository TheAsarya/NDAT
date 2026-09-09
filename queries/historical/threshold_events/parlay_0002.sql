/*
puka, jjeff, ceedee 60+, mcconkey 40+
Define the historical WR1 cohort as:
the top 12 WRs by regular-season receiving yards in each season.

Then, for each regular-season week, take the top-12 receivers who actually recorded a player-game and examine every possible four-player combination. For each quartet, designate one receiver as the 40+ leg and the other three as 60+ legs.
That lets us estimate an empirical envelope rather than pretending there is one exact probability:
- overall historical hit rate;
- season-by-season hit rate;
- week-to-week range;
- median week;
- perhaps 25th/75th percentiles.
*/
WITH season_wr AS (
    SELECT
        season,
        player_id,
        max(player_display_name) AS player_name,
        sum(receiving_yards) AS season_receiving_yards
    FROM player_game
    WHERE season BETWEEN 2021 AND 2025
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

top12 AS (
    SELECT
        season,
        player_id,
        player_name,
        season_receiving_yards,
        season_wr_rank
    FROM ranked_wr
    WHERE season_wr_rank <= 12
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
    INNER JOIN top12 AS t
        ON pg.season = t.season
       AND pg.player_id = t.player_id
    WHERE pg.season BETWEEN 2021 AND 2025
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
        p1_yards >= 40
            AND p2_yards >= 60
            AND p3_yards >= 60
            AND p4_yards >= 60 AS hit
    FROM quartets

    UNION ALL

    SELECT
        season,
        week,
        p1_yards >= 60
            AND p2_yards >= 40
            AND p3_yards >= 60
            AND p4_yards >= 60
    FROM quartets

    UNION ALL

    SELECT
        season,
        week,
        p1_yards >= 60
            AND p2_yards >= 60
            AND p3_yards >= 40
            AND p4_yards >= 60
    FROM quartets

    UNION ALL

    SELECT
        season,
        week,
        p1_yards >= 60
            AND p2_yards >= 60
            AND p3_yards >= 60
            AND p4_yards >= 40
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
    round(100.0 * hit_rate, 2) AS hit_pct
FROM weekly_rates
ORDER BY season, week
