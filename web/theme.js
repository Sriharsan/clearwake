// Theme toggle shared by every page: a sun and moon icon button. Remembers the choice when the browser allows it.
(function () {
  var root = document.documentElement, key = "clearwake-theme", saved = null;
  try { saved = localStorage.getItem(key); } catch (e) {}
  if (saved === "light" || saved === "dark") root.setAttribute("data-theme", saved);
  function current() { return root.getAttribute("data-theme") || (matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark"); }
  function paint(btn) {
    var light = current() === "light";
    btn.setAttribute("aria-label", light ? "Switch to the dark theme" : "Switch to the light theme");
    btn.setAttribute("title", light ? "Switch to the dark theme" : "Switch to the light theme");
  }
  addEventListener("DOMContentLoaded", function () {
    var btn = document.querySelector(".theme"); if (!btn) return; paint(btn);
    btn.addEventListener("click", function () {
      var next = current() === "light" ? "dark" : "light"; root.setAttribute("data-theme", next);
      try { localStorage.setItem(key, next); } catch (e) {} paint(btn);
    });
  });
})();
