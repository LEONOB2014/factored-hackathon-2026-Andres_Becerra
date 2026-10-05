/* ================================================================ new renderers */
const NR={};
const KP=(arr)=>arr.map(k=>'<div class="kpi '+(k[0]||"")+'"'+(k[3]?' id="'+k[3]+'"':'')+'><b>'+k[1]+'</b><span>'+esc(k[2])+'</span></div>').join("");
const CN={MX:"Mexico",CO:"Colombia",AR:"Argentina",mx:"Mexico",co:"Colombia",ar:"Argentina",Mexico:"MX",Colombia:"CO",Argentina:"AR"};
const WD=["Mon","Tue","Wed","Thu","Fri","Sat","Sun"];
const pct=(v,d=1)=>fmt(100*v,d)+" %";
const pfmt=p=>p==null?"–":(p<0.001?"<0.001":p.toFixed(3));
const vpill=v=>'<span class="pill '+(v==="green"?"p-ok":v==="amber"?"p-warn":"p-crit")+'">'+v+'</span>';

/* time series with hover crosshair */
function tsChart(el,series,o={}){
  const W=900,H=o.h||300,L=56,R=16,T=14,B=32, n=Math.max(...series.map(s=>s.v.length)), d0=Date.parse(series[0].start);
  const raw=o.max||Math.max(...series.map(s=>Math.max(...s.v.filter(v=>v!=null))))*1.04, p10=Math.pow(10,Math.floor(Math.log10(raw))), mx=[1,1.2,1.5,2,2.5,3,4,5,6,8,10].map(f=>f*p10).find(v=>v>=raw);
  const x=i=>L+i/(n-1)*(W-L-R), y=v=>T+(1-v/mx)*(H-T-B);
  let s='<svg viewBox="0 0 '+W+' '+H+'" role="img" aria-label="'+esc(o.aria||"daily series")+'">';
  for(let t=0;t<=4;t++){const v=mx*t/4; s+='<line class="gl" x1="'+L+'" x2="'+(W-R)+'" y1="'+y(v)+'" y2="'+y(v)+'"/><text class="mut" x="'+(L-6)+'" y="'+(y(v)+4)+'" text-anchor="end">'+fmt(v,0)+'</text>';}
  for(let i=0;i<n;i++){const dt=new Date(d0+i*864e5); if(dt.getUTCDate()===1&&dt.getUTCMonth()%6===0){s+='<line class="gl" x1="'+x(i)+'" x2="'+x(i)+'" y1="'+T+'" y2="'+(H-B)+'"/><text class="mut" x="'+x(i)+'" y="'+(H-12)+'" text-anchor="middle">'+dt.toISOString().slice(0,7)+'</text>';}}
  series.forEach(se=>{let d="",pen=false; se.v.forEach((v,i)=>{if(v==null){pen=false;return;} d+=(pen?"L":"M")+x(i).toFixed(1)+","+y(v).toFixed(1); pen=true;});
    s+='<path d="'+d+'" fill="none" stroke="'+se.color+'" stroke-width="'+(o.thin?1:1.6)+'" stroke-linejoin="round"/>';});
  s+='<line id="'+el.id+'X" x1="0" x2="0" y1="'+T+'" y2="'+(H-B)+'" stroke="var(--ink)" stroke-width="1" opacity="0"/><rect x="'+L+'" y="'+T+'" width="'+(W-L-R)+'" height="'+(H-T-B)+'" fill="transparent" class="hov"/>';
  el.innerHTML=s+'</svg><div class="legend">'+series.map(se=>'<span><i style="background:'+se.color+'"></i>'+esc(se.name)+'</span>').join("")+'</div>';
  const svg=$("svg",el), ov=$(".hov",el), ln=$("#"+el.id+"X",el);
  ov.addEventListener("mousemove",ev=>{const r=svg.getBoundingClientRect(), px=(ev.clientX-r.left)/r.width*W, i=Math.max(0,Math.min(n-1,Math.round((px-L)/(W-L-R)*(n-1))));
    ln.setAttribute("x1",x(i)); ln.setAttribute("x2",x(i)); ln.setAttribute("opacity",".35");
    const dt=new Date(d0+i*864e5), wd=WD[(dt.getUTCDay()+6)%7];
    tip.innerHTML='<b>'+dt.toISOString().slice(0,10)+'</b> '+wd+'<br>'+series.map(se=>esc(se.name)+': <b>'+(se.v[i]==null?"–":fmt(se.v[i],0))+'</b>').join("<br>"); tip.hidden=false;});
  ov.addEventListener("mouseleave",()=>{ln.setAttribute("opacity","0"); tip.hidden=true;});
}
const ma7=v=>v.map((_,i)=>{if(i<6) return null; let s=0,c=0; for(let j=i-6;j<=i;j++){if(v[j]!=null){s+=v[j];c++;}} return c?s/c:null;});
function seg(id,cb){const box=$("#"+id); if(!box) return; box.addEventListener("click",e=>{const b=e.target.closest("[data-v]"); if(!b) return; $$("button",box).forEach(x=>x.setAttribute("aria-pressed",String(x===b))); cb(b.dataset.v);});}
const COLS=["var(--bar)","var(--bar3)","var(--bar2)","var(--ok)","var(--crit)"];

/* ---------------- mission */
function paintMatrix(){
  const box=$("#gmGrid"); if(!box) return;
  let h='<div class="hd"></div>'+GROUPS.map(g=>'<div class="hd">'+g[1]+'</div>').join("");
  GRAINS.forEach(G=>{h+='<div class="rh">'+glyph(G.id,30,18)+'<div><b>'+G.name+'</b><small>'+G.short+'</small></div></div>'+GROUPS.map(gr=>{
    const vs=VIEWS[G.id].filter(r=>PAGES[r].group===gr[0]);
    return '<div class="cell"><span class="sl">'+gr[1]+'</span>'+vs.map(r=>'<button type="button" class="ml" data-route="'+r+'"><span class="dot '+(PAGES[r].s||"")+'"></span>'+esc(PAGES[r].title)+'</button>').join("")+'</div>';}).join("");});
  box.innerHTML=h;
}
NR.mission=()=>{
  const nGreen=X.h_ready.filter(r=>r[11]==="green").length;
  $("#msKpis").innerHTML=KP([["","23.5 M","source records, 13 tables, 3 years"],["",VIEWS.event.length+VIEWS.country.length+VIEWS.daily.length+VIEWS.hourly.length+"","views across four grains, each a deep link"],["ok","1","behavioural target learnable at any grain: dormancy (AUC 0.72–0.73)"],
    ["warn","9 / 60","daily-grain targets significant after FDR control and material"],["crit",nGreen+" / "+X.h_ready.length,"hour-grain models with a green gate"],["","…","decisions recorded","msDec"]]);
  paintMatrix();
  $("#msVerdicts").innerHTML=GRAINS.map(g=>{const v=grainCounts[g.id], tot=Object.values(v.c).reduce((a,b)=>a+b,0);
    return '<button class="vrow" type="button" data-route="'+g.id+'-models"><b>'+g.name+'</b>'+mixBar(v,true)+'<span class="cnt">'+tot+' '+esc(v.unit)+'</span></button>';}).join("")+
    '<div class="vlegend"><span><i style="background:var(--ok)"></i>learnable, forecastable or green</span><span><i style="background:var(--warn)"></i>partial, weak or amber</span><span><i style="background:var(--crit)"></i>not learnable, no evidence or red</span><span><i style="background:var(--bar2)"></i>leak control</span></div>';
  const TL=[["event","The bank in the data","13 tables, 0.81 transactions a month","event-bank"],["event","Can we trust it?","a trust profile per table; joins valid and wrong","event-eda"],["event","Can we learn fraud?","no: the label is a function of a score","event-fraud"],
    ["event","Is the backup a copy?","no: a different dataset sharing identifiers","event-backup"],["event","What can we detect?","rank ensembles, AP 0.773 on planted anomalies","event-anomaly"],["event","Did the source change shape?","no; detectors proven on 10 planted changes","event-forensics"],
    ["event","Keep it, type it, correct it, rebuild it","lossless, contracts, four eyes, 108/108","event-bronze"],["event","Does the pipeline do what we think?","replayed: 6 defects passed 107 tests","event-replay"],
    ["country","One bank or three?","three configurations, one behaviour","country-contract"],["country","If the backup were the source","every testable conclusion survives; no control sees the gap","country-backupmain"],
    ["daily","Does a coarser grain reveal value?","forecasts and an exposure law, no behaviour","daily-exposure"],["daily","Which clock does a day run on?","the delivery day: −6 h and −8 h","daily-clock"],["daily","Where does marketing money go?","the campaign cell; a tracking gap, not a failure","daily-cell"],
    ["hourly","The bank at the hour","flat hours; three defects only the hour sees","hourly-teller"],["hourly","From red gates to a data audit","0 green, 2 amber, 9 red, each with an owner","hourly-models"]];
  $("#msTimeline").innerHTML=TL.map(t=>'<li><span class="gchip">'+t[0]+'</span><span class="pt"></span><button type="button" data-route="'+t[3]+'"><b>'+esc(t[1])+'</b><span>'+esc(t[2])+'</span></button></li>').join("");
  paintSummary();
};

