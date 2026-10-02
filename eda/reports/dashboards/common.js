/* Shared helpers: tooltip (textContent only), table view, theme toggle, formatting. */
const fmtInt = d3.format(",d"), fmtPct = (v, d = 1) => (100 * v).toFixed(d) + " %";
const css = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();

const tipEl = (() => { const el = document.createElement("div"); el.className = "tt"; el.setAttribute("role", "tooltip"); document.body.appendChild(el); return el; })();
/** rows: [{key:cssColor|null, label, value}], title: string. Everything inserted with textContent. */
function showTip(evt, title, rows) {
  tipEl.replaceChildren();
  const t = document.createElement("div"); t.className = "t"; t.textContent = title; tipEl.appendChild(t);
  for (const r of rows) {
    const row = document.createElement("div"); row.className = "row";
    const l = document.createElement("span");
    if (r.key) { const k = document.createElement("span"); k.className = "key"; k.style.background = r.key; l.appendChild(k); }
    l.appendChild(document.createTextNode(r.label)); const v = document.createElement("b"); v.textContent = r.value;
    row.append(l, v); tipEl.appendChild(row);
  }
  tipEl.style.opacity = 1; moveTip(evt);
}
function moveTip(evt) {
  const pad = 14, w = tipEl.offsetWidth, h = tipEl.offsetHeight;
  let x = evt.clientX + pad, y = evt.clientY + pad;
  if (x + w > innerWidth - 8) x = evt.clientX - w - pad; if (y + h > innerHeight - 8) y = evt.clientY - h - pad;
  tipEl.style.left = x + "px"; tipEl.style.top = y + "px";
}
const hideTip = () => { tipEl.style.opacity = 0; };

/** Build an accessible table view from column spec [{h, f(row)}] */
function tableView(el, cols, rows) {
  const t = document.createElement("table"); t.className = "tv";
  const thead = t.createTHead().insertRow(); for (const c of cols) { const th = document.createElement("th"); th.textContent = c.h; thead.appendChild(th); }
  const tb = t.createTBody(); for (const r of rows) { const tr = tb.insertRow(); for (const c of cols) tr.insertCell().textContent = c.f(r); }
  el.replaceChildren(t);
}
/** Chart | Table toggle for a card: chartEl and tableEl are the two panes */
function viewToggle(host, chartEl, tableEl) {
  const seg = document.createElement("div"); seg.className = "seg";
  const mk = (txt, on) => { const b = document.createElement("button"); b.textContent = txt; b.setAttribute("aria-pressed", on); return b; };
  const a = mk("Chart", true), b = mk("Table", false);
  const set = (chart) => { a.setAttribute("aria-pressed", chart); b.setAttribute("aria-pressed", !chart); chartEl.hidden = !chart; tableEl.hidden = chart; };
  a.onclick = () => set(true); b.onclick = () => set(false); seg.append(a, b); host.appendChild(seg); tableEl.hidden = true;
}
function themeToggle(host, redraw) {
  const b = document.createElement("button"); b.textContent = "◐ Theme"; b.title = "Toggle light / dark";
  b.onclick = () => { const cur = document.documentElement.dataset.theme || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    document.documentElement.dataset.theme = cur === "dark" ? "light" : "dark"; setTimeout(redraw, 30); };
  host.appendChild(b);
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => setTimeout(redraw, 30));
}
function legend(host, items) {
  host.replaceChildren(); host.className = "legend";
  for (const it of items) { const s = document.createElement("span"); const i = document.createElement("i"); i.style.background = it.color; if (it.line) i.className = "line"; s.append(i, document.createTextNode(it.label)); host.appendChild(s); }
}
function debounceResize(fn) { let t; addEventListener("resize", () => { clearTimeout(t); t = setTimeout(fn, 120); }); }
