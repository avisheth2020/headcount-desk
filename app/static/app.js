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
  const menu = $(".role-switch[open]");
  if (menu && !t.closest(".role-switch")) menu.removeAttribute("open");
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
    $(".role-switch[open]")?.removeAttribute("open");
  }
  if (document.body.classList.contains("palette-open")) {
    if (e.key === "ArrowDown") { e.preventDefault(); movePalette(1); }
    if (e.key === "ArrowUp") { e.preventDefault(); movePalette(-1); }
    if (e.key === "Enter") { e.preventDefault(); $("#palette-results .palette-item.active")?.click(); }
    return;
  }
  if (e.key === "Enter" && document.activeElement.matches?.(".req-card[tabindex]")) {
    document.activeElement.querySelector("[data-approve]")?.click();
  }
});

// ── HTMX hooks ───────────────────────────────────────────────────────────────
document.body.addEventListener("htmx:configRequest", (e) => { e.detail.headers["X-CSRF-Token"] = csrf(); });

// Optimistic update: show the result at once, then let the server confirm it.
document.body.addEventListener("htmx:beforeRequest", (e) => {
  e.detail.elt.closest?.("[data-optimistic]")?.classList.add("optimistic");
});
document.body.addEventListener("htmx:responseError", (e) => {
  e.detail.elt.closest?.("[data-optimistic]")?.classList.remove("optimistic");
  let message = "That didn't work. Try again.";
  try { message = JSON.parse(e.detail.xhr.responseText).detail || message; } catch (err) {}
  showToast({ message });
});

document.body.addEventListener("htmx:afterSwap", (e) => {
  const target = e.detail.target;
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

// ── Deep link: /requests#d=/positions/12 opens that position in the drawer. ──
const openFromHash = () => {
  if (location.hash.startsWith("#d=/")) openDrawer(decodeURIComponent(location.hash.slice(3)), false);
  else closeDrawer();
};
window.addEventListener("hashchange", openFromHash);
if (location.hash.startsWith("#d=/")) openFromHash();
