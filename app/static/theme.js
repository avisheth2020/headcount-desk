// Runs before first paint (it is tiny and loaded without defer) so the page
// never flashes the wrong theme. The choice is remembered; otherwise follow the system.
(function () {
  var root = document.documentElement, saved = null;
  try { saved = localStorage.getItem("theme"); if (localStorage.getItem("try-dismissed")) root.classList.add("try-dismissed"); } catch (e) {}
  var dark = saved ? saved === "dark" : window.matchMedia("(prefers-color-scheme: dark)").matches;
  root.setAttribute("data-theme", dark ? "dark" : "light");
})();