/* ---------------- event */
NR["event-models"]=()=>{
  const v=grainCounts.event;
  $("#evVerdict").innerHTML='<div class="vrow" style="cursor:default"><b>Event</b>'+mixBar(v,true)+'<span class="cnt">'+LEARN.length+' families</span></div><div class="vlegend">'+v.lab.map((l,i)=>'<span><i style="background:var(--'+["ok","warn","crit"][i]+')"></i>'+l+'</span>').join("")+'</div>';
  const C=COUNTRY_DATA, f=cc=>C[cc].learn.find(r=>r[0]==="fraud (honest)")[1];
  hbar($("#evAucLadder"),[["features + fraud_score (the leak)",0.8236],["fraud_score alone",0.8249],["behavioural features only (EDA)",0.5131],["point-in-time features, out of time (warehouse)",0.5044],["honest model, Mexico",f("mx")],["honest model, Colombia",f("co")],["honest model, Argentina",f("ar")]].map(r=>({l:r[0],v:r[1],c:r[1]>0.6?"var(--crit)":"var(--bar)"})),{min:0.4,max:0.9,ticks:5,labelW:330,width:860,fmt:v=>fmt(v,3),tick:v=>fmt(v,1),refs:[{v:0.5,l:"chance"}]});
};
NR["event-kpis"]=()=>{
  let sev="", ord="rate";
  const draw=()=>{
    const rows=RULES.filter(r=>!sev||r[1]===sev).slice().sort((a,b)=>ord==="rate"?b[5]-a[5]:a[0].localeCompare(b[0]));
    const W=900, rh=24, L=330, R=90, T=10, H=T+rows.length*rh+28, x=v=>L+v/100*(W-L-R);
    let s='<svg viewBox="0 0 '+W+' '+H+'" role="img" aria-label="rule rates against SLO">';
    [0,25,50,75,100].forEach(t=>{s+='<line class="gl" x1="'+x(t)+'" x2="'+x(t)+'" y1="'+T+'" y2="'+(H-22)+'"/><text class="mut" x="'+x(t)+'" y="'+(H-6)+'" text-anchor="middle">'+t+' %</text>';});
    rows.forEach((r,i)=>{const y=T+i*rh, br=r[8]===1, col=br?"var(--crit)":r[1]==="A"?"var(--bar)":r[1]==="B"?"var(--bar3)":"var(--bar2)";
      const tipTxt='<b>'+r[0]+'</b> '+esc(r[3])+'<br>rate <b>'+fmt(r[5],2)+' %</b> · SLO max <b>'+fmt(r[7],2)+' %</b><br>'+fmt(r[4])+' violations';
      s+='<g data-tip="'+esc(tipTxt)+'"><text x="'+(L-8)+'" y="'+(y+16)+'" text-anchor="end"><tspan font-family="IBM Plex Mono" font-size="11">'+r[0]+'</tspan> '+esc(r[2].replace(/_/g," "))+'</text>';
      s+='<rect x="'+x(0)+'" y="'+(y+5)+'" width="'+(x(100)-x(0))+'" height="13" rx="2" fill="var(--grid)"/><rect x="'+x(0)+'" y="'+(y+5)+'" width="'+Math.max(1,x(r[5])-x(0))+'" height="13" rx="2" fill="'+col+'"/>';
      s+='<line x1="'+x(Math.min(100,r[7]))+'" x2="'+x(Math.min(100,r[7]))+'" y1="'+(y+2)+'" y2="'+(y+21)+'" stroke="var(--ink)" stroke-width="2"/>';
      s+='<text class="val" x="'+(W-R+8)+'" y="'+(y+16)+'"'+(br?' style="fill:var(--crit)"':'')+'>'+fmt(r[5],2)+' %</text></g>';});
    $("#ekGauge").innerHTML=s+'</svg><div class="legend"><span><i style="background:var(--bar)"></i>severity A</span><span><i style="background:var(--bar3)"></i>B</span><span><i style="background:var(--bar2)"></i>C</span><span><i style="background:var(--crit)"></i>breaches a 0 % SLO</span><span><i style="background:var(--ink);width:2px"></i>SLO maximum</span></div>';
  };
  seg("ekSev",v=>{sev=v; draw();}); seg("ekOrd",v=>{ord=v; draw();}); draw();
  const p=0.000975, ppv=p*0.8/(p*0.8+(1-p)*0.01);
  const REG=[["Lossless coverage","records re-serialised hash-equal / records","100 %","100 %","data platform","ok"],["Partitions held","partitions held by the breaker / partitions","0","0 unless a producer changes","data platform","ok"],
   ["Rebuild identity","relations identical across two builds / relations","108 / 108","100 %","data platform","ok"],["Sends without current consent (R21)","sends to customers whose flag says no / sends","50.06 %","0 %","compliance","crit"],
   ["Complaints naming another customer's product (R25)","/ complaints with a product","66.43 %","0 %","complaints","crit"],["Digital events on another customer's product (R26)","/ events with a product","7.00 %","0 %","digital","crit"],
   ["Disputes linkable to a transaction","medium or better confidence / disputes","34 of 26,351","every new dispute (capture at intake)","service","crit"],["Active cards past expiry (R22)","/ products","56,664 (14.17 %)","0 after reissue","cards","warn"],
   ["Dispute SLA breach","breached / disputes","19.97 %","regulatory deadline per country","complaints","warn"],["Customers with income in 3 of 6 months","pass the R04 rule / customers","3.5 %","policy owner to review","credit","warn"],
   ["Precision of a fraud alert","true fraud / alerts, at 80 % recall and 99 % specificity",""+fmt(100*ppv,1)+" %","set by analyst capacity","fraud operations","warn"],["Anomaly ensemble on planted anomalies","average precision, held-out split","0.773","CI floor: recall 1.0 on every planted type","fraud operations","ok"],
   ["Transactions per customer-month","Σ transactions / Σ customer-months","0.81","real banks: 20–60","data reality","warn"]];
  $("#ekReg tbody").innerHTML=REG.map(r=>'<tr><td><b>'+esc(r[0])+'</b></td><td>'+esc(r[1])+'</td><td class="n">'+esc(r[2])+'</td><td>'+esc(r[3])+'</td><td>'+esc(r[4])+'</td><td><span class="pill p-'+r[5]+'">'+({ok:"on target",warn:"watch",crit:"breach"}[r[5]])+'</span></td></tr>').join("");
};

