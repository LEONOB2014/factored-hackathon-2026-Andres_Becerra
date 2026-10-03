{# Use the custom schema name as-is (staging, marts, ...) instead of prefixing the target schema. #}
{% macro generate_schema_name(custom_schema_name, node) -%}
  {{ custom_schema_name if custom_schema_name is not none else target.schema }}
{%- endmacro %}

{# Deterministic fingerprint of the business columns of a row. Nulls are encoded explicitly so that
   NULL -> value changes alter the hash (the backup comparison found exactly this kind of mutation). #}
{% macro row_hash(columns) -%}
  md5(concat_ws('|', {% for c in columns %}coalesce(cast({{ c }} as varchar), '<null>'){% if not loop.last %}, {% endif %}{% endfor %}))
{%- endmacro %}

{# Pseudonymous token for a direct identifier. Locally a salted SHA-256; in production replace with a
   keyed HMAC from a KMS/HSM-backed tokenization service so tokens cannot be brute-forced. #}
{% macro pii_hash(col) -%}
  sha256(concat('{{ env_var("LATAM_PII_SALT", "local-dev-salt") }}', '|', lower(trim(cast({{ col }} as varchar)))))
{%- endmacro %}

{# Great-circle distance in km. #}
{% macro haversine_km(lat1, lon1, lat2, lon2) -%}
  (2 * 6371.0 * asin(sqrt(
      power(sin(radians({{ lat2 }} - {{ lat1 }}) / 2), 2)
    + cos(radians({{ lat1 }})) * cos(radians({{ lat2 }})) * power(sin(radians({{ lon2 }} - {{ lon1 }}) / 2), 2))))
{%- endmacro %}

{% macro as_of() -%} date '{{ var("as_of_date") }}' {%- endmacro %}

{# Timestamp in the local time of a country, from the UTC event time and a fixed offset (no DST in MX/CO/AR since 2022/never/2009). #}
{% macro to_local(ts, offset_hours) -%}
  ({{ ts }} + to_hours(cast({{ offset_hours }} as integer)))
{%- endmacro %}
