select
    transcript_id,
    interaction_id,
    process_date,
    customer_id,
    agent_id,
    full_text,
    customer_text,
    agent_text,
    detected_language,
    detected_accent,
    accent_confidence,
    string_split(detected_keywords, ', ')          as keywords,
    try_cast(json(mentioned_entities) as json)     as mentioned_entities,
    detected_intents,
    main_topics,
    transcription_model,
    audio_quality,
    cast(duration_seconds as integer)              as duration_seconds,
    -- generator artefact: unrendered template slots such as {monto} / {moneda}
    regexp_matches(full_text, '\{[a-z_]+\}')       as has_unrendered_placeholder
from {{ ref('typed_call_transcripts') }} src
where {{ not_held('src', 'call_transcripts') }}
