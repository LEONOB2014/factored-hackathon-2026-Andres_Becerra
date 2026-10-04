{% test backup_is_faithful(model) %}
select table_name, only_main, only_backup, shared_changed
from {{ model }}
where only_main > 0 or only_backup > 0 or shared_changed > 0
{% endtest %}
