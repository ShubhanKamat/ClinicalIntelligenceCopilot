SELECT
    primary_program,
    COUNT(*) AS trial_count
FROM trials_v3
WHERE primary_program IS NOT NULL
GROUP BY primary_program
ORDER BY trial_count DESC, primary_program;
