/* The technical report as a book inside the Atlas. The PDF ships with the page (base64 in #ebkData) and is drawn by
   pdf.js, which loads from cdnjs the first time the book opens, so the Atlas starts exactly as before. */
(function(){
"use strict";
const PDFJS="https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/";
const $=id=>document.getElementById(id);
const root=$("ebk"), stage=$("ebkStage"), book=$("ebkBook"), L=$("ebkL"), R=$("ebkR"), msg=$("ebkMsg");
const pgIn=$("ebkPg"), ofEl=$("ebkOf"), run=$("ebkRun"), edge=$("ebkEdge"), toc=$("ebkToc"), tocBtn=$("ebkTocBtn");
const reduce=window.matchMedia&&matchMedia("(prefers-reduced-motion: reduce)").matches;
const TURN=reduce?0:640;
const store={get(k){try{return localStorage.getItem(k)}catch(e){return null}},set(k,v){try{localStorage.setItem(k,v)}catch(e){}}};

let pdf=null, N=0, labels=null, aspect=0.707, two=true, pw=0, ph=0, cur=1, busy=false, opener=null, prevHash="";
let marks=[];                 // outline entries {title, depth, page}
const cache=new Map();        // "page@width" -> canvas, most recent last

/* ---------------------------------------------------------------- loading */
function script(src){return new Promise((ok,no)=>{const s=document.createElement("script"); s.src=src; s.onload=ok;
  s.onerror=()=>no(new Error("could not load "+src)); document.head.appendChild(s);});}
let loading=null;
function load(){
  if(loading) return loading;
  loading=(async()=>{
    if(!window.pdfjsLib) await script(PDFJS+"pdf.min.js");
    if(!window.pdfjsWorker) await script(PDFJS+"pdf.worker.min.js");   // runs pdf.js on this page: no worker needed
    pdfjsLib.GlobalWorkerOptions.workerSrc=PDFJS+"pdf.worker.min.js";
    const b64=$("ebkData").textContent.trim(), bin=atob(b64), bytes=new Uint8Array(bin.length);
    for(let i=0;i<bin.length;i++) bytes[i]=bin.charCodeAt(i);
    pdf=await pdfjsLib.getDocument({data:bytes,isEvalSupported:false}).promise;
    N=pdf.numPages;
    try{labels=await pdf.getPageLabels();}catch(e){labels=null;}
    const v=(await pdf.getPage(1)).getViewport({scale:1}); aspect=v.width/v.height;
    await outline();
  })();
  return loading;
}
const label=p=>labels&&labels[p-1]?labels[p-1]:String(p);
function pageOfLabel(s){
  s=String(s).trim().toLowerCase(); if(!s) return null;
  if(labels){const i=labels.findIndex(x=>String(x).toLowerCase()===s); if(i>=0) return i+1;}
  const n=parseInt(s,10); return n>=1&&n<=N?n:null;
}
async function destPage(dest){
  try{
    if(typeof dest==="string") dest=await pdf.getDestination(dest);
    if(!Array.isArray(dest)) return null;
    const ref=dest[0]; return (typeof ref==="number"?ref:await pdf.getPageIndex(ref))+1;
  }catch(e){return null;}
}

/* ---------------------------------------------------------------- outline: contents, running title, fore-edge */
async function outline(){
  const out=await pdf.getOutline()||[];
  async function walk(items,depth){for(const it of items){const p=await destPage(it.dest);
    marks.push({title:it.title,depth,page:p||1,kids:it.items&&it.items.length?it.items:null}); if(it.items) await walk(it.items,depth+1);}}
  await walk(out,0);
  buildToc(); buildEdge();
}
function runningTitle(p){let t=null; for(const m of marks){if(m.depth<=1&&!isPart(m)&&m.page<=p) t=m;} return t?t.title:"Title and contents";}
function esc(s){return String(s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));}
// The outline has parts (depth 0 with children: the six parts and the appendices), entries at the root without
// children (contents, abstract, conventions, bibliography), chapters (depth 1) and their sections (depth 2).
const isPart=m=>m.depth===0&&!!m.kids;
function buildToc(){
  const ol=$("ebkTocList"); let h="";
  const item=m=>'<button type="button" class="it" data-p="'+m.page+'"><span class="t">'+esc(m.title)+'</span><span class="p">'+esc(label(m.page))+'</span></button>';
  marks.forEach((m,i)=>{
    if(isPart(m)){h+='<li class="part">'+esc(m.title)+'</li>'; return;}
    if(m.depth>1) return;
    const kids=[]; for(const s of marks.slice(i+1)){ if(s.depth<=m.depth) break; if(s.depth===m.depth+1) kids.push(s); }
    h+='<li>'+item(m)+(kids.length?'<details><summary class="sub">'+kids.length+(kids.length===1?' section':' sections')+'</summary><ol>'+
      kids.map(k=>'<li>'+item(k)+'</li>').join("")+'</ol></details>':'')+'</li>';
  });
  ol.innerHTML=h;
}
function edgeEntries(){
  const out=[{title:"Title and contents",page:1}];
  marks.filter(m=>m.depth<=1&&!isPart(m)).sort((a,b)=>a.page-b.page).forEach(m=>{
    const last=out[out.length-1]; if(m.page>last.page) out.push(m); else if(m.page===last.page) out[out.length-1]=m;});
  return out;
}
function buildEdge(){
  const es=edgeEntries(), appAt=(marks.find(m=>isPart(m)&&/^appendices$/i.test(m.title))||{page:N+1}).page; let h="";
  es.forEach((m,i)=>{const end=i+1<es.length?es[i+1].page:N+1, w=Math.max(1,end-m.page);
    h+='<i class="'+(m.page>=appAt?"app":"")+'" style="--w:'+w+'" data-p="'+m.page+'" title="'+esc(m.title)+' · p. '+esc(label(m.page))+'"></i>';});
  edge.innerHTML=h+'<span class="mark" id="ebkMark"></span>';
}

/* ---------------------------------------------------------------- layout and drawing */
function layout(){
  const W=Math.min(stage.clientWidth,root.clientWidth)-32, H=stage.clientHeight-24;
  two=W>=820&&W/H>1.05;
  const maxW=two?W/2:W; ph=Math.floor(Math.min(H,maxW/aspect)); pw=Math.floor(ph*aspect);
  book.classList.toggle("single",!two); L.hidden=!two;
  for(const el of [L,R]){el.style.width=pw+"px"; el.style.height=ph+"px";}
}
async function render(p){
  const dpr=Math.min(window.devicePixelRatio||1,2.5), key=p+"@"+pw+"@"+dpr;
  if(cache.has(key)){const c=cache.get(key); cache.delete(key); cache.set(key,c); return c;}
  const page=await pdf.getPage(p), vp=page.getViewport({scale:pw/page.getViewport({scale:1}).width*dpr});
  const c=document.createElement("canvas"); c.width=Math.round(vp.width); c.height=Math.round(vp.height);
  await page.render({canvasContext:c.getContext("2d"),viewport:vp}).promise;
  c._vp=page.getViewport({scale:pw/page.getViewport({scale:1}).width}); c._page=page;
  cache.set(key,c); while(cache.size>28) cache.delete(cache.keys().next().value);
  return c;
}
function blit(slot,c){const cv=slot.querySelector("canvas"); cv.width=c.width; cv.height=c.height; cv.getContext("2d").drawImage(c,0,0);}
async function links(slot,p,c){
  const box=slot.querySelector(".ebk-lnk"); box.innerHTML="";
  let anns=[]; try{anns=await c._page.getAnnotations({intent:"display"});}catch(e){}
  for(const a of anns){ if(a.subtype!=="Link") continue;
    const [x1,y1,x2,y2]=c._vp.convertToViewportRectangle(a.rect), el=document.createElement("a");
    el.style.left=Math.min(x1,x2)+"px"; el.style.top=Math.min(y1,y2)+"px"; el.style.width=Math.abs(x2-x1)+"px"; el.style.height=Math.abs(y2-y1)+"px";
    if(a.url){el.href=a.url; el.target="_blank"; el.rel="noopener"; el.title=a.url;}
    else if(a.dest){el.href="#"; el.dataset.dest=JSON.stringify(a.dest);}
    else continue;
    box.appendChild(el);}
}
async function show(slot,p){
  slot.classList.remove("blank","void");
  if(!p){slot.classList.add("void"); slot.querySelector(".ebk-lnk").innerHTML=""; slot.removeAttribute("aria-label"); return;}
  if(p>N){slot.classList.add("blank"); slot.querySelector(".ebk-lnk").innerHTML=""; return;}
  const c=await render(p); blit(slot,c); slot.setAttribute("aria-label","Page "+label(p)); links(slot,p,c);
}
// two-page spreads open like a printed book: the title page alone on the right, then even|odd
const spreadOf=p=>p<=1?[null,1]:[p-(p%2), p-(p%2)+1];
function shown(){return two?spreadOf(cur):[null,cur];}
async function paint(){
  const [l,r]=shown(); await Promise.all([two?show(L,l):null, show(R,r)]); status();
}
function status(){
  const [l,r]=shown(), first=l||r;
  pgIn.value=label(first); ofEl.textContent=labels&&label(first)!==String(first)?"("+first+" of "+N+")":"of "+N;
  run.textContent=runningTitle(r&&r<=N?r:first);
  $("ebkPrev").disabled=first<=1; $("ebkNext").disabled=(two?(r||0):cur)>=N;
  const mk=$("ebkMark"); if(mk) mk.style.left="calc("+(100*(first-1)/Math.max(1,N-1))+"% - 1.5px)";
  $$(".ebk-toc button.it").forEach(b=>b.setAttribute("aria-current",String(+b.dataset.p===first||+b.dataset.p===r)));
  store.set("ebk.page",String(first));
  if(location.hash.startsWith("#report")) history.replaceState(null,"","#report/"+first);
}
const $$=s=>Array.from(root.querySelectorAll(s));

/* ---------------------------------------------------------------- turning */
function leaf(side,front,back){
  const el=document.createElement("div"); el.className="ebk-leaf";
  el.style.width=pw+"px"; el.style.height=ph+"px"; el.style.left=(side==="r"&&two?pw:0)+"px";
  el.style.transformOrigin=side==="r"?"left center":"right center"; el.style.setProperty("--ebk-t",TURN+"ms");
  for(const [cls,c] of [["front",front],["back",back]]){const f=document.createElement("div"); f.className="ebk-face "+cls;
    const cv=document.createElement("canvas"); f.appendChild(cv); if(c){cv.width=c.width; cv.height=c.height; cv.getContext("2d").drawImage(c,0,0);} el.appendChild(f);}
  book.appendChild(el); return el;
}
function spin(el,from,to){
  return new Promise(ok=>{
    if(!TURN){ok(); return;}
    const a=el.animate([{transform:"rotateY("+from+"deg)"},{transform:"rotateY("+to+"deg)"}],{duration:TURN,easing:"cubic-bezier(.45,.05,.3,1)",fill:"forwards"});
    a.onfinish=ok; a.oncancel=ok;
  });
}
async function turn(dir){
  if(busy||!pdf) return; busy=true;
  try{
    if(two){
      const [l,r]=shown(), target=dir>0?r+1:Math.max(1,l-1);
      if((dir>0&&r>=N)||(dir<0&&(!l||l<=1&&r<=1))){busy=false; return;}
      const [tl,tr]=spreadOf(target);
      if(dir>0){
        const front=await render(r), back=await render(tl), el=leaf("r",front,back);
        await show(R,tr<=N?tr:N+1); cur=target; await spin(el,0,-180); await show(L,tl); el.remove();
      }else{
        const front=await render(l), back=await render(tr), el=leaf("l",front,back);
        await show(L,tl); cur=target; await spin(el,0,180); await show(R,tr); el.remove();
      }
    }else{
      const next=cur+dir; if(next<1||next>N){busy=false; return;}
      if(dir>0){ const front=await render(cur), el=leaf("r",front,null); await show(R,next); cur=next; await spin(el,0,-180); el.remove(); }
      else{ const front=await render(next), el=leaf("r",front,null); cur=next; await spin(el,-180,0); await show(R,next); el.remove(); }
    }
    status();
    prefetch();
  }finally{busy=false;}
}
function prefetch(){const [l,r]=shown(), base=r||l||cur; [base+1,base+2,base+3,(l||base)-1,(l||base)-2].forEach(p=>{if(p>=1&&p<=N) render(p).catch(()=>{});});}
async function jump(p){ if(!pdf||!p) return; cur=Math.min(Math.max(1,p),N); await paint(); prefetch(); }

/* ---------------------------------------------------------------- open and close */
async function open(page){
  if(root.hidden){opener=document.activeElement; prevHash=location.hash.startsWith("#report")?"":location.hash;}
  root.hidden=false; document.documentElement.style.overflow="hidden"; $("ebkClose").focus();
  try{
    msg.hidden=false; msg.textContent="Opening the report…";
    await load(); msg.hidden=true; layout();
    const saved=parseInt(store.get("ebk.page")||"",10);   // the ribbon: reopen where the reader stopped
    await jump(page||(saved>=1&&saved<=N?saved:1));
    if(!location.hash.startsWith("#report")) history.replaceState(null,"","#report/"+cur);
  }catch(e){msg.hidden=false; msg.textContent="The reader could not load its PDF engine. Check the connection and open the report again.";}
}
function close(){
  root.hidden=true; toc.hidden=true; tocBtn.setAttribute("aria-expanded","false"); document.documentElement.style.overflow="";
  history.replaceState(null,"",prevHash||location.pathname+location.search);
  if(opener&&opener.focus) opener.focus();
}
function hashPage(h){const m=(h===undefined?location.hash:h).match(/^#report(?:\/(\d+))?$/); return m?(m[1]?+m[1]:0):null;}

/* ---------------------------------------------------------------- the Atlas: header button, rail entry, help, key */
const ICON='<svg width="15" height="15" viewBox="0 0 16 16" aria-hidden="true"><path d="M2 3.2c2.1-.9 4.1-.8 6 .6 1.9-1.4 3.9-1.5 6-.6v9.6c-2.1-.9-4.1-.8-6 .6-1.9-1.4-3.9-1.5-6-.6z" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/><path d="M8 3.8v9.6" stroke="currentColor" stroke-width="1.3"/></svg>';
function hookAtlas(){
  const help=document.getElementById("helpBtn");
  if(help&&!document.getElementById("ebkOpen")){
    const b=document.createElement("button"); b.type="button"; b.className="tb"; b.id="ebkOpen"; b.dataset.ebk="";
    b.title="Technical report (r)"; b.innerHTML=ICON+'<span class="lbl">Report</span>'; help.parentNode.insertBefore(b,help);
  }
  const dl=document.querySelector("#help dl");
  if(dl&&!dl.querySelector("[data-ebk-help]")){dl.insertAdjacentHTML("beforeend",'<dt data-ebk-help><kbd>r</kbd></dt><dd>technical report, as a book</dd>');}
  const rail=document.getElementById("rail");
  const addRail=()=>{ if(!rail||rail.querySelector("[data-ebk]")) return; const last=Array.from(rail.querySelectorAll(".vi.gl")).pop(); if(!last) return;
    last.insertAdjacentHTML("afterend",'<button class="vi gl" type="button" data-ebk><span class="ic">'+ICON+'</span><span>Technical report</span></button>'); };
  addRail(); if(rail) new MutationObserver(addRail).observe(rail,{childList:true});
}

document.addEventListener("click",e=>{
  const o=e.target.closest("[data-ebk]"); if(o){e.preventDefault(); e.stopPropagation(); open(0); return;}
  if(root.hidden) return;
  const a=e.target.closest(".ebk-lnk a"); if(a&&a.dataset.dest){e.preventDefault(); destPage(JSON.parse(a.dataset.dest)).then(jump); return;}
  const t=e.target.closest("[data-p]"); if(t&&root.contains(t)){e.preventDefault(); jump(+t.dataset.p); if(t.closest(".ebk-toc")){toc.hidden=true; tocBtn.setAttribute("aria-expanded","false");} return;}
},true);
$("ebkClose").addEventListener("click",close);
$("ebkPrev").addEventListener("click",()=>turn(-1));
$("ebkNext").addEventListener("click",()=>turn(1));
tocBtn.addEventListener("click",()=>{toc.hidden=!toc.hidden; tocBtn.setAttribute("aria-expanded",String(!toc.hidden));});
pgIn.addEventListener("change",()=>{const p=pageOfLabel(pgIn.value); if(p) jump(p); else status();});
pgIn.addEventListener("keydown",e=>{if(e.key==="Enter"){e.preventDefault(); pgIn.blur();}});
edge.addEventListener("click",e=>{ if(e.target.closest("[data-p]")) return; const r=edge.getBoundingClientRect();
  jump(Math.round(1+(N-1)*(e.clientX-r.left)/r.width)); });
// clicking the outer half of a page turns it; a link on the page takes precedence
book.addEventListener("click",e=>{ if(swiped){swiped=false; return;} if(e.target.closest(".ebk-lnk a")) return; const r=book.getBoundingClientRect();
  turn(e.clientX>r.left+r.width/2?1:-1); });
let sx=null, swiped=false;
stage.addEventListener("pointerdown",e=>{sx=e.clientX; swiped=false;});
stage.addEventListener("pointerup",e=>{ if(sx===null) return; const dx=e.clientX-sx; sx=null; if(Math.abs(dx)>50){swiped=true; turn(dx<0?1:-1);} });

window.addEventListener("keydown",e=>{
  const typing=/^(INPUT|TEXTAREA|SELECT)$/.test((e.target&&e.target.tagName)||"")||(e.target&&e.target.isContentEditable);
  if(root.hidden){
    if(!typing&&!e.metaKey&&!e.ctrlKey&&!e.altKey&&e.key==="r"){e.preventDefault(); e.stopPropagation(); open(0);}
    return;
  }
  e.stopPropagation();     // the Atlas's own shortcuts stay quiet while the book is open
  if(typing&&e.key!=="Escape") return;
  const k=e.key;
  if(k==="Escape"){e.preventDefault(); if(!toc.hidden){toc.hidden=true; tocBtn.setAttribute("aria-expanded","false");} else close();}
  else if(k==="ArrowRight"||k==="PageDown"||k===" "){e.preventDefault(); turn(1);}
  else if(k==="ArrowLeft"||k==="PageUp"){e.preventDefault(); turn(-1);}
  else if(k==="Home"){e.preventDefault(); jump(1);}
  else if(k==="End"){e.preventDefault(); jump(N);}
  else if(k==="c"){e.preventDefault(); tocBtn.click();}
},true);
let rt=null; window.addEventListener("resize",()=>{ if(root.hidden||!pdf) return; clearTimeout(rt); rt=setTimeout(()=>{cache.clear(); layout(); paint();},150); });
window.addEventListener("hashchange",()=>{const p=hashPage(); if(p!==null&&root.hidden) open(p);});

hookAtlas();
const hp=hashPage(window.__ebkHash||location.hash); if(hp!==null) open(hp);
})();
