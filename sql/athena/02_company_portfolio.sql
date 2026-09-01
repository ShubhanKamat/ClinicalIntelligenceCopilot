SELECT
    canonical_company,
    COUNT(*) AS trial_count,
    SUM(
        CASE
            WHEN overall_status IN (
                'RECRUITING',
                'ACTIVE_NOT_RECRUITING',
                'NOT_YET_RECRUITING',
                'ENROLLING_BY_INVITATION'
            )
            THEN 1
            ELSE 0
        END
    ) AS active_trial_count,
    ROUND(
        100.0
        * SUM(
            CASE
                WHEN overall_status IN (
                    'RECRUITING',
                    'ACTIVE_NOT_RECRUITING',
                    'NOT_YET_RECRUITING',
                    'ENROLLING_BY_INVITATION'
                )
                THEN 1
                ELSE 0
            END
        )
        / COUNT(*),
        1
    ) AS active_share_pct
FROM trials_v3
GROUP BY canonical_company
ORDER BY canonical_company;
