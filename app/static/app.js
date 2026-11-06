// Behaviour for Headcount Desk. No inline scripts anywhere (the CSP forbids them),
// so everything is wired up here by data attributes.

const $ = (sel, root = document) => root.querySelector(sel);
const csrf = () => $('meta[name="csrf-token"]')?.content || "";
let lastFocus = null;

// ── Theme ────────────────────────────────────────────────────────────────────
function toggleTheme() {
  const next = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
  document.documentElement.setAttribute("data-theme", next);
  try { localStorage.setItem("theme", next); } catch (e) {}
}

// ── Tour: a small guide. Progress is remembered in this browser only. ───────
function tourDone() { try { return JSON.parse(localStorage.getItem("tour") || "[]"); } catch (e) { return []; } }
function drawTour() {
  const done = tourDone(), tour = $(".tour");
  if (!tour) return;
  document.querySelectorAll("[data-tour-step]").forEach((a) => a.closest("li").classList.toggle("done", done.includes(a.dataset.tourStep)));
  tour.classList.toggle("started", done.length > 0);
  $("[data-tour-label]").textContent = done.length === 0 ? "Take the tour" : done.length < 4 ? `Tour ${done.length} of 4` : "Tour done";
}
function markTour(step) {
  const done = tourDone();
  if (!done.includes(step)) done.push(step);
  try { localStorage.setItem("tour", JSON.stringify(done)); } catch (e) {}
  drawTour();
}
drawTour();

// ── Drawer: detail without losing your place. Deep-linkable through the hash. ──
function openDrawer(href, push = true) {
  if (!href.startsWith("/") || href.startsWith("//")) return;
  if (!document.body.classList.contains("drawer-open")) lastFocus = document.activeElement;
  const body = $("#drawer-body");
  body.innerHTML = '<div class="skeleton-rows"><div class="skeleton"></div><div class="skeleton"></div><div class="skeleton"></div></div>';
  document.body.classList.add("drawer-open");
  $("#drawer").setAttribute("aria-hidden", "false");
  $("#drawer-full").setAttribute("href", href);
  htmx.ajax("GET", href + (href.includes("?") ? "&" : "?") + "partial=1", { target: "#drawer-body", swap: "innerHTML" });
  if (push) history.replaceState(null, "", "#d=" + href);
  $("#drawer-close").focus({ preventScroll: true });
}
function closeDrawer() {
  if (!document.body.classList.contains("drawer-open")) return;
  document.body.classList.remove("drawer-open");
  $("#drawer").setAttribute("aria-hidden", "true");
  history.replaceState(null, "", location.pathname + location.search);
  lastFocus?.focus?.({ preventScroll: true });
}

// ── Command palette ──────────────────────────────────────────────────────────
function openPalette() {
  closeDrawer();
  lastFocus = document.activeElement;
  document.body.classList.add("palette-open");
  const input = $("#palette-input");
  input.value = "";
  htmx.ajax("GET", "/palette", { target: "#palette-results", swap: "innerHTML" });
  input.focus();
}
function closePalette() {
  if (!document.body.classList.contains("palette-open")) return;
  document.body.classList.remove("palette-open");
  lastFocus?.focus?.({ preventScroll: true });
}
function movePalette(step) {
  const items = [...document.querySelectorAll("#palette-results .palette-item")];
  if (!items.length) return;
  const at = items.findIndex((el) => el.classList.contains("active"));
  items.forEach((el) => el.classList.remove("active"));
  const next = items[(at + step + items.length) % items.length];
  next.classList.add("active");
  next.scrollIntoView({ block: "nearest" });
}

