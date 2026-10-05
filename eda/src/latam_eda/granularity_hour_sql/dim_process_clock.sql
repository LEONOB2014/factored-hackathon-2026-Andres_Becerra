-- The declared clock of each process (ADR-014): the shift that maps a UTC timestamp to its delivery day and its hour of
-- the business day. Surveys have no fixed window (about 42 hours) and are placed on the transaction clock.
-- grain: process
select * from (values
    ('transactions', -6), ('digital_events', -6), ('campaign_sends', -6), ('satisfaction_surveys', -6),
    ('call_center_interactions', -8), ('complaints', -8)) v(process, utc_offset_hours)
