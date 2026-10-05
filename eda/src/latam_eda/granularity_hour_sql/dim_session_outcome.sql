-- Junk dimension of a digital session's outcome flags (error, purchase, form submitted): eight rows instead of three
-- low-cardinality columns repeated on 1.8 million sessions.
-- grain: has_error, has_purchase, has_form
select e.v as has_error, p.v as has_purchase, f.v as has_form,
       concat_ws('/', case when e.v then 'error' end, case when p.v then 'purchase' end,
                 case when f.v then 'form' end) as outcome_label
from (values (false), (true)) e(v) cross join (values (false), (true)) p(v) cross join (values (false), (true)) f(v)
