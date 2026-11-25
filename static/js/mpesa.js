/* Live M-Pesa STK push status widget. Markup: templates/partials/mpesa_status.html */
(function () {
  "use strict";

  function csrfToken() {
    const m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : "";
  }

  const ICONS = {
    SUCCESS: '<i class="bi bi-check-circle-fill text-success"></i>',
    FAILED: '<i class="bi bi-x-circle-fill text-danger"></i>',
    CANCELLED: '<i class="bi bi-x-circle-fill text-secondary"></i>',
    TIMEOUT: '<i class="bi bi-hourglass-bottom text-warning"></i>',
  };

  function render(el, data) {
    const title = el.querySelector(".mpesa-title");
    const msg = el.querySelector(".mpesa-message");
    const icon = el.querySelector(".mpesa-icon");
    const sim = el.querySelector(".mpesa-sim");
    if (data.error) {
      msg.textContent = data.error;
      return;
    }
    if (sim) sim.classList.toggle("d-none", !(data.simulated && data.status === "PENDING"));
    if (data.status === "PENDING") {
      title.textContent = "Waiting for M-Pesa confirmation… (" + data.phone + ", KES " + Number(data.amount).toLocaleString() + ")";
      return;
    }
    icon.innerHTML = ICONS[data.status] || "";
    if (data.success) {
      title.textContent = "Payment received" + (data.receipt ? " – " + data.receipt : "");
      msg.textContent = "Thank you! KES " + Number(data.amount).toLocaleString() + " was received via M-Pesa.";
      el.classList.add("border-success");
    } else {
      title.textContent = data.status_label;
      msg.textContent = data.message || "The payment was not completed. You can try again.";
      el.classList.add("border-danger");
    }
  }

  function finish(el, data) {
    if (data.success) {
      const target = el.dataset.successUrl || window.location.pathname;
      setTimeout(function () { window.location.href = target; }, 1800);
    } else {
      const retry = document.querySelector("[data-mpesa-retry]");
      if (retry) retry.classList.remove("d-none");
    }
  }

  function poll(el) {
    const url = el.dataset.statusUrl;
    const started = Date.now();
    function tick() {
      fetch(url, { headers: { Accept: "application/json" }, cache: "no-store" })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          render(el, data);
          if (data.final) { finish(el, data); return; }
          const elapsed = Date.now() - started;
          if (elapsed > 6 * 60 * 1000) {
            el.querySelector(".mpesa-message").textContent =
              "Still waiting. If you completed the payment it will reflect automatically – refresh this page later.";
            return;
          }
          setTimeout(tick, elapsed < 30000 ? 3000 : 6000);
        })
        .catch(function () { setTimeout(tick, 6000); });
    }
    tick();
  }

  function bindSimulator(el) {
    el.querySelectorAll("[data-outcome]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        const body = new URLSearchParams({ outcome: btn.dataset.outcome });
        el.querySelectorAll("[data-outcome]").forEach(function (b) { b.disabled = true; });
        fetch(el.dataset.simulateUrl, {
          method: "POST",
          headers: { "X-CSRFToken": csrfToken(), Accept: "application/json" },
          body: body,
        })
          .then(function (r) { return r.json(); })
          .then(function (data) { render(el, data); if (data.final) finish(el, data); });
      });
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("[data-mpesa-tx]").forEach(function (el) {
      bindSimulator(el);
      poll(el);
    });
    // Prevent double submits on payment forms.
    document.querySelectorAll("form[data-once]").forEach(function (form) {
      form.addEventListener("submit", function () {
        form.querySelectorAll("button[type=submit], button:not([type])").forEach(function (b) {
          b.disabled = true;
          if (b.dataset.loading) b.innerHTML = b.dataset.loading;
        });
      });
    });
  });
})();
