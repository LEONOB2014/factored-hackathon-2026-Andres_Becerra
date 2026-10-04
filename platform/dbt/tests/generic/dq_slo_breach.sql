{# Fails (returns rows) for every rule whose violation rate exceeds its SLO.
   `severities` selects which rules this instance guards, so A-rules can error while B/C-rules warn.
   In the dev target, rules with enforce_in_dev = false are reported by the warn instance only. #}
{% test dq_slo_breach(model, severities, enforced_only=true) %}
select rule_id, severity, rate_pct, max_rate_pct
from {{ model }}
where slo_breached
  and severity in ({% for s in severities %}'{{ s }}'{% if not loop.last %}, {% endif %}{% endfor %})
  {% if enforced_only and target.name != 'prod' %} and enforce_in_dev {% endif %}
{% endtest %}
