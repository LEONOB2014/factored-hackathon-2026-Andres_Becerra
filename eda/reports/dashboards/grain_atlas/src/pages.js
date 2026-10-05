/* ================================================================ grains, stages, glyphs */
const GRAINS=[
 {id:"event",name:"Event",short:"one row per source record",unit:"a transaction, a click, a contact, a send, a complaint: the rows exactly as the bank's systems deliver them",
  vol:"23.5 M main records in 13 tables (44.3 M with the backup), 3 years of daily files",clock:"timestamps as delivered; batches by process_date",
  nb:"eda/notebooks 01–11 · medallion 01 · model_risk 01–02 · pipeline 01–12",key:"AUC 0.504: the honest fraud model has no skill"},
 {id:"country",name:"Country",short:"the platform rebuilt per market",unit:"the whole platform cut at bronze by the customer's country and rebuilt for Mexico, Colombia and Argentina, then again with the backup as the source",
  vol:"74.9 k · 45.3 k · 29.8 k customers; 112 notebooks from one template",clock:"delivery day (timestamp −6 h) in every market",
  nb:"country_{mx,co,ar,all} 01–14 · country_compare 01 · backup_{all,mx,co,ar} 01–14 · dataset_compare 01",key:"1,097 of 1,097 days held by the bank-wide contract"},
 {id:"daily",name:"Daily",short:"day · month · campaign cell",unit:"aggregates a bank decides on: customer × month, market × day, branch × day, agent × day, product × month, the complaint case and the campaign cell",
  vol:"17 aggregate models, 43 of 43 checks; 1,248 campaign cells",clock:"delivery day: −6 h (transactions, digital, sends), −8 h (contacts, complaints)",
  nb:"granularity 01–09 · granularity_time 01–05",key:"10 of 60 targets survive false-discovery control"},
 {id:"hourly",name:"Hourly",short:"each process on its own clock",unit:"market × channel × hour, branch × hour, agent × hour, queue × hour, the session, the case clock and the send response",
  vol:"13 hour-star models, 44 of 44 checks; 11 models gated",clock:"hour of the delivery clock of each process (ADR-014)",
  nb:"granularity_hour 01–09",key:"0 green · 2 amber · 9 red readiness gates"}];
const STAGES=[["story","Story","how the analysis unfolded"],["data","Data","what one row is"],["findings","Findings","what the grain revealed"],
 ["pipeline","Pipeline","what the platform must do"],["walk","Walkthrough","notebook by notebook"],["models","Models","what can be learned"],
 ["kpis","KPIs","what to measure"],["decide","Decide","the calls to make"]];
const GLOBALS=[["board","Decision board","every open call, all grains"],["notebooks","Notebook index","177 notebooks, where each one lands"],["glossary","Glossary","every term in plain words"]];
function glyph(g,w=28,h=16){
  let s='<svg class="glyph" width="'+w+'" height="'+h+'" viewBox="0 0 28 16" aria-hidden="true">';
  if(g==="event"){[[2,5],[5,11],[7,3],[10,8],[12,13],[14,6],[17,10],[19,2],[21,12],[23,7],[26,4]].forEach(p=>{s+='<circle cx="'+p[0]+'" cy="'+p[1]+'" r="1.5"/>';});}
  else if(g==="country"){[0,1,2].forEach(i=>{s+='<rect x="'+(1+i*9.3)+'" y="2" width="7.6" height="12" rx="1.5"/>';});}
  else if(g==="daily"){[1,1,1,1,1,.6,.6].forEach((v,i)=>{const hh=12*v; s+='<rect x="'+(1+i*3.9)+'" y="'+(14-hh)+'" width="2.9" height="'+hh+'" rx=".6"/>';});}
  else if(g==="hourly"){for(let i=0;i<24;i++) s+='<rect x="'+(1+i*1.08)+'" y="3" width=".62" height="10" rx=".2"/>';}
  else {s+='<rect x="1" y="2" width="26" height="12" rx="3" fill="none" stroke="currentColor"/>';}
  return s+'</svg>';
}
const RT=(g,s)=>g+"-"+s;