/* ---------------- country */
NR["country-story"]=()=>{
  const C=COUNTRY_DATA, B=BACKUP_DATA.profile;
  $("#csCards").innerHTML=["mx","co","ar"].map(cc=>{const c=C[cc].contract, p=B[cc].main, d=C[cc].learn.find(r=>r[0].startsWith("dormant")), r25=C[cc].rules.find(r=>r[0]==="R25"), r20=C[cc].rules.find(r=>r[0]==="R20");
    return '<div class="card"><h4>'+CN[cc]+'</h4><div class="meta">'+fmt(p.customers)+' customers · '+fmt(p.transactions)+' transactions</div><dl>'+
      '<dt>activity</dt><dd>'+p.tx_per_customer_month.toFixed(3)+' transactions per customer-month</dd>'+
      '<dt>currency</dt><dd>'+(p.home_currency_tx_pct===0?"all accounts in USD":fmt(p.home_currency_tx_pct,0)+" % of transactions in pesos")+'; median '+fmt(p.median_tx_usd)+' USD</dd>'+
      '<dt>contract</dt><dd>bank-wide: <b style="color:var(--crit)">'+fmt(c.partitions_held_global_contract)+'</b> days held · own: <b style="color:var(--ok)">'+fmt(c.partitions_held_country_contract)+'</b> · amounts '+(c.amount_scale_country_over_global<1?c.amount_scale_country_over_global.toFixed(2):fmt(c.amount_scale_country_over_global,0))+'× the blend</dd>'+
      '<dt>dormancy</dt><dd>AUC '+d[1].toFixed(3)+' ['+d[2].toFixed(3)+', '+d[3].toFixed(3)+']; six-month count alone '+d[6].toFixed(3)+'</dd>'+
      '<dt>R25 · R20</dt><dd>'+fmt(r25[2],1)+' % of complaints name another customer\'s product · '+fmt(r20[2],1)+' % anonymous events</dd></dl>'+
      '<p style="margin:.6rem 0 0"><button class="btn" type="button" data-route="country-deep" data-cc="'+cc+'">Deep dive →</button></p></div>';}).join("");
  $("#csCards").addEventListener("click",e=>{const b=e.target.closest("[data-cc]"); if(b){store.set("atlas.cdc",b.dataset.cc); const sw=$('#cdSwitch [data-cc="'+b.dataset.cc+'"]'); if(sw) setTimeout(()=>sw.click(),0);}});
};
NR["country-data"]=()=>{
  const B=BACKUP_DATA.profile, D=X.daily, names=["Mexico","Colombia","Argentina"];
  const tot=n=>D[n].v.reduce((a,b)=>a+(b||0),0);
  $("#cdtKpis").innerHTML=KP(names.map(n=>{const cc=CN[n].toLowerCase(); return ["",fmt(B[cc].main.customers),n+": customers ("+pct(B[cc].main.customers/150000)+"), "+fmt(tot(n))+" transactions"];}).concat([["","0.79–0.80","transactions per customer-month in every country"]]));
  let on={Mexico:true,Colombia:true,Argentina:true}, sm="ma";
  const cty=$("#dsCty"); cty.innerHTML=names.map(n=>'<button type="button" data-c="'+n+'" aria-pressed="true">'+n+'</button>').join("");
  const draw=()=>{const ser=names.filter(n=>on[n]).map((n,i)=>({name:n,start:D[n].start,v:sm==="ma"?ma7(D[n].v):D[n].v,color:COLS[names.indexOf(n)]}));
    if(!ser.length){$("#dsChart").innerHTML='<p class="small">Pick at least one country.</p>'; return;}
    tsChart($("#dsChart"),ser,{thin:sm==="raw",aria:"daily transactions per country"});
    const wk=n=>{let we=0,wd=0,a=0,b=0; const d0=Date.parse(D[n].start); D[n].v.forEach((v,i)=>{if(v==null)return; const w=(new Date(d0+i*864e5).getUTCDay()+6)%7; if(w>=5){we+=v;a++;} else {wd+=v;b++;}}); return 100*((we/a)/(wd/b)-1);};
    $("#dsCap").textContent="Weekend days run "+names.map(n=>n+" "+wk(n).toFixed(1).replace("-","−")+" %").join(", ")+" against weekdays. The level differs by population; the rhythm is identical.";};
  cty.addEventListener("click",e=>{const b=e.target.closest("[data-c]"); if(!b) return; on[b.dataset.c]=!on[b.dataset.c]; b.setAttribute("aria-pressed",String(on[b.dataset.c])); draw();});
  seg("dsSmooth",v=>{sm=v; draw();}); draw();
  const keys=[...new Set([].concat(...["mx","co","ar"].map(c=>CTX_G[c].map(r=>r[0]))))];
  $("#cdCtx tbody").innerHTML=keys.map(k=>'<tr><td><b>'+esc(k)+'</b></td>'+["mx","co","ar"].map(c=>{const r=CTX_G[c].find(x=>x[0]===k); return '<td>'+(r?esc(r[1]):"–")+'</td>';}).join("")+'</tr>').join("");
};
NR["country-pipeline"]=()=>{
  const S=[["contracts: amount scale and empty-share baselines","a blended baseline holds every day of every country; estimate on each country's first 180 days","data platform"],
   ["rule SLOs","national rates (R17, R18, R20, R25) need their own maximum; zero-tolerance policies stay shared","data governance"],
   ["AML cash lines, in local units","USD 7,500 (MX), COP 10 million (CO), a UIF threshold indexed to inflation (AR)","compliance"],
   ["complaint deadlines","CONDUSEF 30 business days, SFC 15, BCRA 10 (compliance to confirm)","compliance"],
   ["calendars","holidays, puentes, paydays and bonus months differ; the generator ignores them, real data will not","data platform, finance"],
   ["consent rules","LFPDPPP and REUS, Ley 1581, Ley 25.326 and No Llame","legal"],
   ["currency statistics","statistics per currency; incomes always converted; imputed USD amounts flagged near thresholds","data platform"],
   ["gates","one country's failed delivery must never block another's run","platform operations"],
   ["completeness calendar (new)","expected partitions per fact table and row-count floors per source: the backup run's missing control","data platform"]];
  $("#cpSeeds tbody").innerHTML=S.map(r=>'<tr><td><b>'+esc(r[0])+'</b></td><td>'+esc(r[1])+'</td><td>'+esc(r[2])+'</td></tr>').join("");
};
NR["country-kpis"]=()=>{
  const C=COUNTRY_DATA, B=BACKUP_DATA.profile, cc=["mx","co","ar"];
  const cal=(c,t)=>{const r=C[c].calendar.find(x=>x[0]===t); return r?r[1]:null;};
  const L=[["customers",c=>B[c].main.customers,0],["transactions",c=>B[c].main.transactions,0],["transactions per customer-month",c=>B[c].main.tx_per_customer_month,3],
   ["transactions in the home currency (%)",c=>B[c].main.home_currency_tx_pct,0],["anonymous digital sessions (%)",c=>B[c].main.anonymous_sessions_pct,1],["median monthly income (USD)",c=>B[c].main.median_income_usd,0],
   ["median transaction (USD)",c=>B[c].main.median_tx_usd,0],["days held, bank-wide contract",c=>C[c].contract.partitions_held_global_contract,0],["days held, own contract",c=>C[c].contract.partitions_held_country_contract,0],
   ["typical amount vs the blend (×)",c=>C[c].contract.amount_scale_country_over_global,2],["severity-B drift reports",c=>C[c].contract.b_reports_country_contract,0],["largest monthly PSI",c=>C[c].contract.max_monthly_psi,4],
   ["Saturday vs Monday (%)",c=>cal(c,"C(iso_weekday)[T.6]"),1],["calendar model R²",c=>C[c].r2,2],["abnormal days · change points",c=>C[c].anomalies.abnormal_days+" · "+C[c].anomalies.change_points,null],
   ["customer-months with an AML typology (%)",c=>C[c].anomalies.aml_rate_overall_pct,2],["forest top 0.5 % vs AML rules (×)",c=>C[c].anomalies.enrichment,1],
   ["dormancy AUC, out of time",c=>C[c].learn.find(r=>r[0].startsWith("dormant"))[1],3],["campaign conversion AUC",c=>C[c].learn.find(r=>r[0].startsWith("campaign"))[1],3],["fraud AUC (honest)",c=>C[c].learn.find(r=>r[0]==="fraud (honest)")[1],3]];
  $("#ckTbl tbody").innerHTML=L.map(([l,f,d])=>{const v=cc.map(f); let rd="";
    if(d!=null){const nums=v.map(Number), mn=Math.min(...nums), mx=Math.max(...nums), rel=mx===0?0:(mx-mn)/Math.max(Math.abs(mx),1e-9);
      rd=/held|customers|transactions$/.test(l)?"":rel>0.25?"national":rel>0.05?"close":"common";}
    return '<tr><td>'+esc(l)+'</td>'+v.map(x=>'<td class="n">'+(d==null?esc(String(x)):fmt(x,d))+'</td>').join("")+'<td>'+(rd?'<span class="pill '+(rd==="national"?"p-warn":rd==="common"?"p-ok":"p-mut")+'">'+rd+'</span>':'')+'</td></tr>';}).join("");
  const ids=C.mx.rules.map(r=>r[0]).sort(); const sel=$("#ckRule"); sel.innerHTML=ids.map(i=>'<option'+(i==="R25"?" selected":"")+'>'+i+'</option>').join("");
  const desc=Object.fromEntries(RULES.map(r=>[r[0],r[3]]));
  const draw=()=>{const id=sel.value, rows=cc.map(c=>C[c].rules.find(r=>r[0]===id)), base=rows[0][3];
    const mx=Math.max(base,...rows.map(r=>r[2]))*1.15||1;
    hbar($("#ckRuleChart"),rows.map((r,i)=>({l:CN[cc[i]],v:r[2],c:COLS[i]})),{min:0,max:mx,labelW:140,width:760,fmt:v=>fmt(v,2)+" %",tick:v=>fmt(v,1),refs:[{v:base,l:"bank "+fmt(base,2)+" %"}]});
    $("#ckRuleCap").textContent=id+": "+(desc[id]||"")+". Country SLO maximums: "+rows.map((r,i)=>CN[cc[i]]+" "+fmt(Math.min(100,r[4]),2)+" %").join(", ")+(rows.some(r=>r[4]===0&&r[2]>0)?". A maximum of 0 % is a zero-tolerance policy: shared by every country, breached in each.":".");};
  sel.addEventListener("change",draw); draw();
};