// ── Clicks ───────────────────────────────────────────────────────────────────
document.addEventListener("click", (e) => {
  const t = e.target;
  if (t.closest("[data-theme-toggle]")) return toggleTheme();
  if (t.closest("[data-palette-open]")) { e.preventDefault(); return openPalette(); }
  if (t.closest("[data-close]")) { closePalette(); return closeDrawer(); }
  if (t.closest("[data-dismiss-try]")) {
    try { localStorage.setItem("try-dismissed", "1"); } catch (err) {}
    return document.documentElement.classList.add("try-dismissed");
  }
  const step = t.closest("[data-tour-step]");
  if (step) markTour(step.dataset.tourStep);
  const toggle = t.closest("[data-toggle]");            // show or hide another element, e.g. the reject reason
  if (toggle) {
    const target = toggle.closest(toggle.dataset.within || "body").querySelector(toggle.dataset.toggle);
    target.hidden = !target.hidden;
    if (!target.hidden) target.querySelector("input, textarea")?.focus();
    return;
  }
  const tree = t.closest(".tree-toggle");                // org explorer: collapse an expanded branch
  if (tree && tree.getAttribute("aria-expanded") === "true") {
    e.preventDefault(); e.stopPropagation();
    const row = tree.closest("tr"), depth = +row.dataset.depth;
    for (let next = row.nextElementSibling; next && +next.dataset.depth > depth;) { const gone = next; next = next.nextElementSibling; gone.remove(); }
    tree.setAttribute("aria-expanded", "false");
    return;
  }
  const link = t.closest("a[data-drawer]");
  if (link && !(e.metaKey || e.ctrlKey || e.shiftKey || e.button)) {
    e.preventDefault();
    closePalette();
    return openDrawer(link.getAttribute("href"));
  }
  if (t.closest(".palette-item")) closePalette();
  document.querySelectorAll("details.popover[open]").forEach((d) => { if (!d.contains(t)) d.removeAttribute("open"); });
  const more = $(".tabbar details[open]");
  if (more && !t.closest(".tabbar details")) more.removeAttribute("open");
}, true);

// ── Keyboard ─────────────────────────────────────────────────────────────────
document.addEventListener("keydown", (e) => {
  const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName);
  if ((e.key === "k" && (e.metaKey || e.ctrlKey)) || (e.key === "/" && !typing)) { e.preventDefault(); return openPalette(); }
  if (e.key === "Escape") {
    if (document.body.classList.contains("palette-open")) return closePalette();
    if (document.body.classList.contains("drawer-open")) return closeDrawer();
    document.querySelectorAll("details.popover[open]").forEach((d) => d.removeAttribute("open"));
  }
  if (document.body.classList.contains("palette-open")) {
    if (e.key === "ArrowDown") { e.preventDefault(); movePalette(1); }
    if (e.key === "ArrowUp") { e.preventDefault(); movePalette(-1); }
    if (e.key === "Enter") { e.preventDefault(); $("#palette-results .palette-item.active")?.click(); }
    return;
  }
  // The queue: J and K move, A approves, R rejects.
  if (typing || e.metaKey || e.ctrlKey || e.altKey || document.body.classList.contains("drawer-open")) return;
  const cards = [...document.querySelectorAll(".req-card[tabindex]")];
  if (!cards.length) return;
  const at = cards.indexOf(document.activeElement);
  if (e.key === "j" || e.key === "k") {
    e.preventDefault();
    const next = e.key === "j" ? Math.min(at + 1, cards.length - 1) : Math.max(at - 1, 0);
    cards[next].focus();
  } else if (at >= 0 && e.key === "a") document.activeElement.querySelector("[data-approve]")?.click();
  else if (at >= 0 && e.key === "r") { e.preventDefault(); document.activeElement.querySelector("[data-reject]")?.click(); }
});

// ── HTMX hooks ───────────────────────────────────────────────────────────────
document.body.addEventListener("htmx:configRequest", (e) => { e.detail.headers["X-CSRF-Token"] = csrf(); });

// Optimistic update: show the result at once, then let the server confirm it.
document.body.addEventListener("htmx:beforeRequest", (e) => {
  e.detail.elt.closest?.("[data-optimistic]")?.classList.add("optimistic");
  if (e.detail.target?.id === "main") document.documentElement.classList.add("swapping");   // show that a click landed
});
document.body.addEventListener("htmx:afterSettle", () => document.documentElement.classList.remove("swapping"));
document.body.addEventListener("htmx:sendError", () => document.documentElement.classList.remove("swapping"));
document.body.addEventListener("htmx:responseError", (e) => {
  e.detail.elt.closest?.("[data-optimistic]")?.classList.remove("optimistic");
  document.documentElement.classList.remove("swapping");
  let message = "That didn't work. Try again.";
  try { message = JSON.parse(e.detail.xhr.responseText).detail || message; } catch (err) {}
  showToast({ message });
});

document.body.addEventListener("htmx:afterSwap", (e) => {
  const target = e.detail.target;
  if (document.getElementById("forecast")) initForecast();
  if (document.getElementById("bulk-form")) countSelected();
  if (target.id === "palette-results") target.querySelector(".palette-item")?.classList.add("active");
  if (target.id === "drawer-body") {
    const title = target.querySelector("[data-drawer-title]")?.dataset.drawerTitle;
    if (title) $("#drawer-title").textContent = title;
  }
  // After an inline action, move keyboard focus to the next thing to act on.
  if (!target.id) return;
  const fresh = document.getElementById(target.id);
  if (fresh?.matches(".req-card")) (document.querySelector(".req-card[tabindex]") || fresh.querySelector("a"))?.focus({ preventScroll: true });
  else if (fresh?.matches(".todo li")) fresh.querySelector("button")?.focus({ preventScroll: true });
});