/* ================================================================ cross-grain model verdicts */
function grainVerdicts(){
  const lc={ok:0,warn:0,crit:0}; LEARN.forEach(r=>lc[r[2]]++);
  const dc={ok:0,warn:0,crit:0}; GRAN_DATA.signal.forEach(r=>{const v=r[6]||""; const k=/^(learnable|forecastable|campaigns differ)/.test(v)?"ok":/^(weak|moderate|marginal|material|leads|rates differ|fatigue|mix shifting)/.test(v)?"warn":"crit"; dc[k]++;});
  const cl=COUNTRY_DATA.mx.learn; const cc={ok:0,warn:0,crit:0,mut:0}; cl.forEach(r=>{if(/leak/.test(r[0]))cc.mut++; else if(/^learnable/.test(r[7]))cc.ok++; else if(/^(weak|moderate)/.test(r[7]))cc.warn++; else cc.crit++;});
  const hc={ok:0,warn:0,crit:0}; X.h_ready.forEach(r=>{hc[r[11]==="green"?"ok":r[11]==="amber"?"warn":"crit"]++;});
  return {event:{c:lc,lab:["learnable","partial or weak","not learnable"],unit:"model families"},
          country:{c:cc,lab:["learnable","weak","no evidence","leak control"],unit:"targets × 3 countries"},
          daily:{c:dc,lab:["learnable or forecastable","weak","no evidence"],unit:"targets and tests"},
          hourly:{c:hc,lab:["green","amber","red"],unit:"gated models"}};
}
function mixBar(v,big){
  const tot=Object.values(v.c).reduce((a,b)=>a+b,0)||1, cols={ok:"var(--ok)",warn:"var(--warn)",crit:"var(--crit)",mut:"var(--bar2)"};
  return '<div class="'+(big?"vb":"vbarmini")+'">'+Object.keys(v.c).filter(k=>v.c[k]>0).map(k=>'<i style="width:'+(100*v.c[k]/tot)+'%;background:'+cols[k]+'">'+(big?v.c[k]:"")+'</i>').join("")+'</div>';
}

/* ================================================================ decisions: grain tags and new decisions */
DECISIONS.push(
 {id:"hour-integrity-controls",title:"The three controls only the hour can see",due:"P1, after ADR-014",
  ev:"At the hour, 59 % of teller transactions fall in hours their branch is closed (exactly what schedule-blind activity gives), agents' declared shifts are unrelated to the hours they take contacts (33.4 % of Morning agents' contacts fall in the morning; chance is 33.3 %), and the complaint SLA flag does not follow the regulatory business-day clock (Cohen's κ ≈ 0 in every country). No coarser grain can see any of them.",
  opts:[["report","Add them as severity-B integrity rules with measured baselines, reported, not blocking","They track the defect on every run and turn into alerts the day real feeds should satisfy them.",true],
        ["block","Make them blocking now","Gold would stop on a property of the synthetic generator.",false],
        ["notebook","Leave them as notebook findings","Nobody sees them change when a real source arrives.",false]]},
 {id:"hourly-monitor-limits",title:"Control limits for the hourly volume monitors",due:"with the streaming twins",
  ev:"Given the day's total, hours split it uniformly (dispersion index 0.98–1.02), but the day's level itself varies about 11 % beyond Poisson. In the series II test, Poisson limits flagged about 5× the expected 0.1 % of hours; negative-binomial limits keep the alarm rate at target.",
  opts:[["nb","Negative-binomial limits with the day's level, Poisson only for small series","Alarm rate at target; operators keep trusting the monitor.",true],
        ["poisson","Poisson limits everywhere","Several times too many alarms on busy channels.",false],
        ["none","No hourly monitor; daily only","Intraday outages surface a day late.",false]]});
const DGRAIN={"fraud-model-approval":["event"],"live-corrections":["event"],"slo-breach-rules":["event"],"fraud-strategy":["event"],"first-bundle":["event"],
 "alert-budget":["event"],"backup-role":["event","country"],"dispute-key":["event"],"campaign-consent":["event","daily"],"pipeline-fix-scope":["event"],
 "scd2-first-version":["event"],"token-nulls":["event"],"drift-empty-share":["event"],"country-config":["country"],"completeness-control":["country"],
 "aggregate-promotion":["daily"],"campaign-channels":["daily"],"campaign-budget-policy":["daily"],"hour-models":["hourly"],"first-model":["country","daily"],
 "hour-integrity-controls":["hourly"],"hourly-monitor-limits":["hourly","daily"]};

