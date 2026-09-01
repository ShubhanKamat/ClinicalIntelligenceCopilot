WITH ranked AS (
    SELECT
        canonical_company,
        CAST(enrollment AS DOUBLE) AS enrollment,
        ROW_NUMBER() OVER (
            PARTITION BY canonical_company
            ORDER BY enrollment
        ) AS rn,
        COUNT(*) OVER (
            PARTITION BY canonical_company
        ) AS cnt
    FROM trials_v3
    WHERE enrollment IS NOT NULL
      AND enrollment > 0
)
SELECT
    canonical_company,
    AVG(enrollment) AS median_enrollment
FROM ranked
WHERE rn IN (
    CAST(
        FLOOR((cnt + 1) / 2.0)
        AS BIGINT
    ),
    CAST(
        FLOOR((cnt + 2) / 2.0)
        AS BIGINT
    )
)
GROUP BY canonical_company
ORDER BY canonical_company;
