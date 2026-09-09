/*
puka, jjeff, ceedee 60+, mcconkey 40+
returns weeks parlay hit
*/
WITH selected AS (
    SELECT
        season,
        week,
        player_display_name,
        receiving_yards
    FROM player_game
    WHERE season_type = 'REG'
      AND player_display_name IN (
          'Puka Nacua',
          'Justin Jefferson',
          'CeeDee Lamb',
          'Ladd McConkey'
      )
),

weekly AS (
    SELECT
        season,
        week,
        max(CASE WHEN player_display_name = 'Puka Nacua'
            THEN receiving_yards END) AS puka_yards,
        max(CASE WHEN player_display_name = 'Justin Jefferson'
            THEN receiving_yards END) AS jefferson_yards,
        max(CASE WHEN player_display_name = 'CeeDee Lamb'
            THEN receiving_yards END) AS lamb_yards,
        max(CASE WHEN player_display_name = 'Ladd McConkey'
            THEN receiving_yards END) AS mcconkey_yards
    FROM selected
    GROUP BY season, week
)

SELECT
    season,
    week,
    puka_yards,
    jefferson_yards,
    lamb_yards,
    mcconkey_yards
FROM weekly
WHERE puka_yards >= 60
  AND jefferson_yards >= 60
  AND lamb_yards >= 60
  AND mcconkey_yards >= 40
ORDER BY season, week