/* ================================================================ glossary additions */
GLOSS.push(
 ["Accumulating snapshot","A fact table with one row per process instance (a complaint case, a send) updated as milestones happen."],
 ["ADR-014 (declared clocks)","The architecture decision that every source timestamp carries a declared clock and delivery window: −6 h for transactions, digital events and sends, −8 h for contacts and complaints."],
 ["Benjamini–Hochberg (FDR)","A procedure that controls the expected share of false discoveries among the tests called significant; used whenever dozens of tests run at once."],
 ["Bridge table","A table that resolves a many-to-many link between a dimension and a fact; here a declared shift to its hours."],
 ["Cohen's κ","Agreement between two classifications beyond chance: 1 is perfect, 0 is what chance gives. The SLA flag against the regulatory clock scores about 0."],
 ["Coverage (factless) dimension","A table that records what could have happened (a branch open at an hour) so an empty fact cell can be read as 'closed' rather than 'no activity'."],
 ["Daypart","A block of hours (night, morning, afternoon, evening) used when an hour is too sparse per customer."],
 ["Delivery day (process_date)","The business day a record belongs to: its timestamp shifted by the process's declared offset. The clock every day and hour grain must use."],
 ["Dense fact","An aggregate that keeps a row of zeros for every quiet unit-period, so windows and inactivity labels work."],
 ["Diebold–Mariano test","Tests whether two forecasts have the same expected loss, accounting for autocorrelated errors."],
 ["Dispersion index","Variance over mean of counts; 1 for Poisson or binomial noise. Above 1 means the level itself varies."],
 ["Ecological fallacy","Reading a correlation between aggregates as a relation between the units inside them."],
 ["Erlang C","The queueing formula that turns arrivals per interval and handle time into the agents needed for a service level."],
 ["Exposure law","Dormancy probability c·rᵏ for a customer with k products: the arithmetic of independent product use, the benchmark any retention model must beat."],
 ["Granger causality","A test of whether past values of one series improve the forecast of another; a lead, not a cause."],
 ["Kaplan–Meier","A survival curve that uses open (censored) cases correctly instead of averaging only the closed ones."],
 ["Log-rank test","Compares survival curves between groups."],
 ["Markov chain (monthly states)","A model of moving between states (dormant, light, active) with fixed transition probabilities; its stationary distribution is where the portfolio settles."],
 ["MASE","Mean absolute scaled error: the forecast's error divided by a naive forecast's in-sample error; below 1 beats the naive forecast."],
 ["MDE (minimum detectable effect)","The smallest gain an evaluation can detect: here 2.8 bootstrap standard errors (5 % test, 80 % power)."],
 ["Negative binomial","A count distribution whose variance exceeds its mean; the right model for hourly counts whose daily level varies."],
 ["Newsvendor","Order the quantile Cu / (Cu + Co) of demand when unmet demand costs Cu and leftover stock costs Co."],
 ["Occupancy","Handle time divided by logged-in time in an interval; needs agent state logs."],
 ["Periodic snapshot","A fact table with one row per unit per period (customer × month, market × day)."],
 ["Readiness gate","The rule every model meets: green when the 95 % interval of its out-of-time gain excludes 0 and the gain is material, amber when significant but immaterial, red otherwise, with a root cause."],
 ["Retransformation bias","A model fitted on logs predicts medians; summed over many skewed series the medians fall short of the total."],
 ["RMST","Restricted mean survival time: the average time to an event within a horizon, from the survival curve."],
 ["Role-playing dimension","One dimension joined several times in different roles: the hour of creation, of assignment, of first response."],
 ["Spearman–Brown reliability","The split-half correlation of a KPI scaled to its full length; near 0 means the KPI ranks noise."],
 ["Symmetric window test","For each trigger, count the follow-up events in the W hours after and before; with no link both sides are equally likely."],
 ["Winner's curse","Ranking cells by their raw past rate selects the lucky ones; shrinkage corrects it."]);
GLOSS.sort((a,b)=>a[0].localeCompare(b[0]));