// Fired on the element that made the request (afterSwap fires on the target instead).
document.body.addEventListener("htmx:afterRequest", (e) => {
  if (!e.detail.successful) return;
  const source = e.detail.elt;
  // The org explorer loaded a branch's children under its row.
  source?.closest?.(".tree-toggle")?.setAttribute("aria-expanded", "true");
  // The backfill form: remember who was picked and clear the suggestions.
  const picked = source?.closest?.("[data-pick-name]");
  if (picked) { $("#who").value = picked.dataset.pickName; $("#who-results").innerHTML = ""; }
});

// ── Toasts. The server asks for one with an HX-Trigger header. ───────────────
function showToast({ message, undo, target }) {
  const toast = document.createElement("div");
  toast.className = "toast";
  toast.setAttribute("role", "status");
  toast.append(message);
  if (undo) {
    const btn = document.createElement("button");
    btn.textContent = "Undo";
    btn.addEventListener("click", () => {
      htmx.ajax("POST", undo, { target, swap: "outerHTML", headers: { "X-CSRF-Token": csrf() } });
      toast.remove();
    });
    toast.append(btn);
  }
  $("#toasts").replaceChildren(toast);
  setTimeout(() => toast.remove(), 6000);
}
document.body.addEventListener("toast", (e) => showToast(e.detail));

// ── One tooltip for every chart. It adds detail and never holds the only copy of a value. ──
const chartTip = document.createElement("div");
chartTip.id = "chart-tip";
chartTip.hidden = true;
document.body.append(chartTip);
function placeTip(text, x, y) {
  chartTip.textContent = text;
  chartTip.hidden = false;
  const box = chartTip.getBoundingClientRect();
  chartTip.style.left = Math.max(8, Math.min(innerWidth - box.width - 8, x + 12)) + "px";
  chartTip.style.top = Math.max(8, y - box.height - 10) + "px";
}
document.addEventListener("pointermove", (e) => {
  const hit = e.target.closest?.("[data-chart-tip]");
  if (hit) placeTip(hit.dataset.chartTip, e.clientX, e.clientY);
  else if (!e.target.closest?.("[data-chart-live]")) chartTip.hidden = true;
});
document.addEventListener("focusin", (e) => {
  const hit = e.target.closest?.("[data-chart-tip]");
  if (hit) { const box = hit.getBoundingClientRect(); placeTip(hit.dataset.chartTip, box.left, box.top); }
});
document.addEventListener("focusout", () => { chartTip.hidden = true; });

