/* Static (GitHub Pages) demo helper: explains read-only actions and keeps navigation inside the snapshot. */
(function () {
  "use strict";
  var D = window.HOTELI_DEMO;
  if (!D) return;
  var pages = new Set(D.pages || []);

  function norm(pathname) {
    var p = pathname;
    if (D.base !== "/" && p.indexOf(D.base) === 0) p = "/" + p.slice(D.base.length);
    p = p.replace(/index\.html$/, "");
    if (p.slice(-1) !== "/") p += "/";
    return p;
  }

  function inSnapshot(url) {
    var u = new URL(url, location.href);
    if (u.origin !== location.origin) return true;
    if (u.pathname.indexOf(D.base + "static/") === 0) return true;
    return pages.has(norm(u.pathname));
  }

  function explain(path) {
    if (/\/(pay|mpesa\/stk)\//.test(path) || path.indexOf("/pay/") >= 0) {
      return "Sending an M-Pesa payment prompt needs the live demo. There, a simulated prompt lets you choose what the customer does: pay, cancel, enter a wrong PIN…";
    }
    if (/^\/book\/\d+\/$/.test(path)) return "In the live demo this reserves a room and takes you to the M-Pesa deposit step.";
    if (path.indexOf("/check-in/") >= 0 || path.indexOf("/check-out/") >= 0) return "Checking guests in and out works in the live demo – it posts room charges and sends the room to housekeeping.";
    if (path.indexOf("/staff/logout/") === 0) return "This preview is always signed in as the demo administrator.";
    return "This preview is read-only, so saving changes is switched off. Everything works in the live demo.";
  }

  var modal;
  function show(message) {
    if (!modal) {
      modal = document.createElement("div");
      modal.setAttribute("role", "dialog");
      modal.style.cssText = "position:fixed;inset:0;background:rgba(15,23,42,.55);display:flex;align-items:center;justify-content:center;z-index:5000;padding:16px;font-family:Inter,system-ui,sans-serif";
      modal.innerHTML =
        '<div style="background:#fff;color:#0f172a;max-width:460px;width:100%;border-radius:14px;padding:22px;box-shadow:0 20px 50px rgba(0,0,0,.3)">' +
        '<div style="font-weight:700;font-size:18px;margin-bottom:6px">Static preview</div>' +
        '<p data-msg style="margin:0 0 16px;color:#475569;font-size:15px;line-height:1.5"></p>' +
        '<div style="display:flex;flex-wrap:wrap;gap:8px;justify-content:flex-end">' +
        (D.live ? '<a href="' + D.live + '" target="_blank" rel="noopener" style="background:#16a34a;color:#fff;padding:8px 14px;border-radius:8px;text-decoration:none;font-weight:600">▶ Launch the live demo</a>' : "") +
        '<a href="' + D.base + 'demo/" style="padding:8px 14px;border-radius:8px;text-decoration:none;border:1px solid #cbd5e1;color:#0f172a">Demo guide</a>' +
        '<button type="button" data-close style="padding:8px 14px;border-radius:8px;border:none;background:#e2e8f0;cursor:pointer">Close</button>' +
        "</div></div>";
      modal.addEventListener("click", function (e) {
        if (e.target === modal || e.target.hasAttribute("data-close")) modal.style.display = "none";
      });
      document.body.appendChild(modal);
    }
    modal.querySelector("[data-msg]").textContent = message;
    modal.style.display = "flex";
  }

  function handleForm(form) {
    var action = new URL(form.getAttribute("action") || location.href, location.href);
    var path = norm(action.pathname);
    var method = (form.getAttribute("method") || "get").toLowerCase();
    if (path === "/staff/login/") { location.href = D.staff; return; }
    if (method === "get" && path === "/book/") { location.href = D.book; return; }
    if (method === "get" && pages.has(path)) { location.href = D.base + path.slice(1); return; }
    show(explain(path));
  }

  document.addEventListener("submit", function (e) {
    e.preventDefault();
    e.stopPropagation();
    handleForm(e.target);
  }, true);
  HTMLFormElement.prototype.submit = function () { handleForm(this); };
  // Skip the browser's required-field checks: nothing is saved here, the demo dialog explains instead.
  function relax() { document.querySelectorAll("form").forEach(function (f) { f.noValidate = true; }); }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", relax); else relax();

  document.addEventListener("click", function (e) {
    var a = e.target.closest && e.target.closest("a[href]");
    if (!a) return;
    var href = a.getAttribute("href");
    if (!href || href[0] === "#" || /^(mailto:|tel:|javascript:)/i.test(href)) return;
    if (!inSnapshot(a.href)) {
      e.preventDefault();
      show("That screen isn't part of the static preview. Explore it in the live demo.");
    }
  }, true);
})();