/* ---------------- daily */
NR["daily-story"]=()=>{
  const F=[["Grain design","17 aggregates, 43/43 checks","daily-star"],["Customer × month","exposure, not behaviour","daily-exposure"],["Customer lifetime","lapse at 11–12 months","daily-retention"],["Market × day","calendar beats naive","daily-models"],
   ["Branch × day","cash: newsvendor planner","daily-campaigns"],["Agent × day and case","agent KPIs are noise","daily-earlywarn"],["Product × month","no DPD history yet","daily-series1"],["Category and campaign","campaigns differ","daily-campaigns"],["Synthesis I","9 of 60 actionable","daily-signal"],
   ["The clock","−6 h and −8 h","daily-clock"],["The hour grain","a monitor, not a table","hourly-clock"],["Sequences","no event leads another","hourly-sequences"],["The campaign cell","a tracking gap","daily-cell"],["Allocation","+22 % at the same contacts","daily-allocation"]];
  $("#dyFlow").innerHTML=F.map(f=>'<button type="button" data-route="'+f[2]+'"><b>'+esc(f[0])+'</b><span>'+esc(f[1])+'</span></button>').join("");
};
NR["daily-data"]=()=>{
  const D=X.daily, names=["Mexico","Colombia","Argentina"]; let mode="tx", sm="ma";
  const draw=()=>{let ser;
    if(mode==="tx") ser=names.map((n,i)=>({name:n,start:D[n].start,v:sm==="ma"?ma7(D[n].v):D[n].v,color:COLS[i]}));
    else ser=[{name:"contacts",start:X.daily_contacts.start,v:sm==="ma"?ma7(X.daily_contacts.v):X.daily_contacts.v,color:"var(--bar)"}];
    tsChart($("#ddChart"),ser,{thin:sm==="raw",aria:"daily series"});
    $("#ddCap").textContent=mode==="tx"?"Transactions per delivery day by the customer's country, 17 June 2023 to 17 June 2026.":"Contact-centre interactions per delivery day (timestamp −8 h), whole bank.";};
  seg("ddSeries",v=>{mode=v; draw();}); seg("ddSmooth",v=>{sm=v; draw();}); draw();
  const sum=[0,0,0,0,0,0,0], cnt=[0,0,0,0,0,0,0];
  names.forEach(n=>{const d0=Date.parse(D[n].start); D[n].v.forEach((v,i)=>{if(v==null)return; const w=(new Date(d0+i*864e5).getUTCDay()+6)%7; sum[w]+=v; cnt[w]++;});});
  const avg=sum.map((s,i)=>3*s/cnt[i]), wdm=avg.slice(0,5).reduce((a,b)=>a+b,0)/5;
  hbar($("#ddWeek"),avg.map((v,i)=>({l:WD[i],v,c:i>=5?"var(--bar3)":"var(--bar)"})),{min:0,max:Math.max(...avg)*1.1,labelW:60,width:700,fmt:v=>fmt(v,0)+"  ("+(v/wdm*100-100>0?"+":"")+(v/wdm*100-100).toFixed(1)+" %)",valW:150,tick:v=>fmt(v,0),refs:[{v:wdm,l:"weekday mean"}]});
};
NR["daily-findings"]=()=>{
  const L=X.lifts;
  hbar($("#dfLifts"),L.map(r=>({l:r[0],v:r[4],c:"var(--bar)"})),{min:0.9,max:1.1,ticks:4,labelW:320,width:860,fmt:v=>fmt(v,3),tick:v=>fmt(v,2),refs:[{v:1,l:"no link"}]});
  const svg=$("#dfLifts svg"); if(svg){const W=860, lw=320, pad=10, vw=78, pw=W-lw-vw-pad*2, x=v=>lw+pad+(v-0.9)/0.2*pw; let add=""; L.forEach((r,i)=>{const y=8+i*26+13; add+='<line x1="'+x(Math.max(0.9,r[5]))+'" x2="'+x(Math.min(1.1,r[6]))+'" y1="'+y+'" y2="'+y+'" stroke="var(--ink)" stroke-width="1.5"/>';}); svg.insertAdjacentHTML("beforeend",add);}
  $("#dfLiftTbl tbody").innerHTML=L.map(r=>'<tr><td>'+esc(r[0])+'</td><td class="n">'+fmt(r[1])+'</td><td class="n">'+fmt(r[2],2)+' %</td><td class="n">'+fmt(r[3],2)+' %</td><td class="n">'+r[4].toFixed(3)+' ['+r[5].toFixed(3)+', '+r[6].toFixed(3)+']</td><td class="small">'+esc(r[8])+'</td></tr>').join("");
  $("#dfSurvC tbody").innerHTML=X.surv_cust.map(r=>'<tr><td>'+esc(r[0].replace(/_/g," "))+'</td><td>'+esc(r[1])+'</td><td class="n">'+fmt(r[2])+'</td><td class="n">'+fmt(r[3],1)+' %</td><td class="n">'+fmt(r[4],0)+'</td><td class="n">'+r[5].toFixed(3)+'</td><td class="n">'+pfmt(r[7])+'</td></tr>').join("");
  $("#dfSurvK tbody").innerHTML=X.surv_cases.map(r=>'<tr><td>'+esc(r[0])+'</td><td>'+esc(r[1])+'</td><td class="n">'+fmt(r[2])+'</td><td class="n">'+fmt(r[3],1)+' %</td><td class="n">'+fmt(100*r[6],1)+' %</td><td class="n">'+fmt(r[5],1)+' d</td></tr>').join("");
  $("#dfAgent tbody").innerHTML=X.agent_rel.map(r=>'<tr><td>'+esc(r[0])+'</td><td class="n">'+fmt(r[1])+'</td><td class="n">'+r[2].toFixed(3)+'</td><td class="n">'+r[3].toFixed(3)+'</td><td class="n">'+(r[4]==null?"–":r[4].toFixed(5))+'</td></tr>').join("");
  $("#dfGranger tbody").innerHTML=X.granger.map(r=>'<tr><td>'+r[0]+'</td><td>'+esc(r[1].replace(/_/g," "))+' → '+esc(r[2].replace(/_/g," "))+'</td><td class="n">'+r[3]+'</td><td class="n">'+r[4].toFixed(3)+'</td><td>'+(r[5]?'<span class="pill p-ok">lead</span>':'<span class="pill p-mut">none</span>')+'</td></tr>').join("");
};
NR["daily-pipeline"]=()=>{
  const R=[["transactions","−6 h","enrich_transactions derives local hour and is_weekend from the declared clock instead of the country's legal offset","delivery-day conformance ≥ 99.5 %; monthly clock-drift scan"],
   ["digital events","−6 h","fct_digital_session.date_key moves from the UTC day to the delivery day; 99.8 % of events already land on their process_date","conformance and drift scan"],
   ["campaign sends","−6 h","campaign day and cell months on the delivery day","conformance and drift scan"],
   ["contacts","−8 h","R15 tests the −8 h window; today its ~8.3 % violations are the 2 of 24 hours between −6 h and −8 h","R15 on the declared window"],
   ["complaints","−8 h","R16 likewise; the case clock counts business hours on each country's calendar","R16 on the declared window; regulatory breach recomputed from the clock"],
   ["surveys","none fixed","about 42-hour windows: keep process_date as delivered","flag, no hour grain"]];
  $("#dpClock tbody").innerHTML=R.map(r=>'<tr><td><b>'+r[0]+'</b></td><td class="mono">'+r[1]+'</td><td>'+esc(r[2])+'</td><td>'+esc(r[3])+'</td></tr>').join("");
};
NR["daily-models"]=()=>{
  const G=GRAN_DATA.signal, by={}, cls=v=>/^(learnable|forecastable|campaigns differ)/.test(v)?"ok":/^(weak|moderate|marginal|material|leads|rates differ|fatigue|mix shifting)/.test(v)?"warn":"crit";
  G.forEach(r=>{const g=r[0].replace(/ \((AR|CO|MX)\)$/,""); (by[g]=by[g]||{ok:0,warn:0,crit:0})[cls(r[6]||"")]++;});
  const ks=Object.keys(by), W=860, rh=28, L=200, R=60, T=8, H=T+ks.length*rh+26, mx=Math.max(...ks.map(k=>by[k].ok+by[k].warn+by[k].crit)), x=v=>L+v/mx*(W-L-R);
  let s='<svg viewBox="0 0 '+W+' '+H+'" role="img" aria-label="verdicts by grain">';
  for(let t=0;t<=mx;t+=5){s+='<line class="gl" x1="'+x(t)+'" x2="'+x(t)+'" y1="'+T+'" y2="'+(H-20)+'"/><text class="mut" x="'+x(t)+'" y="'+(H-5)+'" text-anchor="middle">'+t+'</text>';}
  ks.forEach((k,i)=>{const y=T+i*rh; let a=0; s+='<text x="'+(L-8)+'" y="'+(y+18)+'" text-anchor="end">'+esc(k)+'</text>';
    ["ok","warn","crit"].forEach(c=>{const v=by[k][c]; if(v){s+='<rect x="'+x(a)+'" y="'+(y+5)+'" width="'+(x(a+v)-x(a))+'" height="17" fill="var(--'+c+')" data-tip="'+esc(k+": "+v+" "+({ok:"learnable or forecastable",warn:"weak",crit:"no evidence"}[c]))+'"/>'; a+=v;}});
    s+='<text class="val" x="'+(x(a)+6)+'" y="'+(y+18)+'">'+a+'</text>';});
  $("#dmGrain").innerHTML=s+'</svg><div class="legend"><span><i style="background:var(--ok)"></i>learnable or forecastable</span><span><i style="background:var(--warn)"></i>weak</span><span><i style="background:var(--crit)"></i>no evidence</span></div>';
  let mkt="MX";
  const MOD=["seasonal naive","calendar regression","SARIMAX","boosting"];
  const draw=()=>{const rows=X.fc.filter(r=>r[0]===mkt&&MOD.includes(r[2]));
    const series=[...new Set(rows.map(r=>r[1]))]; const out=[];
    series.forEach(se=>{const rs=rows.filter(r=>r[1]===se), best=rs.filter(r=>r[2]!=="seasonal naive").reduce((a,b)=>b[3]<a[3]?b:a);
      MOD.forEach(m=>{const r=rs.find(x=>x[2]===m); if(r) out.push({l:se.replace(/_/g," ")+" · "+m,v:r[3],c:m==="seasonal naive"?"var(--bar2)":r===best&&r[4]!=null&&r[4]<0.05?"var(--ok)":"var(--bar)"});});});
    hbar($("#fcChart"),out,{min:0,max:1.7,ticks:6,labelW:300,width:860,rowH:21,fmt:v=>v.toFixed(3),tick:v=>v.toFixed(1),refs:[{v:1,l:"MASE 1"}]});
    const sig=rows.filter(r=>r[4]!=null&&r[4]<0.05&&r[3]<rows.find(x=>x[1]===r[1]&&x[2]==="seasonal naive")[3]).map(r=>r[1].replace(/_/g," ")+" ("+r[2]+", p "+r[4].toFixed(3)+")");
    $("#fcCap").textContent=CN[mkt]+": green bars beat seasonal naive with Diebold–Mariano p < 0.05: "+(sig.length?sig.join("; "):"none")+". SARIMAX on outflows overshoots (MASE about 1.5–1.6).";};
  seg("fcMkt",v=>{mkt=v; draw();}); draw();
  const C=X.cells, uniq=i=>[...new Set(C.map(r=>r[i]))].sort();
  const fill=(id,i)=>{$("#"+id).innerHTML='<option value="">all</option>'+uniq(i).map(v=>'<option>'+esc(v)+'</option>').join("");};
  fill("ceCh",0); fill("ceObj",2); fill("ceMkt",4);
  const chs=uniq(0), ccol=c=>COLS[chs.indexOf(c)%COLS.length];
  const drawC=()=>{const ch=$("#ceCh").value, ob=$("#ceObj").value, mk=$("#ceMkt").value, mn=+$("#ceMin").value||0;
    const rs=C.filter(r=>(!ch||r[0]===ch)&&(!ob||r[2]===ob)&&(!mk||r[4]===mk)&&r[5]>=mn&&r[5]>0);
    const W=860,H=360,L=60,R=20,T=14,B=40, raw=r=>r[6]/r[5], mxr=Math.min(0.03,Math.max(0.005,...rs.map(raw))*1.05), mxe=mxr;
    const x=v=>L+Math.min(v,mxr)/mxr*(W-L-R), y=v=>H-B-Math.min(v,mxe)/mxe*(H-T-B);
    let s='<svg viewBox="0 0 '+W+' '+H+'" role="img" aria-label="raw against shrunk cell rates">';
    for(let t=0;t<=4;t++){const v=mxe*t/4; s+='<line class="gl" x1="'+L+'" x2="'+(W-R)+'" y1="'+y(v)+'" y2="'+y(v)+'"/><text class="mut" x="'+(L-6)+'" y="'+(y(v)+4)+'" text-anchor="end">'+(100*v).toFixed(2)+'%</text>';
      const u=mxr*t/4; s+='<text class="mut" x="'+x(u)+'" y="'+(H-B+16)+'" text-anchor="middle">'+(100*u).toFixed(2)+'%</text>';}
    s+='<text class="mut" x="'+((W)/2)+'" y="'+(H-6)+'" text-anchor="middle">raw cell conversion per send (fit period)</text><text class="mut" transform="translate(14 '+(H/2)+') rotate(-90)" text-anchor="middle">empirical-Bayes rate</text>';
    s+='<line x1="'+x(0)+'" y1="'+y(0)+'" x2="'+x(mxr)+'" y2="'+y(mxe)+'" class="ref" style="stroke:var(--bar2)"/><text class="mut" x="'+(x(mxr)-6)+'" y="'+(y(mxe)+16)+'" text-anchor="end">no shrinkage (y = x)</text>';
    rs.forEach(r=>{const rad=Math.max(2,Math.min(9,Math.sqrt(r[5])/9)); s+='<circle cx="'+x(raw(r)).toFixed(1)+'" cy="'+y(r[7]||0).toFixed(1)+'" r="'+rad.toFixed(1)+'" fill="'+ccol(r[0])+'" fill-opacity=".55" data-tip="'+esc('<b>'+r[0]+'</b> · '+r[1]+' · '+r[2]+' · '+r[3]+' · '+r[4]+'<br>'+fmt(r[5])+' sends, '+fmt(r[6])+' conversions<br>raw '+(100*raw(r)).toFixed(3)+' % · EB '+(100*(r[7]||0)).toFixed(3)+' %')+'"/>';});
    $("#ceScatter").innerHTML=s+'</svg><div class="legend">'+chs.map(c=>'<span><i style="background:'+ccol(c)+'"></i>'+esc(c)+'</span>').join("")+'</div>';
    const tracked=rs.filter(r=>r[9]);
    $("#ceCap").textContent=fmt(rs.length)+" cells shown ("+fmt(tracked.length)+" with open tracking). Both axes on the same scale. Raw rates spread along x; the empirical-Bayes rates are pulled toward their channel's rate, so each channel forms a flat band (its spread is about a fifth of the raw spread). Voice and WhatsApp sit at 0: they record no opens. Hover a point for the cell.";
    $("#ceTbl tbody").innerHTML=rs.slice().sort((a,b)=>b[5]-a[5]).slice(0,40).map(r=>'<tr><td>'+esc(r[0])+'</td><td>'+esc(r[1])+'</td><td>'+esc(r[2])+'</td><td>'+esc(r[3])+'</td><td>'+r[4]+'</td><td class="n">'+fmt(r[5])+'</td><td class="n">'+fmt(r[6])+'</td><td class="n">'+(100*raw(r)).toFixed(3)+' %</td><td class="n">'+(100*(r[7]||0)).toFixed(3)+' %</td><td class="n">'+(r[8]==null?"–":fmt(r[8],2))+'</td></tr>').join("");};
  ["ceCh","ceObj","ceMkt","ceMin"].forEach(id=>$("#"+id).addEventListener("input",drawC)); drawC();
};