// ── Forecast: real history, then the likely range to quarter end. What-ifs stay in this browser. ──
const fmt = (n) => Math.round(n).toLocaleString("en-US");
function niceStep(span) {
  const raw = span / 4, unit = 10 ** Math.floor(Math.log10(raw)), m = raw / unit;
  return (m <= 1 ? 1 : m <= 2 ? 2 : m <= 5 ? 5 : 10) * unit;
}
function initForecast() {
  const box = document.getElementById("forecast"), svg = document.getElementById("fan");
  if (!box || !svg || box.dataset.ready) return;
  box.dataset.ready = "1";
  const d = box.dataset, history = d.history.split(",").map(Number), last = history.length - 1;
  const start = new Date(d.start + "T12:00:00"), end = new Date(d.end + "T12:00:00");
  const stop = last + Math.max(1, Math.round((end - start) / 864e5) - last);
  const seats = +d.seats, hires = +d.hires, exits = +d.exits, base = +d.projected, approved = +d.approved;
  const below = base - +d.low, above = +d.high - base;
  const field = (name) => box.querySelector(`[data-fc="${name}"]`);
  const hireInput = $("#fc-hires", box), exitInput = $("#fc-exits", box), NS = "http://www.w3.org/2000/svg";
  const make = (tag, attrs, text) => { const el = document.createElementNS(NS, tag); for (const k in attrs) el.setAttribute(k, attrs[k]); if (text !== undefined) el.textContent = text; return el; };
  const label = (i) => new Date(start.getTime() + i * 864e5).toLocaleDateString("en-US", { month: "short", day: "numeric" });
  // The scale holds still as the sliders move: it already covers both extremes.
  const extremes = [seats + hires * 0.7 - exits * 1.3 - below, seats + hires * 1.3 - exits * 0.7 + above];
  let low = Math.min(...history, ...extremes), high = Math.max(...history, ...extremes);
  const step = niceStep(Math.max(high - low, 8));
  low = Math.floor(low / step) * step; high = Math.ceil(high / step) * step;
  let state = {};
  function draw() {
    const H = svg.clientHeight || 280, W = Math.max(280, svg.clientWidth), L = 46, R = 54, T = 10, B = 26;
    const x = (i) => L + (i / stop) * (W - L - R), y = (v) => T + ((high - v) / (high - low)) * (H - T - B);
    const hp = +hireInput.value / 100, ep = +exitInput.value / 100;
    const projected = base + hires * (hp - 1) - exits * (ep - 1), lo = projected - below, hi = projected + above;
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    svg.replaceChildren();
    for (let v = low; v <= high; v += step) svg.append(make("line", { x1: L, x2: W - R, y1: y(v), y2: y(v), class: "grid" }), make("text", { x: L - 8, y: y(v) + 4, "text-anchor": "end" }, fmt(v)));
    [[0, "start"], [last, "middle"], [stop, "end"]].forEach(([i, anchor]) => svg.append(make("text", { x: x(i), y: H - 8, "text-anchor": anchor }, i === last ? "Today" : label(i))));
    if (approved >= low && approved <= high) svg.append(make("line", { x1: L, x2: W - R, y1: y(approved), y2: y(approved), class: "approved" }), make("text", { x: L + 4, y: y(approved) - 5 }, "Approved"));
    svg.append(make("path", { d: `M${x(last)} ${y(seats)} L${x(stop)} ${y(hi)} L${x(stop)} ${y(lo)} Z`, fill: "var(--accent)", "fill-opacity": 0.14 }));
    svg.append(make("path", { d: history.map((v, i) => `${i ? "L" : "M"}${x(i)} ${y(v)}`).join(" "), fill: "none", stroke: "var(--accent)", "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" }));
    svg.append(make("path", { d: `M${x(last)} ${y(seats)} L${x(stop)} ${y(projected)}`, fill: "none", stroke: "var(--accent)", "stroke-width": 2, "stroke-linecap": "round" }));
    [[last, seats], [stop, projected]].forEach(([i, v]) => svg.append(make("circle", { cx: x(i), cy: y(v), r: 4, fill: "var(--accent)", stroke: "var(--surface)", "stroke-width": 2 })));
    svg.append(make("text", { x: x(stop) + 8, y: y(projected) + 4, class: "end" }, fmt(projected)));
    const cross = make("line", { y1: T, y2: H - B, stroke: "var(--border-strong)", "stroke-width": 1, visibility: "hidden" });
    svg.append(cross);
    state = { cross, x, projected, L, R, W };
    field("projected").textContent = fmt(projected);
    field("range").textContent = `${fmt(lo)} to ${fmt(hi)}`;
    field("gap").textContent = `${fmt(Math.abs(approved - projected))} ${projected > approved ? "over" : "under"}`;
    field("hires").textContent = "+" + fmt(hires * hp);
    field("exits").textContent = "−" + fmt(exits * ep);
    field("hires-pct").textContent = hireInput.value + "%";
    field("exits-pct").textContent = exitInput.value + "%";
    const changed = hp !== 1 || ep !== 1;
    field("whatif").hidden = field("reset").hidden = !changed;
    box.classList.toggle("whatif", changed);
  }
  svg.addEventListener("pointermove", (e) => {
    const box2 = svg.getBoundingClientRect(), share = (e.clientX - box2.left - state.L) / (state.W - state.L - state.R), i = Math.max(0, Math.min(stop, Math.round(share * stop)));
    state.cross.setAttribute("x1", state.x(i)); state.cross.setAttribute("x2", state.x(i)); state.cross.setAttribute("visibility", "visible");
    if (i <= last) return placeTip(`${fmt(history[i])} people, ${label(i)}`, e.clientX, e.clientY);
    const t = (i - last) / (stop - last), mid = seats + (state.projected - seats) * t;
    placeTip(`About ${fmt(mid)} (${fmt(mid - below * t)} to ${fmt(mid + above * t)}), ${label(i)}`, e.clientX, e.clientY);
  });
  svg.addEventListener("pointerleave", () => { state.cross?.setAttribute("visibility", "hidden"); chartTip.hidden = true; });
  hireInput.addEventListener("input", draw);
  exitInput.addEventListener("input", draw);
  field("reset").addEventListener("click", () => { hireInput.value = exitInput.value = 100; draw(); });
  field("sliders").hidden = false;
  draw();
  new ResizeObserver(draw).observe(svg);
}
initForecast();

