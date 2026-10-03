select
    survey_id,
    survey_date                                    as survey_ts_utc,
    process_date,
    interaction_id,
    customer_id,
    agent_id,
    survey_type,
    send_channel,
    main_score,
    nps_category,
    question_1_response, question_2_response, question_3_response,
    open_comments,
    comment_sentiment,
    response_time_hours
from {{ source('raw', 'satisfaction_surveys') }}
