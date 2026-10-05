/* ================================================================ decision board (shared db, local fallback) */
let dbH=null, userH=null, mode="local", decState={}, uid=null, readOnly=false, bdFilter="all";
const writing={};
function loadLocal(){try{decState=JSON.parse(store.get("grain.decisions")||"{}")}catch(e){decState={}}}
function saveLocal(){store.set("grain.decisions",JSON.stringify(decState));}
function decCard(d,ctx){
  const st=decState[d.id]||{}, nm="d-"+ctx+"-"+d.id;
  return '<article class="dec" data-dec="'+d.id+'"><header><h4>'+esc(d.title)+'</h4><span class="meta">'+esc(d.due)+'</span><span class="gtags">'+(DGRAIN[d.id]||[]).map(g=>'<span class="pill p-acc">'+g+'</span>').join("")+'</span></header>'+
    '<p class="small" style="margin:.4rem 0 0">'+esc(d.ev)+'</p><div class="opts" role="radiogroup" aria-label="'+esc(d.title)+'">'+
    d.opts.map(o=>'<label class="opt'+(st.choice===o[0]?" sel":"")+'"><input type="radio" name="'+nm+'" data-did="'+d.id+'" value="'+o[0]+'"'+(st.choice===o[0]?" checked":"")+(readOnly?" disabled":"")+'><div><b>'+esc(o[1])+(o[3]?'<span class="rec">recommended</span>':'')+'</b><span>'+esc(o[2])+'</span></div></label>').join("")+
    '</div><label class="f">your note<textarea data-note="'+d.id+'" data-ctx="'+ctx+'"'+(readOnly?" disabled":"")+'></textarea></label>'+
    '<div class="row" style="margin-top:.5rem"><button class="btn" type="button" data-savenote="'+d.id+'" data-ctx="'+ctx+'"'+(readOnly?" disabled":"")+'>Save note</button>'+
    (st.choice?'<button class="btn" type="button" data-clear="'+d.id+'"'+(readOnly?" disabled":"")+'>Clear decision</button>':'')+'</div>'+
    '<div class="dstate" data-dstate="'+d.id+'"></div></article>';
}
function renderDecLists(){
  const focused=document.activeElement&&document.activeElement.dataset&&document.activeElement.dataset.note?{id:document.activeElement.dataset.note,ctx:document.activeElement.dataset.ctx,val:document.activeElement.value}:null;
  $$("[data-declist]").forEach(box=>{
    const ctx=box.dataset.declist; let list=DECISIONS;
    if(ctx==="board"){ if(bdFilter==="open") list=DECISIONS.filter(d=>!(decState[d.id]||{}).choice); else if(bdFilter!=="all") list=DECISIONS.filter(d=>(DGRAIN[d.id]||[]).includes(bdFilter)); }
    else list=DECISIONS.filter(d=>(DGRAIN[d.id]||[]).includes(ctx));
    box.innerHTML=list.map(d=>decCard(d,ctx)).join("")||'<p class="small">Every decision in this view is made.</p>';
    list.forEach(d=>{const ta=$('[data-note="'+d.id+'"][data-ctx="'+ctx+'"]',box); if(ta) ta.value=(decState[d.id]||{}).note||"";});
  });
  $$("[data-dstate]").forEach(el=>paintStamp(el));
  $$("[data-decsum]").forEach(el=>{const l=DECISIONS.filter(d=>(DGRAIN[d.id]||[]).includes(el.dataset.decsum)), n=l.filter(d=>(decState[d.id]||{}).choice).length;
    el.innerHTML='<div class="kpis"><div class="kpi ok"><b>'+n+'</b><span>decided</span></div><div class="kpi '+(l.length-n?"warn":"ok")+'"><b>'+(l.length-n)+'</b><span>still open</span></div><div class="kpi"><b>'+l.filter(d=>{const st=decState[d.id]||{}, rec=(d.opts.find(o=>o[3])||[])[0]; return st.choice&&st.choice===rec;}).length+'</b><span>followed the recommendation</span></div><div class="kpi"><b>'+l.filter(d=>(decState[d.id]||{}).note).length+'</b><span>with a note</span></div></div>';});
  if(focused){const ta=$('[data-note="'+focused.id+'"][data-ctx="'+focused.ctx+'"]'); if(ta){ta.value=focused.val; ta.focus();}}
  paintSummary();
}
async function paintStamp(el){
  const st=decState[el.dataset.dstate];
  if(!st||(!st.choice&&!st.note)){el.textContent="Open."; return;}
  let who="";
  if(st.by&&userH){try{const ps=await userH.profiles([st.by]); who=(ps[st.by]&&ps[st.by].name)||"someone";}catch(e){who="someone";}}
  const when=st.at?new Date(st.at).toLocaleString():"";
  el.textContent=(st.choice?"Decided":"Note saved")+(who?" by "+who:"")+(when?" · "+when:"")+(mode==="local"?" · this browser only":" · shared");
}
function paintSummary(){
  const n=DECISIONS.filter(d=>(decState[d.id]||{}).choice).length, open=DECISIONS.filter(d=>!(decState[d.id]||{}).choice);
  const s=$("#decSummary"); if(s) s.innerHTML="<b>"+n+" of "+DECISIONS.length+" decided.</b> "+(open.length?"Still open: "+open.slice(0,5).map(d=>esc(d.title)).join(" · ")+(open.length>5?" · …":""):"All decided.");
  const k=$("#msDec"); if(k) k.innerHTML='<b>'+n+' / '+DECISIONS.length+'</b><span>decisions recorded on the board</span>';
}
async function writeDec(id,patch){
  const next=Object.assign({},decState[id]||{},patch,{at:new Date().toISOString()});
  if(uid) next.by=uid;
  decState[id]=next; renderDecLists();
  if(mode==="local"){saveLocal(); return;}
  const prev=writing[id]||Promise.resolve();
  writing[id]=prev.then(()=>dbH.doc("decisions/"+id).set({choice:next.choice||null,note:next.note||"",by:next.by||null,at:next.at})).catch(err=>{
    const m=$("#decMode");
    if(err&&(err.code==="not_granted"||err.code==="invalid_argument"||err.code==="permission_denied")){readOnly=true; if(m){m.className="banner warn"; m.textContent="You can read the board but not change it.";} renderDecLists();}
    else if(err&&err.code==="unavailable"){setTimeout(()=>writeDec(id,{}),800+Math.random()*800);}
    else if(m){m.className="banner warn"; m.textContent="Could not save ("+((err&&err.code)||"error")+"). Your choice is shown but not stored.";}
  });
}
document.addEventListener("change",e=>{const r=e.target; if(r.type==="radio"&&r.dataset.did){writeDec(r.dataset.did,{choice:r.value});}});
document.addEventListener("click",e=>{
  const b=e.target.closest("[data-savenote]"); if(b){const id=b.dataset.savenote; const ta=$('[data-note="'+id+'"][data-ctx="'+b.dataset.ctx+'"]'); writeDec(id,{note:(ta?ta.value:"").slice(0,4000)}); toast("Note saved");}
  const c=e.target.closest("[data-clear]"); if(c){writeDec(c.dataset.clear,{choice:null});}
  const f=e.target.closest("#bdFilter [data-v]"); if(f){bdFilter=f.dataset.v; $$("#bdFilter button").forEach(x=>x.setAttribute("aria-pressed",String(x===f))); renderDecLists();}
});
async function initDecisions(){
  loadLocal(); renderDecLists();
  const setMode=(cls,txt)=>{const m=$("#decMode"); if(m){m.className="banner"+(cls?" "+cls:""); m.textContent=txt;}};
  setMode("","Saved in this browser only, until the shared board connects.");
  try{
    const c=window.claude; if(!c||!c.use) throw 0;
    const [db,user]=await Promise.all([c.use("db"),c.use("user")]);
    userH=user; if(!db) throw 0;
    dbH=db; mode="shared"; uid=user?await user.id():null;
    const can=user?await user.can("data.write"):null; if(can===false) readOnly=true;
    setMode(readOnly?"warn":"",readOnly?"Shared board, read-only for you.":"Shared board: decisions are saved for everyone who opens this atlas, and Claude can read them in a later session.");
    db.collection("decisions").onSnapshot(snap=>{
      const s={}; snap.docs.forEach(d=>{const v=d.data(); if(v) s[d.id]={choice:v.choice||null,note:typeof v.note==="string"?v.note:"",by:v.by||null,at:v.at||null};});
      decState=s; renderDecLists();
    },err=>setMode("warn","Live updates stopped ("+(err&&err.code)+"). Reload to reconnect."));
  }catch(e){mode="local"; setMode("","Shared storage is not available here, so decisions are saved in this browser only.");}
}
