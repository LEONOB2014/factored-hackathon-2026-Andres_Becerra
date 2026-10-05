/* ================================================================ routes */
const GLOBAL_ROUTES=["mission","board","notebooks","glossary"];
const ORDER=["mission",...VIEWS.event,...VIEWS.country,...VIEWS.daily,...VIEWS.hourly,"board","notebooks","glossary"];
const ALIAS={overview:"mission",decide:"board",gloss:"glossary",home:"mission"};
ORDER.forEach(r=>{(PAGES[r].blocks||[]).forEach(b=>{if(b.mod&&b.intro!==false&&!ALIAS[b.mod]) ALIAS[b.mod]=r;});});
ORDER.forEach(r=>{(PAGES[r].blocks||[]).forEach(b=>{if(b.mod&&!ALIAS[b.mod]) ALIAS[b.mod]=r;});});
GRAINS.forEach(g=>{ALIAS[g.id]=g.id+"-overview";});
const resolve=r=>{r=(r||"").replace(/^#/,""); if(PAGES[r]) return r; if(ALIAS[r]) return ALIAS[r]; return null;};
const routeGrain=r=>PAGES[r]&&PAGES[r].grain||null;
const groupName=g=>(GROUPS.find(x=>x[0]===g)||[g,g])[1];
const titleOf=r=>{const p=PAGES[r]; if(!p) return r; return p.grain?GRAINS.find(x=>x.id===p.grain).name+" · "+p.title:p.title;};
const grainCounts=grainVerdicts();

/* ================================================================ build every view once, as a dashboard */
const main=$("#main");
const slug=s=>s.toLowerCase().replace(/<[^>]+>/g,"").replace(/[^a-z0-9]+/g,"-").replace(/^-|-$/g,"").slice(0,48);
function blockHTML(b){
  if(b.html) return b.html;
  const m=MODS[b.mod]; if(!m) return "";
  const subs=b.subs?b.subs.map(i=>m.subs[i]).filter(Boolean):m.subs;
  return '<section class="mod">'+(b.intro===false?"":m.intro)+subs.map(s=>s.h).join("")+'</section>';
}
function crumbs(r){
  const p=PAGES[r], parts=['<button type="button" data-route="mission">Mission control</button>'];
  if(p.grain){const G=GRAINS.find(x=>x.id===p.grain); parts.push('<span>›</span><button type="button" data-route="'+p.grain+'-overview">'+G.name+' grain</button><span>›</span><span>'+groupName(p.group)+'</span>');}
  return '<nav class="crumbs" aria-label="Breadcrumb">'+parts.join("")+'</nav>';
}
function sameKind(r,g){
  const p=PAGES[r]; if(!p||!p.grain) return g+"-overview";
  if(PAGES[g+"-"+p.id]) return g+"-"+p.id;
  if(p.kind){const k=VIEWS[g].find(x=>PAGES[x].kind===p.kind); if(k) return k;}
  return VIEWS[g].find(x=>PAGES[x].group===p.group)||g+"-overview";
}
function pager(r){
  const p=PAGES[r], out=[];
  if(p.grain){
    const list=VIEWS[p.grain], i=list.indexOf(r), gi=GRAINS.findIndex(x=>x.id===p.grain);
    if(i>0) out.push(["previous view",list[i-1]]);
    if(i<list.length-1) out.push(["next view",list[i+1]]);
    if(gi>0) out.push(["in the "+GRAINS[gi-1].name.toLowerCase()+" grain",sameKind(r,GRAINS[gi-1].id)]);
    if(gi<GRAINS.length-1) out.push(["in the "+GRAINS[gi+1].name.toLowerCase()+" grain",sameKind(r,GRAINS[gi+1].id)]);
  } else {const i=GLOBAL_ROUTES.indexOf(r); if(i>0) out.push(["previous",GLOBAL_ROUTES[i-1]]); if(i<GLOBAL_ROUTES.length-1) out.push(["next",GLOBAL_ROUTES[i+1]]);}
  return '<div class="pager">'+out.map(([l,t])=>'<button type="button" data-route="'+t+'"><small>'+l+'</small>'+esc(titleOf(t))+'</button>').join("")+'</div>';
}
const NOTE_KINDS=[["all","All"],["Concept","Concept"],["For","For models"],["Why","Why it matters"],["Tips","Tips"],["Caution","Caution"]];
const isWide=c=>!!c.querySelector("pre.mermaid,.flow,.cards,.nblist,.heat,.tline,.two,.cols,.gm,.vrows,.declist,.chart,.dec,#nbIndex,dl.gloss,.calc .chart")||
  Array.from(c.querySelectorAll("table")).some(t=>t.querySelectorAll("thead th").length>=4||t.querySelectorAll("tbody tr").length>12)||c.textContent.length>1600;
function dashboardize(el,r){
  const p=PAGES[r], body=$(".vsrc",el), kp=$(".vkpis",el), cards=$(".vcards",el), notes=$(".nlist",el);
  const nodes=[]; Array.from(body.childNodes).forEach(n=>{if(n.nodeType===1&&n.matches("details.panel")) n.dataset.for="this view";if(n.nodeType===1&&n.matches("section.mod,section.blk")) nodes.push(...Array.from(n.childNodes)); else nodes.push(n);});
  let card=null, ctitle=p.sub||p.title;
  const newCard=h=>{card=document.createElement("section"); card.className="vcard"; cards.appendChild(card); if(h){card.appendChild(h); ctitle=h.textContent;}};
  nodes.forEach(n=>{
    if(n.nodeType!==1){if(n.textContent.trim()){if(!card) newCard(); card.appendChild(n);} return;}
    if(n.matches(".kpis")){if(n.id){const ls=card&&card.lastElementChild; if(ls&&ls.matches(".seg")) kp.appendChild(ls); kp.appendChild(n); n.classList.add("merged");} else Array.from(n.children).forEach(k=>kp.appendChild(k)); return;}
    if(n.matches("details.panel")){if(!n.dataset.for) n.dataset.for=ctitle; notes.appendChild(n); return;}
    if(n.matches("h3")){newCard(n); return;}
    if(n.matches(".calc")){const h4=$("h4",n), h3=document.createElement("h3"); h3.textContent=h4?h4.textContent:"Try it"; if(h4) h4.remove(); newCard(h3); card.classList.add("tool"); card.appendChild(n); return;}
    if(!card) newCard(); card.appendChild(n);
  });
  $$("details.panel",cards).forEach(d=>{const c=d.closest(".vcard"), h=c&&$("h3",c); d.dataset.for=h?h.textContent:ctitle; notes.appendChild(d);});
  Array.from(cards.children).forEach(c=>{if(!Array.from(c.childNodes).some(n=>!(n.nodeType===1&&n.matches("h3"))&&(n.nodeType===1||n.textContent.trim()))) c.remove(); else if(isWide(c)) c.classList.add("w");});
  const cs=Array.from(cards.children), halves=cs.filter(c=>!c.classList.contains("w"));
  if(halves.length%2===1) halves[halves.length-1].classList.add("w");
  body.remove();
  if(!kp.children.length) kp.remove();
  $$("details.panel",notes).forEach(d=>{const k=$(".k",d), lab=document.createElement("div"); lab.className="nfor"; lab.textContent="on: "+d.dataset.for; $(".body",d).prepend(lab); d.dataset.kind=k?k.textContent:"";});
  const nn=$$("details.panel",notes).length;
  const nb=$(".notes",el);
  if(!nn) $(".nhead",el).remove();
  else $(".ncount",el).textContent=nn+" note"+(nn>1?"s":"");
  const hs=$$(".vcard > h3",el);
  hs.forEach(h=>{if(!h.id){let s=r+"--"+slug(h.textContent); while(document.getElementById(s)) s+="-x"; h.id=s;}});
  const toc=$(".vtoc",el);
  if(hs.length>2) toc.innerHTML='<h4>In this view</h4>'+hs.map(h=>'<a href="#" data-sec="'+h.id+'">'+esc(h.textContent)+'</a>').join(""); else toc.remove();
  if(!nn&&hs.length<=2&&!p.src){nb.classList.add("empty"); $(".vmain",el).classList.add("solo");}
}
ORDER.forEach(r=>{
  const p=PAGES[r], el=document.createElement("article");
  el.className="view"; el.dataset.view=r; el.setAttribute("aria-label",titleOf(r));
  el.innerHTML=crumbs(r)+
    '<header class="vhead"><div class="eyebrow">'+(p.grain?GRAINS.find(x=>x.id===p.grain).name+" grain · "+groupName(p.group):(p.eyebrow||""))+'</div><h1>'+p.title+'</h1>'+(p.sub&&p.sub!==p.title?'<p class="vsub">'+p.sub+'</p>':'')+(p.lede?'<p class="lede">'+p.lede+'</p>':'')+'</header>'+
    '<div class="vkpis"></div>'+
    '<div class="vmain"><div class="vcwrap"><div class="vcards"></div></div>'+
    '<aside class="notes" aria-label="Notes">'+(p.src?'<div class="nsrc"><h4>Source</h4><p class="mono">'+esc(p.src)+'</p></div>':'')+'<nav class="vtoc"></nav>'+
      '<div class="nhead"><h4>Notes <span class="ncount"></span></h4><div class="nfilter seg" role="group" aria-label="Note kind">'+NOTE_KINDS.map((k,i)=>'<button type="button" data-nk="'+k[0]+'" aria-pressed="'+(i===0)+'">'+k[1]+'</button>').join("")+'</div></div><div class="nlist"></div></aside></div>'+
    '<div class="vsrc">'+p.blocks.map(blockHTML).join("")+'</div>'+
    '<footer class="vfoot">'+pager(r)+'</footer>';
  main.appendChild(el);
  dashboardize(el,r);
});

/* ================================================================ chrome: tabs, rail */
const tabs=$("#grainTabs");
tabs.innerHTML=GRAINS.map((g,i)=>'<button class="gt" type="button" role="tab" data-grain="'+g.id+'" aria-selected="false">'+glyph(g.id)+'<span class="gl">'+g.name+'<small>'+g.short+'</small></span><span class="k">'+(i+1)+'</span></button>').join("");
let lastGrain=store.get("grain.lastGrain")||"event";
function renderRail(r){
  const g=routeGrain(r)||lastGrain, G=GRAINS.find(x=>x.id===g);
  let h='<div class="gname">'+glyph(g,34,20)+'<div><b>'+G.name+' grain</b><small>'+G.short+'</small></div></div>';
  GROUPS.forEach(gr=>{const vs=VIEWS[g].filter(x=>PAGES[x].group===gr[0]); if(!vs.length) return;
    h+='<h3>'+gr[1]+'</h3>'+vs.map(x=>'<button class="vi" type="button" data-route="'+x+'"'+(x===r?' aria-current="page"':'')+'><span class="dot '+(PAGES[x].s||"")+'"></span><span>'+esc(PAGES[x].title)+'</span></button>').join("");});
  h+='<h3>All grains</h3>'+[["mission","Mission control","◎"],["board","Decision board","◆"],["notebooks","Notebook index","▤"],["glossary","Glossary","Aa"]].map(x=>'<button class="vi gl" type="button" data-route="'+x[0]+'"'+(x[0]===r?' aria-current="page"':'')+'><span class="ic">'+x[2]+'</span><span>'+x[1]+'</span></button>').join("");
  $("#rail").innerHTML=h;
}

/* ================================================================ router */
let cur=null;
const doneMods={}, doneNew={};
function go(r,opt={}){
  const rr=resolve(r)||"mission";
  cur=rr;
  $$(".view").forEach(v=>v.classList.toggle("active",v.dataset.view===rr));
  const g=routeGrain(rr); if(g){lastGrain=g; store.set("grain.lastGrain",g);}
  $$(".gt").forEach(b=>b.setAttribute("aria-selected",String(b.dataset.grain===g)));
  renderRail(rr); closeNav();
  try{history.replaceState(null,"","#"+rr)}catch(e){}
  store.set("grain.route",rr);
  document.title="LATAM Bank Grain Atlas · "+titleOf(rr);
  const P=PAGES[rr];
  (P.mods||[]).forEach(m=>{if(!doneMods[m]&&ATLAS_R[m]){doneMods[m]=true; try{ATLAS_R[m]();}catch(e){console.warn("render",m,e);}}});
  (P.nrs||[]).forEach(n=>{if(!doneNew[n]&&NR[n]){doneNew[n]=true; try{NR[n]();}catch(e){console.warn("render",n,e);}}});
  if(P.kind==="decisions"||rr==="board"||rr==="mission") renderDecLists();
  runMermaid(rr);
  const a=$('#rail [aria-current="page"]'); if(a&&a.scrollIntoView) a.scrollIntoView({block:"nearest"});
  if(opt.sec){const t=document.getElementById(opt.sec); if(t){setTimeout(()=>t.scrollIntoView({block:"start"}),30); return;}}
  window.scrollTo(0,0);
}
window.addEventListener("hashchange",()=>{const r=resolve(location.hash); if(r&&r!==cur) go(r);});
document.addEventListener("click",e=>{
  const sec=e.target.closest("[data-sec]"); if(sec){e.preventDefault(); const t=document.getElementById(sec.dataset.sec); if(t) t.scrollIntoView({block:"start",behavior:matchMedia("(prefers-reduced-motion: reduce)").matches?"auto":"smooth"}); return;}
  const nk=e.target.closest("[data-nk]"); if(nk){const box=nk.closest(".notes"); $$("[data-nk]",box).forEach(b=>b.setAttribute("aria-pressed",String(b===nk)));
    $$("details.panel",box).forEach(d=>{d.hidden=!(nk.dataset.nk==="all"||(d.dataset.kind||"").startsWith(nk.dataset.nk));}); return;}
  const b=e.target.closest("[data-route],[data-goto]"); if(b){e.preventDefault(); go(b.dataset.route||b.dataset.goto); return;}
  const gt=e.target.closest(".gt"); if(gt){switchGrain(gt.dataset.grain); return;}
  const a=e.target.closest('a[href^="#"]'); if(a&&!a.dataset.sec){const r=resolve(a.getAttribute("href")); if(r){e.preventDefault(); go(r);}}
});
function switchGrain(g){go(cur&&PAGES[cur].grain?sameKind(cur,g):g+"-overview");}

/* nav drawer (narrow screens) */
const navBtn=$("#navBtn"), rail=$("#rail"), scrim=$("#scrim");
function closeNav(){rail.classList.remove("open"); scrim.classList.remove("on"); navBtn.setAttribute("aria-expanded","false");}
navBtn.addEventListener("click",()=>{const o=!rail.classList.contains("open"); rail.classList.toggle("open",o); scrim.classList.toggle("on",o); navBtn.setAttribute("aria-expanded",String(o));});
scrim.addEventListener("click",closeNav);

/* theme */
const root=document.documentElement;
const savedTheme=store.get("grain.theme"); if(savedTheme) root.setAttribute("data-theme",savedTheme);
function isDark(){const t=root.getAttribute("data-theme"); return t?t==="dark":matchMedia("(prefers-color-scheme: dark)").matches;}
function paintThemeLbl(){$("#themeLbl").textContent=isDark()?"Dark":"Light";}
function toggleTheme(){const next=isDark()?"light":"dark"; root.setAttribute("data-theme",next); store.set("grain.theme",next); paintThemeLbl(); rerenderMermaid(); toast((next==="dark"?"Dark":"Light")+" theme");}
$("#themeBtn").addEventListener("click",toggleTheme); paintThemeLbl();

/* explanations */
function toggleExp(){const b=$("#expBtn"), on=b.getAttribute("aria-pressed")!=="true"; b.setAttribute("aria-pressed",String(on)); $$("details.panel").forEach(d=>d.open=on); toast(on?"Every note open":"Notes folded");}
$("#expBtn").addEventListener("click",toggleExp);

/* toast */
let toastT=null;
function toast(msg){let t=$(".toast"); if(!t){t=document.createElement("div"); t.className="toast"; t.setAttribute("role","status"); document.body.appendChild(t);} t.textContent=msg; t.hidden=false; clearTimeout(toastT); toastT=setTimeout(()=>{t.hidden=true;},1600);}

/* mermaid */
const mmSrc={}; $$("pre.mermaid").forEach(p=>mmSrc[p.id]=p.textContent);
let mmReady=false;
function runMermaid(r){
  if(!window.mermaid) return;
  if(!mmReady){window.mermaid.initialize({startOnLoad:false,theme:isDark()?"dark":"neutral",securityLevel:"strict",fontFamily:"IBM Plex Sans, system-ui, sans-serif"}); mmReady=true;}
  const nodes=$$('.view[data-view="'+r+'"] pre.mermaid:not([data-processed])');
  if(nodes.length){try{window.mermaid.run({nodes}).catch(()=>{})}catch(e){}}
}
function rerenderMermaid(){if(!window.mermaid) return; mmReady=false; $$("pre.mermaid").forEach(p=>{p.removeAttribute("data-processed"); p.textContent=mmSrc[p.id];}); if(cur) runMermaid(cur);}

/* tooltips */
const tip=$("#tip");
document.addEventListener("mouseover",e=>{const t=e.target.closest("[data-tip]"); if(t){tip.innerHTML=t.dataset.tip; tip.hidden=false;}});
document.addEventListener("mousemove",e=>{if(!tip.hidden){const w=tip.offsetWidth, x=Math.min(window.innerWidth-w-8,e.clientX+14); tip.style.left=x+"px"; tip.style.top=(e.clientY+16)+"px";}});
document.addEventListener("mouseout",e=>{const t=e.target.closest("[data-tip]"); if(t&&!t.contains(e.relatedTarget)) tip.hidden=true;});

/* ================================================================ command palette */
const IDX=[];
ORDER.forEach(r=>{const p=PAGES[r]; IDX.push({ty:"view",t:titleOf(r),s:(p.grain?groupName(p.group)+" · ":"")+(p.sub||"").replace(/<[^>]+>/g,""),r});
  $$('.view[data-view="'+r+'"] .vcard > h3[id]').forEach(h=>IDX.push({ty:"section",t:h.textContent,s:titleOf(r),r,sec:h.id}));});
GLOSS.forEach(g=>IDX.push({ty:"term",t:g[0],s:g[1],r:"glossary",term:g[0]}));
DECISIONS.forEach(d=>IDX.push({ty:"decision",t:d.title,s:(DGRAIN[d.id]||[]).join(", ")+" · "+d.due,r:"board",dec:d.id}));
NOTEBOOKS.forEach(n=>{IDX.push({ty:"notebooks",t:n.series,s:n.what,r:"notebooks"}); n.items.forEach(it=>IDX.push({ty:"notebook",t:it,s:n.series,r:n.route}));});
const pal=$("#pal"), palIn=$("#palIn"), palRes=$("#palRes");
let palSel=0, palHits=[];
function openPal(){pal.hidden=false; palIn.value=""; renderPal(); setTimeout(()=>palIn.focus(),10);}
function closePal(){pal.hidden=true;}
function renderPal(){
  const q=palIn.value.trim().toLowerCase(), toks=q.split(/\s+/).filter(Boolean);
  if(!toks.length) palHits=IDX.filter(x=>x.ty==="view").slice(0,40);
  else palHits=IDX.map(x=>{const hay=(x.t+" "+x.s).toLowerCase(); if(!toks.every(t=>hay.includes(t))) return null; const tl=x.t.toLowerCase();
      return {x,sc:(tl.startsWith(q)?0:tl.includes(q)?1:2)+({view:0,section:.1,decision:.2,term:.3,notebook:.4,notebooks:.4}[x.ty]||0)};}).filter(Boolean).sort((a,b)=>a.sc-b.sc).slice(0,40).map(o=>o.x);
  palSel=0;
  palRes.innerHTML=palHits.map((h,i)=>'<button type="button" class="pr'+(i===0?" on":"")+'" role="option" data-pi="'+i+'"><span class="ty">'+h.ty+'</span><span class="tx"><b>'+esc(h.t)+'</b><small>'+esc(h.s)+'</small></span></button>').join("")||'<p class="small" style="padding:.6rem">Nothing matches. Try fewer words.</p>';
}
function pickPal(i){const h=palHits[i]; if(!h) return; closePal();
  if(h.term){go("glossary"); const f=$("#glFilter"); if(f){f.value=h.term; f.dispatchEvent(new Event("input"));} return;}
  if(h.dec){bdFilter="all"; go("board"); setTimeout(()=>{const c=$('.view[data-view="board"] [data-dec="'+h.dec+'"]'); if(c) c.scrollIntoView({block:"start"});},40); return;}
  go(h.r,{sec:h.sec});}
palIn.addEventListener("input",renderPal);
palIn.addEventListener("keydown",e=>{
  if(e.key==="ArrowDown"||e.key==="ArrowUp"){e.preventDefault(); palSel=Math.max(0,Math.min(palHits.length-1,palSel+(e.key==="ArrowDown"?1:-1))); $$(".pr",palRes).forEach((b,i)=>b.classList.toggle("on",i===palSel)); const b=$$(".pr",palRes)[palSel]; if(b) b.scrollIntoView({block:"nearest"});}
  else if(e.key==="Enter"){e.preventDefault(); pickPal(palSel);} else if(e.key==="Escape"){closePal();}});
palRes.addEventListener("click",e=>{const b=e.target.closest("[data-pi]"); if(b) pickPal(+b.dataset.pi);});
pal.addEventListener("click",e=>{if(e.target===pal) closePal();});
$("#palBtn").addEventListener("click",openPal);
const help=$("#help");
$("#helpBtn").addEventListener("click",()=>{help.hidden=false;});
help.addEventListener("click",e=>{if(e.target===help) help.hidden=true;});

/* keyboard */
document.addEventListener("keydown",e=>{
  if((e.metaKey||e.ctrlKey)&&e.key.toLowerCase()==="k"){e.preventDefault(); pal.hidden?openPal():closePal(); return;}
  if(e.key==="Escape"){closePal(); help.hidden=true; closeNav(); return;}
  const tg=e.target, typing=tg&&(/^(INPUT|TEXTAREA|SELECT)$/.test(tg.tagName)||tg.isContentEditable);
  if(typing||e.metaKey||e.ctrlKey||e.altKey||!pal.hidden) return;
  const k=e.key, g=routeGrain(cur);
  if(k==="/"){e.preventDefault(); openPal();}
  else if(k==="?"){help.hidden=!help.hidden;}
  else if(k==="0"){go("mission");}
  else if(/^[1-4]$/.test(k)){switchGrain(GRAINS[+k-1].id);}
  else if(k==="["||k==="]"){const list=VIEWS[g||lastGrain], i=list.indexOf(cur); go(list[Math.max(0,Math.min(list.length-1,(i<0?0:i)+(k==="]"?1:-1)))]);}
  else if(k===","||k==="."){const gi=GRAINS.findIndex(x=>x.id===(g||lastGrain)), ni=(gi+(k==="."?1:-1)+GRAINS.length)%GRAINS.length; switchGrain(GRAINS[ni].id);}
  else if(k==="e"){toggleExp();}
  else if(k==="t"){toggleTheme();}
  else if(k==="b"){go("board");} else if(k==="g"){go("glossary");} else if(k==="n"){go("notebooks");}
});