// ── Planning: dollars and room move as you change a number; the server saves and confirms. ──
const money = (n) => { const a = Math.abs(n), s = n < 0 ? "−" : "+"; return s + (a >= 1e6 ? `$${(a / 1e6).toFixed(1)}M` : `$${Math.round(a / 1e3).toLocaleString("en-US")}K`); };
const signed = (n) => (n > 0 ? "+" : n < 0 ? "−" : "") + Math.abs(n).toLocaleString("en-US");
function previewPlan(form) {
  let change = 0, cost = 0, next = 0;
  form.querySelectorAll("[data-plan-line]").forEach((row) => {
    const input = row.querySelector("input[name^='approved_']") || row.querySelector("input[name^='change_']");
    const base = +row.dataset.base, value = input ? parseInt(input.value, 10) || 0 : parseInt(row.querySelector("[data-next]").textContent.replace(/,/g, ""), 10) - base;
    const dollars = value * +row.dataset.cost;
    row.querySelector("[data-next]").textContent = (base + value).toLocaleString("en-US");
    row.querySelector("[data-line-cost]").textContent = value ? money(dollars) : "$0";
    change += value; cost += dollars; next += base + value;
  });
  const room = form.querySelector(".room"), left = +room.dataset.room - +room.dataset.others - change;
  const mine = room.querySelector("[data-room-mine]");
  mine.style.flexGrow = Math.max(change, 0);
  mine.className = left < 0 ? "seg-over" : "seg-usable";
  room.querySelector("[data-room-left]").style.flexGrow = Math.max(left, 0);
  room.querySelector("[data-room-mine-text]").textContent = signed(change);
  room.querySelector("[data-room-left-text]").textContent = left < 0 ? `${-left} over the limit` : `${left} left`;
  form.querySelector("[data-total-next]").textContent = next.toLocaleString("en-US");
  form.querySelector("[data-total-delta]").textContent = `${signed(change)}, ${change ? money(cost) : "$0"}`;
}
// An autosave can come back after the person has moved on. Keep what they have since typed: the next save carries it.
const planValues = (form) => [...form.querySelectorAll("input:not([type=hidden])")].map((i) => i.value).join("|");
document.body.addEventListener("htmx:beforeRequest", (e) => { if (e.detail.target?.id === "plan-form") e.detail.target.dataset.sent = planValues(e.detail.target); });
document.body.addEventListener("htmx:beforeSwap", (e) => {
  const form = e.detail.target;
  if (form?.id === "plan-form" && planValues(form) !== form.dataset.sent) e.detail.shouldSwap = false;
});
document.addEventListener("input", (e) => { const form = e.target.closest?.("#plan-form"); if (form && e.target.type === "number") previewPlan(form); });
document.addEventListener("click", (e) => {
  const button = e.target.closest?.("[data-step]");
  if (!button) return;
  const input = button.parentElement.querySelector("input");
  input.value = Math.min(+input.max, Math.max(+input.min, (parseInt(input.value, 10) || 0) + +button.dataset.step));
  input.dispatchEvent(new Event("input", { bubbles: true }));
  input.dispatchEvent(new Event("change", { bubbles: true }));
});

// ── Exceptions: pick many, resolve together. ─────────────────────────────────
function countSelected() {
  const boxes = [...document.querySelectorAll("input[name='items']")], count = boxes.filter((box) => box.checked).length, bar = $("#bulk-form"), all = $("[data-select-all]");
  if (!bar) return;
  if (all) all.checked = boxes.length > 0 && count === boxes.length;
  bar.hidden = count === 0;
  $("[data-selected]", bar).textContent = count.toLocaleString("en-US");
}
document.addEventListener("change", (e) => {
  const all = e.target.closest?.("[data-select-all]");
  if (all) document.querySelectorAll("input[name='items']").forEach((box) => { box.checked = all.checked; });
  if (all || e.target.name === "items") countSelected();
});

// ── Deep link: /requests#d=/positions/12 opens that position in the drawer. ──
const openFromHash = () => {
  if (location.hash.startsWith("#d=/")) openDrawer(decodeURIComponent(location.hash.slice(3)), false);
  else closeDrawer();
};
window.addEventListener("hashchange", openFromHash);
if (location.hash.startsWith("#d=/")) openFromHash();