/* ================================================================ notebooks */
const NOTEBOOKS=[
 {series:"eda/notebooks (root)",route:"event-anomaly",grain:"event",what:"The original EDA and the backup investigation: two folders compared, then 14 anomaly detectors on planted anomalies.",
  items:["01 · Business & data understanding","02 · What is in one folder and not in the other?","03 · Is the mismatch a time shift?","04 · Alignment & record linkage","05 · Comparison of comparable rows","06 · Are the two folders the same process?","07 · Anomaly detection: classical methods","08 · Anomaly detection: machine-learning detectors","09 · Anomaly detection: deep learning and supervised references","10 · Method comparison and consensus","11 · Evaluation, deployment and report"]},
 {series:"medallion",route:"event-eda",grain:"event",what:"The complete profile of every raw table.",items:["01 · Raw tables: complete profile"]},
 {series:"model_risk",route:"event-forensics",grain:"event",what:"Raw-schema forensics over 12,504 files and the four-eyes correction workbench.",items:["01 · Raw schema forensics","02 · Correction workbench"]},
 {series:"pipeline",route:"event-replay",grain:"event",what:"The dbt_lakehouse DAG replayed model by model in a scratch DuckDB, one notebook per stage.",
  items:["01 · Orchestration and lineage","02 · Lossless bronze → typed silver","03 · The quality gate: schema drift and the circuit breaker","04 · Staging: names, vocabularies, hashes and the restricted zone","05 · Conformed silver: conversion, imputation, repairs and flags","06 · Snapshots and the gold core: history, keys and the star schema","07 · Service marts: customer 360, inquiries, cards, disputes, CX","08 · Risk and growth marts: credit, collections, AML, campaigns","09 · Features: point in time, out of time, no leakage","10 · Graph and knowledge exports","11 · Privacy inputs and serving tables","12 · Audit and the three gates"]},
 {series:"country_{mx, co, ar, all} (from country_template)",route:"country-deep",grain:"country",what:"The whole platform rebuilt on each country's data alone, every decision re-taken on that country's reality; 56 notebooks generated from one template.",
  items:["01 · Scope and lake","02 · Bronze to typed silver","03 · The contract, the circuit breaker and schema evolution","04 · Staging, local time and the country calendar","05 · Currency, conversion, imputation and the monthly grid","06 · Snapshots and the gold core","07 · Service marts","08 · Risk and growth marts","09 · Point-in-time features plus the country calendar","10 · Graph and knowledge exports","11 · Privacy inputs and serving tables","12 · Integrity rules, country SLOs and the gates","13 · Anomalies and change points","14 · Which targets are learnable? Candidate models, out of time"]},
 {series:"country_compare",route:"country-contract",grain:"country",what:"Mexico, Colombia and Argentina side by side.",items:["01 · Mexico, Colombia and Argentina side by side"]},
 {series:"backup_{all, mx, co, ar}",route:"country-backupmain",grain:"country",what:"The quarantined backup folder run through the same template as if it were main: 56 more notebooks.",items:["01–14 · the country template, on the backup"]},
 {series:"dataset_compare",route:"country-survive",grain:"country",what:"Learnability, calendar and anomalies on both datasets.",items:["01 · Main against the backup run as main"]},
 {series:"granularity",route:"daily-series1",grain:"daily",what:"Series I: the star re-grained to the units a bank decides on.",
  items:["01 · Grain design and the aggregate star","02 · Customer × month: engagement, retention and cost to serve","03 · The customer over a lifetime: value, and when attrition starts","04 · Market × day and channel × day: capacity, liquidity and operational monitoring","05 · Branch × day: cash logistics","06 · The contact centre: agent × day, and the complaint case","07 · Product × month: the portfolio, its vintages and early credit signs","08 · Category × month and campaign × day: spend mix, campaign economics and contact fatigue","09 · Synthesis: which grain earns a model, an agent or a KPI"]},
 {series:"granularity_time",route:"daily-series2",grain:"daily",what:"Series II: the clock behind every day, and the campaign decision cell.",
  items:["01 · The clock: in which time were the data's days drawn?","02 · The hour grain: is the hour worth a fact table?","03 · Within the hour: sequences and bursts","04 · The campaign decision cell","05 · Allocation and synthesis"]},
 {series:"granularity_hour",route:"hourly-notebooks",grain:"hourly",what:"Series III: every fact table at the hour of its own clock, every model executed and gated.",
  items:["01 · Grain design and the hour star","02 · The customer at the hour","03 · Market and channel at the hour","04 · The branch hour","05 · The agent hour and the queue","06 · The case clock","07 · The session and the send response","08 · Data readiness and the collection audit","09 · Synthesis: the bank at the hour"]}];

/* ================================================================ page building blocks */
const M=(mod,o={})=>Object.assign({mod},o);
const S=(title,lede,body)=>({html:'<section class="blk">'+(title?'<h3>'+title+'</h3>':'')+(lede?'<p class="clede">'+lede+'</p>':'')+body+'</section>'});
const P=(kind,label,body,open)=>'<details class="panel '+kind+'"'+(open?" open":"")+'><summary><span class="k">'+label[0]+'</span>'+label[1]+'</summary><div class="body">'+body+'</div></details>';
const FIG=(id,cap,extra)=>'<figure><div class="chart" id="'+id+'"></div>'+(cap||extra?'<figcaption'+(extra||"")+'>'+(cap||"")+'</figcaption>':'')+'</figure>';
const TBL=(id,heads)=>'<div class="tbl"><table id="'+id+'"><thead><tr>'+heads.map(h=>'<th'+(h.startsWith("#")?' class="n"':'')+'>'+h.replace(/^#/,"")+'</th>').join("")+'</tr></thead><tbody></tbody></table></div>';
const NBL=(arr)=>'<div class="nblist">'+arr.map(n=>'<div class="nb"><div class="no">'+n[0]+'</div><div><b>'+n[1]+'</b><p>'+n[2]+'</p>'+(n[3]?'<p class="res">'+n[3]+'</p>':'')+'</div></div>').join("")+'</div>';
const DECL=(g)=>'<div class="decsum" data-decsum="'+g+'"></div><div class="declist" data-declist="'+g+'"></div>';