/* ---------------- hourly */
NR["hourly-story"]=()=>{
  const F=[["Grain design and the hour star","13 models, 44/44 checks","hourly-star"],["The customer at the hour","no habits: 1.05 % vs 1 % chance","hourly-rhythm"],["Market and channel","24 flat series","hourly-rhythm"],["The branch hour","59 % teller outside hours","hourly-teller"],
   ["The agent hour and the queue","shift label unrelated","hourly-shift"],["The case clock","SLA flag κ ≈ 0","hourly-case"],["Session and send","random order, uniform delays","hourly-rhythm"],["Readiness audit","0 green · 2 amber · 9 red","hourly-models"],["Synthesis","52 tests, 1 material","hourly-signal"]];
  $("#hyFlow").innerHTML=F.map(f=>'<button type="button" data-route="'+f[2]+'"><b>'+esc(f[0])+'</b><span>'+esc(f[1])+'</span></button>').join("");
};
NR["hourly-data"]=()=>{
  const DESC={dim_time_of_day:["role-playing","hour of day (24 rows)","every process joins it on its own clock, so 'morning' means the same everywhere"],
   dim_process_clock:["reference","process","ADR-014 as data: the offset each fact applies"],dim_branch_schedule:["coverage (factless)","branch × weekday × hour","open fraction: an empty branch-hour can be read as closed"],
   dim_agent_shift:["bridge","shift × hour","declared shift → its hours (Morning 6–14, Afternoon 14–22, Night 22–6, Rotating all)"],dim_session_outcome:["junk","flag combination","error, purchase and form flags of a session"],
   dim_hour:["calendar (series II)","UTC hour","the delivery day per process clock"],fct_country_hour:["periodic, dense (series II)","market × hour","the market's intraday monitor"],fct_campaign_cell:["periodic (series II)","campaign cell × month","campaign allocation"],
   fct_channel_hour:["periodic, dense","market × channel × hour","channel load, volume monitors"],fct_branch_hour:["periodic, sparse","branch × hour","opening-hours compliance; ATM cash"],
   fct_agent_hour:["periodic, sparse","agent × hour","occupancy and shift adherence"],fct_contact_queue_hour:["periodic, dense","market × contact channel × hour","Erlang C input: arrivals, handle time, waits"],
   fct_session:["accumulating","session (sub-hour)","funnel and error impact, dated by the delivery day"],fct_case_clock:["accumulating, hour milestones","complaint case","assignment, first response and resolution in hours and business hours"],
   fct_send_response:["accumulating","campaign send","send → open → click → conversion delays"],fct_customer_daypart:["periodic snapshot","customer × daypart","time-of-day profile (customer × hour is 99.9 % empty)"]};
  $("#hdStar tbody").innerHTML=X.h_checks.map(r=>{const d=DESC[r[0]]||["","",""]; return '<tr><td><code>'+esc(r[0])+'</code></td><td>'+esc(d[0])+'</td><td>'+esc(d[1])+'</td><td>'+esc(d[2])+'</td><td class="n">'+r[2]+' / '+r[1]+'</td></tr>';}).join("");
  let proc="transactions", clock="biz";
  const draw=()=>{const m=X.hour_weekday[proc+":"+clock], all=[].concat(...m), mean=all.reduce((a,b)=>a+b,0)/all.length;
    const W=900,H=280,L=46,R=10,T=10,B=40, cw=(W-L-R)/24, ch=(H-T-B)/7;
    let s='<svg viewBox="0 0 '+W+' '+H+'" class="hm" role="img" aria-label="hour by weekday">';
    m.forEach((row,d)=>{s+='<text class="mut" x="'+(L-8)+'" y="'+(T+d*ch+ch/2+4)+'" text-anchor="end">'+WD[d]+'</text>';
      row.forEach((v,h)=>{const r=v/mean, k=Math.max(0,Math.min(1,(r-0.45)/0.75));
        s+='<rect class="c" x="'+(L+h*cw)+'" y="'+(T+d*ch)+'" width="'+cw+'" height="'+ch+'" fill="color-mix(in srgb, var(--accent) '+Math.round(8+k*84)+'%, var(--heat0))" data-tip="'+esc('<b>'+WD[d]+' '+String(h).padStart(2,"0")+':00</b><br>'+fmt(v)+' events · '+(r*100).toFixed(0)+' % of the mean cell')+'"/>';});});
    for(let h=0;h<24;h+=3) s+='<text class="mut" x="'+(L+h*cw+cw/2)+'" y="'+(H-B+16)+'" text-anchor="middle">'+String(h).padStart(2,"0")+'</text>';
    s+='<text class="mut" x="'+(L+(W-L-R)/2)+'" y="'+(H-6)+'" text-anchor="middle">hour of day ('+(clock==="biz"?"delivery clock":"raw UTC")+')</text>';
    $("#hwHeat").innerHTML=s+'</svg>';
    const satEarly=m[5].slice(0,6).reduce((a,b)=>a+b,0)/6, satLate=m[5].slice(12,18).reduce((a,b)=>a+b,0)/6;
    $("#hwCap").textContent=(proc==="transactions"?"Transactions":"Contacts")+", "+(clock==="biz"?"delivery clock":"raw UTC")+": Saturday 00–05 h averages "+fmt(satEarly)+" an hour against "+fmt(satLate)+" at 12–17 h. "+(clock==="biz"?"Whole days carry the weekend dip; inside a day the hours are flat.":"On the raw clock the first "+(proc==="transactions"?"six":"eight")+" Saturday hours still belong to Friday's business day, and the first hours of Monday to Sunday's.");};
  seg("hwProc",v=>{proc=v; draw();}); seg("hwClock",v=>{clock=v; draw();}); draw();
  const P=X.hour_profile, names={transactions:"transactions",digital_events:"digital events",campaign_sends:"campaign sends",call_center_interactions:"contacts",complaints:"complaints"};
  const W=900,H=300,L=56,R=150,T=12,B=34, lo=0.9, hi=1.1, x=h=>L+h/23*(W-L-R), y=v=>T+(hi-Math.max(lo,Math.min(hi,v)))/(hi-lo)*(H-T-B);
  let s='<svg viewBox="0 0 '+W+' '+H+'" role="img" aria-label="hourly index per process">';
  [0.9,0.95,1,1.05,1.1].forEach(v=>{s+='<line class="'+(v===1?"ax":"gl")+'" x1="'+L+'" x2="'+(W-R)+'" y1="'+y(v)+'" y2="'+y(v)+'"/><text class="mut" x="'+(L-6)+'" y="'+(y(v)+4)+'" text-anchor="end">'+v.toFixed(2)+'</text>';});
  for(let h=0;h<24;h+=3) s+='<text class="mut" x="'+x(h)+'" y="'+(H-12)+'" text-anchor="middle">'+String(h).padStart(2,"0")+'</text>';
  Object.keys(names).forEach((k,i)=>{const v=P[k].biz, m=v.reduce((a,b)=>a+b,0)/v.length; s+='<polyline fill="none" stroke="'+COLS[i]+'" stroke-width="1.8" points="'+v.map((c,h)=>x(h)+","+y(c/m)).join(" ")+'"/>';
    const rng=(Math.max(...v)/m-1)*100, rn2=(1-Math.min(...v)/m)*100;
    s+='<text x="'+(W-R+10)+'" y="'+(T+16+i*20)+'" style="fill:'+COLS[i]+'">'+names[k]+' ±'+Math.max(rng,rn2).toFixed(1)+' %</text>';});
  $("#hpChart").innerHTML=s+'</svg>';
};
NR["hourly-findings"]=()=>{
  const th=X.teller_hour, of=X.branch_open_frac, W=900,H=300,L=56,R=56,T=14,B=34, mx=Math.max(...th)*1.15, bw=(W-L-R)/24;
  const y=v=>T+(1-v/mx)*(H-T-B), y2=v=>T+(1-v)*(H-T-B);
  let s='<svg viewBox="0 0 '+W+' '+H+'" role="img" aria-label="teller transactions and branches open by hour">';
  for(let t=0;t<=4;t++){const v=mx*t/4; s+='<line class="gl" x1="'+L+'" x2="'+(W-R)+'" y1="'+y(v)+'" y2="'+y(v)+'"/><text class="mut" x="'+(L-6)+'" y="'+(y(v)+4)+'" text-anchor="end">'+fmt(v/1000,1)+' k</text><text class="mut" x="'+(W-R+6)+'" y="'+(y2(t/4)+4)+'">'+(t*25)+' %</text>';}
  th.forEach((v,h)=>{s+='<rect x="'+(L+h*bw+bw*.12)+'" y="'+y(v)+'" width="'+(bw*.76)+'" height="'+(H-B-y(v))+'" rx="2" fill="'+(of[h]>0.5?"var(--bar)":"var(--bar3)")+'" data-tip="'+esc('<b>'+String(h).padStart(2,"0")+':00</b><br>'+fmt(v)+' teller transactions<br>'+(100*of[h]).toFixed(0)+' % of branches open')+'"/>';
    if(h%3===0) s+='<text class="mut" x="'+(L+h*bw+bw/2)+'" y="'+(H-12)+'" text-anchor="middle">'+String(h).padStart(2,"0")+'</text>';});
  s+='<polyline fill="none" stroke="var(--crit)" stroke-width="2.2" points="'+of.map((v,h)=>(L+h*bw+bw/2)+","+y2(v)).join(" ")+'"/>';
  const outShare=th.reduce((a,v,h)=>a+v*(1-of[h]),0)/th.reduce((a,b)=>a+b,0);
  $("#hfTeller").innerHTML=s+'</svg><div class="legend"><span><i style="background:var(--bar)"></i>hours most branches are open</span><span><i style="background:var(--bar3)"></i>hours most are closed</span><span><i style="background:var(--crit)"></i>share of branches open</span><span>weekday teller transactions outside the posted hours: '+pct(outShare)+'</span></div>';
  $("#hfTellerTbl tbody").innerHTML=X.h_branch.map(r=>'<tr><td>'+esc(r[1])+'</td><td class="n">'+(r[1].startsWith("ATM")?fmt(r[2],1):pct(r[2]))+'</td><td class="n">'+pfmt(r[3])+'</td><td>'+esc(r[6])+'</td></tr>').join("");
  const SH={Morning:[6,14],Afternoon:[14,22],Night:[22,6],Rotating:null}, sh=X.shift_hour; let cur="Morning";
  $("#hsShift").innerHTML=Object.keys(SH).map((k,i)=>'<button type="button" data-v="'+k+'" aria-pressed="'+(i===0)+'">'+k+'</button>').join("");
  const inS=(k,h)=>{const w=SH[k]; if(!w) return true; return w[0]<w[1]?(h>=w[0]&&h<w[1]):(h>=w[0]||h<w[1]);};
  const drawS=()=>{const v=sh[cur], tot=v.reduce((a,b)=>a+b,0), sharev=v.map(c=>c/tot), W=900,H=280,L=56,R=16,T=12,B=34, mx=0.06, x=h=>L+h*(W-L-R)/24, y=p=>T+(1-p/mx)*(H-T-B);
    let s='<svg viewBox="0 0 '+W+' '+H+'" role="img" aria-label="contacts by hour for a shift">';
    for(let h=0;h<24;h++) if(SH[cur]&&inS(cur,h)) s+='<rect x="'+x(h)+'" y="'+T+'" width="'+((W-L-R)/24)+'" height="'+(H-T-B)+'" fill="var(--accent-soft)"/>';
    [0,0.02,0.04,0.06].forEach(p=>{s+='<line class="gl" x1="'+L+'" x2="'+(W-R)+'" y1="'+y(p)+'" y2="'+y(p)+'"/><text class="mut" x="'+(L-6)+'" y="'+(y(p)+4)+'" text-anchor="end">'+(100*p).toFixed(0)+' %</text>';});
    s+='<line class="ref" x1="'+L+'" x2="'+(W-R)+'" y1="'+y(1/24)+'" y2="'+y(1/24)+'"/>';
    s+='<polyline fill="none" stroke="var(--bar)" stroke-width="2.2" points="'+sharev.map((p,h)=>(x(h)+(W-L-R)/48)+","+y(p)).join(" ")+'"/>';
    for(let h=0;h<24;h+=3) s+='<text class="mut" x="'+(x(h)+(W-L-R)/48)+'" y="'+(H-12)+'" text-anchor="middle">'+String(h).padStart(2,"0")+'</text>';
    $("#hfShift").innerHTML=s+'</svg>';
    const ins=sharev.reduce((a,p,h)=>a+(inS(cur,h)?p:0),0);
    $("#hfShiftCap").textContent=cur+" agents: "+fmt(tot)+" contacts. "+(SH[cur]?pct(ins)+" fall inside the declared shift, against "+pct(8/24)+" if the shift meant nothing. The line hugs 1/24 (dashed) in every hour.":"Rotating agents have no fixed hours; their contacts are as flat as everyone else's.");};
  seg("hsShift",v=>{cur=v; drawS();}); drawS();
  $("#hfShiftTbl tbody").innerHTML=X.h_shift.map(r=>'<tr><td>'+esc(r[1])+'</td><td class="n">'+(r[2]<1?pct(r[2]):r[2].toFixed(3))+'</td><td class="n">'+pfmt(r[3])+'</td><td>'+esc(r[6])+'</td></tr>').join("");
  const sl=X.sla_by_days; vbar($("#hfSla"),sl.map(r=>String(r[0])),sl.map(r=>100*r[2]/r[1]),{max:30,fmt:v=>fmt(v,0)+" %",color:"var(--bar3)",width:560,height:240});
  const mile=[["to assignment",X.case_assign_q],["to first response",X.case_first_response_q]], W2=560,H2=170,L2=130,R2=20, mxh=64, xx=v=>L2+v/mxh*(W2-L2-R2);
  let m='<svg viewBox="0 0 '+W2+' '+H2+'" role="img" aria-label="case milestones in hours">';
  [0,12,24,36,48,60].forEach(t=>{m+='<line class="gl" x1="'+xx(t)+'" x2="'+xx(t)+'" y1="10" y2="'+(H2-30)+'"/><text class="mut" x="'+xx(t)+'" y="'+(H2-12)+'" text-anchor="middle">'+t+' h</text>';});
  mile.forEach((q,i)=>{const yy=36+i*52, v=q[1]; m+='<text x="'+(L2-8)+'" y="'+(yy+5)+'" text-anchor="end">'+q[0]+'</text><line x1="'+xx(v[0])+'" x2="'+xx(v[4])+'" y1="'+yy+'" y2="'+yy+'" stroke="var(--bar2)" stroke-width="2"/><rect x="'+xx(v[1])+'" y="'+(yy-9)+'" width="'+(xx(v[3])-xx(v[1]))+'" height="18" rx="3" fill="var(--bar)" fill-opacity=".8"/><line x1="'+xx(v[2])+'" x2="'+xx(v[2])+'" y1="'+(yy-11)+'" y2="'+(yy+11)+'" stroke="var(--surface)" stroke-width="2.5"/><text class="val" x="'+xx(v[4])+'" y="'+(yy-14)+'" text-anchor="end">p50 '+v[2]+' h · p90 '+v[4]+' h</text>';});
  $("#hfMile").innerHTML=m+'</svg>';
  $("#hfCaseTbl tbody").innerHTML=X.h_case.map(r=>'<tr><td>'+esc(r[1])+'</td><td class="n">'+(r[2]==null?"–":r[2].toFixed(4))+'</td><td class="n">'+pfmt(r[3])+'</td><td>'+esc(r[6])+'</td></tr>').join("");
  const dl=X.open_delay_6h; vbar($("#hfDelay"),dl.map(r=>r[0]%4===0?(r[0]*6)+" h":""),dl.map(r=>r[1]),{fmt:v=>fmt(v/1000,0)+" k",width:860,height:240});
  $("#hfBehav tbody").innerHTML=[].concat(X.h_customer,X.h_session,X.h_send).map(r=>'<tr><td>'+esc(r[0])+'</td><td>'+esc(r[1])+'</td><td class="n">'+(r[2]==null?"–":(Math.abs(r[2])<1?r[2].toFixed(4):fmt(r[2],2)))+'</td><td class="n">'+pfmt(r[3])+'</td><td>'+esc(r[6])+'</td></tr>').join("");
  $("#hfChan tbody").innerHTML=X.h_channel.map(r=>'<tr><td>'+esc(r[1].replace(/: flat hours$/,""))+'</td><td class="n">'+fmt(r[2],1)+'</td><td class="n">'+pfmt(r[3])+'</td><td class="n">'+r[4].toFixed(4)+'</td><td>'+esc(r[6])+'</td></tr>').join("");
};
NR["hourly-pipeline"]=()=>{
  const lg=x=>{const c=[76.18009172947146,-86.50532032941677,24.01409824083091,-1.231739572450155,0.1208650973866179e-2,-0.5395239384953e-5]; let y=x, t=x+5.5; t-=(x+0.5)*Math.log(t); let s=1.000000000190015; for(let j=0;j<6;j++) s+=c[j]/++y; return -t+Math.log(2.5066282746310005*s/x);};
  const lgam=z=>lg(z);
  const pmfs=(mu,cv)=>{const sd=Math.sqrt(mu+(cv*mu)**2), kmax=Math.ceil(mu+14*sd+20), P=[], N=[];
    for(let k=0;k<=kmax;k++){P.push(Math.exp(k*Math.log(mu)-mu-lgam(k+1)));
      if(cv<=0) N.push(P[k]); else {const r=1/(cv*cv); N.push(Math.exp(lgam(k+r)-lgam(r)-lgam(k+1)+r*Math.log(r/(r+mu))+k*Math.log(mu/(r+mu))));}}
    return {P,N};};
  const lim=(p,a)=>{let c=0,lo=0,hi=p.length-1; for(let k=0;k<p.length;k++){c+=p[k]; if(c>=a/2){lo=k;break;}} c=0; for(let k=0;k<p.length;k++){c+=p[k]; if(c>=1-a/2){hi=k;break;}} return [lo,hi];};
  const tail=(p,l)=>{let s=0; p.forEach((v,k)=>{if(k<l[0]||k>l[1]) s+=v;}); return s;};
  const u=()=>{const mu=Math.max(1,+$("#nbMu").value), cv=Math.max(0,+$("#nbCv").value/100), a=Math.max(1e-5,+$("#nbA").value/100);
    const {P,N}=pmfs(mu,cv), lp=lim(P,a), ln=lim(N,a), fp=tail(N,lp), fn=tail(N,ln);
    $("#nbOut").textContent="Poisson limits: "+lp[0]+" to "+lp[1]+" events\nnegative-binomial limits: "+ln[0]+" to "+ln[1]+" events (variance μ + (CV·μ)² = "+fmt(mu+(cv*mu)**2,1)+")\n\nif the truth is negative binomial:\n  Poisson limits alarm on "+(100*fp).toFixed(3)+" % of hours ("+(fp/a).toFixed(1)+"× the target)\n  negative-binomial limits alarm on "+(100*fn).toFixed(3)+" % of hours\n"+(fp/a>2?"→ use negative-binomial limits for this series":"→ at this volume the two limits nearly agree");};
  ["#nbMu","#nbCv","#nbA"].forEach(s=>$(s).addEventListener("input",u)); u();
};
NR["hourly-walk"]=()=>{
  let f="reject";
  const draw=()=>{const rows=X.h_signal.filter(r=>f==="all"||r[4]);
    $("#hsTbl tbody").innerHTML=rows.map(r=>'<tr><td>'+esc(r[0])+'</td><td>'+esc(r[1])+'</td><td class="n">'+pfmt(r[2])+'</td><td class="n">'+pfmt(r[3])+'</td><td>'+(r[6]?'<span class="pill p-warn">signal</span>':r[5]?'<span class="pill p-acc">material</span>':'<span class="pill p-mut">no</span>')+'</td><td class="small">'+esc(r[8])+'</td></tr>').join("");};
  seg("hsFilter",v=>{f=v; draw();}); draw();
};
NR["hourly-models"]=()=>{
  const R=X.h_ready, W=900, rh=30, L=330, Rr=40, T=12, H=T+R.length*rh+34, lo=-1, hi=1.4, x=v=>L+(Math.max(lo,Math.min(hi,v))-lo)/(hi-lo)*(W-L-Rr);
  let s='<svg viewBox="0 0 '+W+' '+H+'" role="img" aria-label="gain over materiality per model">';
  s+='<rect x="'+x(1)+'" y="'+T+'" width="'+(x(hi)-x(1))+'" height="'+(H-T-26)+'" fill="var(--ok-soft)"/><text x="'+(x(1)+6)+'" y="'+(T+12)+'" style="fill:var(--ok);font-size:11px">material</text>';
  [-1,-0.5,0,0.5,1].forEach(t=>{s+='<line class="'+(t===0?"ax":"gl")+'" x1="'+x(t)+'" x2="'+x(t)+'" y1="'+T+'" y2="'+(H-26)+'"/><text class="mut" x="'+x(t)+'" y="'+(H-8)+'" text-anchor="middle">'+t+'×</text>';});
  s+='<line class="ref" x1="'+x(0)+'" x2="'+x(0)+'" y1="'+T+'" y2="'+(H-26)+'"/>';
  R.forEach((r,i)=>{const y=T+i*rh+rh/2, m=r[9], c=r[11]==="green"?"var(--ok)":r[11]==="amber"?"var(--warn)":"var(--crit)", d=r[6]/m, a=r[7]/m, b=r[8]/m;
    s+='<g data-tip="'+esc('<b>'+r[1]+'</b><br>'+r[2]+': '+r[3]+' vs '+r[5]+' ('+r[4]+')<br>gain '+r[6]+' ['+r[7]+', '+r[8]+'] · material '+m+'<br>'+r[11]+': '+r[12])+'">';
    s+='<text x="'+(L-8)+'" y="'+(y+4)+'" text-anchor="end">'+esc(r[1])+'</text><line x1="'+x(a)+'" x2="'+x(b)+'" y1="'+y+'" y2="'+y+'" stroke="'+c+'" stroke-width="2.5"/><circle cx="'+x(d)+'" cy="'+y+'" r="5" fill="'+c+'"/>';
    if(d<lo) s+='<text x="'+(x(lo)+8)+'" y="'+(y-6)+'" class="val" style="fill:var(--crit)">◀ '+d.toFixed(2)+'×</text>';
    s+='</g>';});
  $("#hmGate").innerHTML=s+'</svg><div class="legend"><span><i style="background:var(--ok)"></i>green</span><span><i style="background:var(--warn)"></i>amber</span><span><i style="background:var(--crit)"></i>red</span><span>x: out-of-time gain ÷ materiality threshold, 95 % bootstrap interval</span></div>';
  const sel=$("#gtLoad"); sel.innerHTML=R.map((r,i)=>'<option value="'+i+'">'+esc(r[1])+'</option>').join("")+'<option value="-1">my own numbers</option>';
  const load=i=>{if(i<0) return; const r=R[i]; $("#gtD").value=r[6]; $("#gtLo").value=r[7]; $("#gtHi").value=r[8]; $("#gtM").value=r[9]; $("#gtF").value="1";};
  const u=()=>{const d=+$("#gtD").value, a=+$("#gtLo").value, b=+$("#gtHi").value, m=+$("#gtM").value, folds=$("#gtF").value==="1", i=+sel.value;
    const se=(b-a)/(2*1.96), mde=2.8*se; let v,cause;
    if(a>0&&d>=m&&folds){v="GREEN"; cause="significant and material: open the ADR-012 model path";}
    else if(a>0){v="AMBER"; cause=d>=m?"folds disagree: stable evidence first":"significant but not material: a real gain too small to maintain, monitor and explain";}
    else {v="RED"; cause=mde>m?"insufficient volume: even a material gain would be undetectable at this sample":(i>=0&&R[i][11]==="red"?R[i][12]:"the scenario's diagnosis: generator independence, missing field or data defect");}
    $("#gtOut").innerHTML='verdict: <span class="big" style="color:var(--'+(v==="GREEN"?"ok":v==="AMBER"?"warn":"crit")+')">'+v+'</span>\n'+esc(cause)+'\n\nbootstrap SE ≈ (high − low) / 3.92 = '+se.toPrecision(3)+'\nminimum detectable effect = 2.8 · SE = '+mde.toPrecision(3)+(mde>m?"  > material: more data needed before any verdict":"  ≤ material: the sample could see a material gain")+(i>=0?'\nrequirement to green: '+esc(R[i][13]):'');};
  sel.addEventListener("change",()=>{load(+sel.value); u();}); ["#gtD","#gtLo","#gtHi","#gtM","#gtF"].forEach(s=>$(s).addEventListener("input",()=>{u();}));
  load(0); u();
};
NR["hourly-kpis"]=()=>{
  $("#hkTbl tbody").innerHTML=X.h_kpis.map(r=>{const k=/needs/.test(r[5])?["p-warn","needs data"]:/series/.test(r[5])?["p-acc","this series"]:["p-ok","runs today"];
    return '<tr><td><b>'+esc(r[0])+'</b></td><td>'+esc(r[1])+'</td><td>'+esc(r[2])+'</td><td>'+esc(r[3])+'</td><td>'+esc(r[4])+'</td><td><span class="pill '+k[0]+'">'+k[1]+'</span> <span class="small">'+esc(r[5])+'</span></td></tr>';}).join("");
};
NR.notebooks=()=>{
  $("#nbIndex").innerHTML=GRAINS.map(G=>{const list=NOTEBOOKS.filter(n=>n.grain===G.id);
    return '<section class="blk nbg"><header><div class="eyebrow">'+esc(G.nb)+'</div><h2>'+esc(G.name)+' grain</h2></header>'+list.map(n=>'<div class="card" style="margin:.8rem 0"><h4>'+esc(n.series)+'</h4><p class="small">'+esc(n.what)+'</p><ol class="small" style="columns:2 280px;margin:.4rem 0">'+n.items.map(i=>'<li>'+esc(i)+'</li>').join("")+'</ol><button class="btn" type="button" data-route="'+n.route+'">Told in '+esc(titleOf(n.route))+' →</button></div>').join("")+'</section>';}).join("");
};

NR.grainfacts=()=>{
  $$(".gfacts").forEach(el=>{const G=GRAINS.find(x=>x.id===el.dataset.g), v=grainCounts[G.id];
    el.innerHTML='<dl class="gf"><dt>one row is</dt><dd>'+esc(G.unit)+'</dd><dt>volume</dt><dd>'+esc(G.vol)+'</dd><dt>clock</dt><dd>'+esc(G.clock)+'</dd><dt>models · '+esc(v.unit)+'</dt><dd>'+mixBar(v)+'<div class="vlegend">'+Object.keys(v.c).map((k,i)=>'<span><i style="background:var(--'+(k==="mut"?"bar2":k)+')"></i>'+v.c[k]+' '+esc(v.lab[i])+'</span>').join("")+'</div></dd><dt>headline</dt><dd>'+esc(G.key)+'</dd><dt>notebooks</dt><dd class="mono" style="font-size:.78rem">'+esc(G.nb)+'</dd></dl>';});
};
