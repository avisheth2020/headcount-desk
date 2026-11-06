// Small behaviours. Everything important works without this file.

// "Try this" card: remember that it was dismissed.
document.addEventListener("click", (e) => {
  if (e.target.closest("[data-dismiss-try]")) {
    try { localStorage.setItem("try-dismissed", "1"); } catch (err) {}
    document.documentElement.classList.add("try-dismissed");
  }
  // Close the role menu and search results when clicking elsewhere.
  const menu = document.querySelector(".role-switch[open]");
  if (menu && !e.target.closest(".role-switch")) menu.removeAttribute("open");
  if (!e.target.closest(".search")) { const r = document.getElementById("search-results"); if (r) r.innerHTML = ""; }
});

// Keyboard: "/" focuses search, Escape closes menus, Enter approves a focused request card.
document.addEventListener("keydown", (e) => {
  const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName);
  if (e.key === "/" && !typing) {
    const q = document.getElementById("q");
    if (q && q.offsetParent) { e.preventDefault(); q.focus(); }
  }
  if (e.key === "Escape") {
    document.querySelector(".role-switch[open]")?.removeAttribute("open");
    const r = document.getElementById("search-results"); if (r) r.innerHTML = "";
  }
  if (e.key === "Enter" && document.activeElement.matches?.(".req-card[tabindex]")) {
    document.activeElement.querySelector("[data-approve]")?.click();
  }
});

// Toasts. The server asks for one with an HX-Trigger header: {"toast": {"message": "...", "undo": "/url"}}
document.body.addEventListener("toast", (e) => {
  const { message, undo, target } = e.detail;
  const box = document.getElementById("toasts");
  const toast = document.createElement("div");
  toast.className = "toast";
  toast.setAttribute("role", "status");
  toast.append(message);
  if (undo) {
    const btn = document.createElement("button");
    btn.textContent = "Undo";
    btn.addEventListener("click", () => {
      htmx.ajax("POST", undo, { target: target, swap: "outerHTML" });
      toast.remove();
    });
    toast.append(btn);
  }
  box.replaceChildren(toast);
  setTimeout(() => toast.remove(), 6000);
});

// After an inline action (approve, reject, resolve), move keyboard focus to the
// next item instead of dropping it back to the top of the page.
document.body.addEventListener("htmx:afterSwap", (e) => {
  const swapped = e.detail.target;
  if (!swapped || !swapped.id) return;
  const fresh = document.getElementById(swapped.id);
  if (!fresh) return;
  if (fresh.matches(".req-card")) {
    (document.querySelector(".req-card[tabindex]") || fresh.querySelector("a"))?.focus({ preventScroll: true });
  } else if (fresh.matches(".todo li")) {
    fresh.querySelector("button")?.focus({ preventScroll: true });
  }
});
