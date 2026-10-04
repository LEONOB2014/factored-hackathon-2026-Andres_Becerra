-- Customer-experience journey: one row per contact-centre interaction with its transcript, survey,
-- the next contact (first-contact-resolution proxy) and the agent, ready for CX analytics, QA sampling,
-- complaint-escalation models and copilot retrieval.
with i as (
    select
        i.*,
        lead(interaction_ts_utc) over (partition by customer_id order by interaction_ts_utc, interaction_id) as next_contact_ts,
        lead(contact_reason)     over (partition by customer_id order by interaction_ts_utc, interaction_id) as next_contact_reason,
        count(*) over (partition by customer_id order by interaction_ts_utc
                       range between interval 30 day preceding and current row exclude current row) as prior_contacts_30d
    from {{ ref('stg_call_center_interactions') }} i
),
srv as (
    select interaction_id, arg_max(main_score, (survey_ts_utc, survey_id)) as survey_score, arg_max(survey_type, (survey_ts_utc, survey_id)) as survey_type,
           arg_max(comment_sentiment, (survey_ts_utc, survey_id)) as survey_comment_sentiment
    from {{ ref('stg_satisfaction_surveys') }}
    where interaction_id is not null
    group by 1
),
cmp as (   -- complaints opened by the same customer within 14 days after the contact (escalation label)
    select i.interaction_id, count(k.complaint_id) as complaints_next_14d
    from i
    join {{ ref('stg_complaints') }} k
      on k.customer_id = i.customer_id
     and k.created_ts_utc > i.interaction_ts_utc
     and k.created_ts_utc <= i.interaction_ts_utc + interval 14 day
    group by 1
)
select
    i.interaction_id,
    i.customer_id,
    i.interaction_ts_utc,
    i.interaction_type,
    i.channel,
    i.contact_reason,
    i.duration_seconds,
    i.wait_time_seconds,
    i.was_resolved,
    i.was_escalated,
    i.requires_followup,
    i.detected_sentiment,
    i.sentiment_score,
    i.prior_contacts_30d,
    -- repeat contact within 7 days on the same reason = not resolved at first contact
    coalesce(i.next_contact_ts <= i.interaction_ts_utc + interval 7 day
             and i.next_contact_reason = i.contact_reason, false)   as repeat_contact_7d,
    coalesce(c.complaints_next_14d, 0) > 0                          as complaint_within_14d,
    i.customer_detected_accent = i.agent_used_accent                as accent_matched,
    a.agent_id,
    a.experience_level                                              as agent_experience_level,
    a.agent_type,
    t.transcript_id,
    t.transcription_model,
    t.keywords,
    t.main_topics,
    t.has_unrendered_placeholder                                    as transcript_is_template_artifact,
    s.survey_type,
    s.survey_score,
    s.survey_comment_sentiment
from i
left join {{ ref('stg_service_agents') }} a on a.agent_id = i.agent_id
left join {{ ref('stg_call_transcripts') }} t on t.interaction_id = i.interaction_id
left join srv s on s.interaction_id = i.interaction_id
left join cmp c on c.interaction_id = i.interaction_id
