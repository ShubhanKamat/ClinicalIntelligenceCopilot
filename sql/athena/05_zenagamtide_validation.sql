SELECT
    COUNT(*) AS total_trials,

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
    ) AS active_trials,

    SUM(
        CASE
            WHEN contains(
                phases,
                'PHASE3'
            )
            THEN 1
            ELSE 0
        END
    ) AS phase3_trials

FROM trials_v3

WHERE primary_program = 'Zenagamtide';
