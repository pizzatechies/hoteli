/* Staff booking form: guest look-up and live room availability. */
(function () {
  "use strict";
  const form = document.getElementById("booking-form");
  if (!form) return;
  const availabilityUrl = form.dataset.availabilityUrl;
  const guestSearchUrl = form.dataset.guestSearchUrl;
  const excludeId = form.dataset.exclude || "";

  // ---------------------------------------------------------------- availability
  const ci = form.querySelector("[name=check_in_date]");
  const co = form.querySelector("[name=check_out_date]");
  const roomSelect = form.querySelector("[name=room]");
  const rateInput = form.querySelector("[name=rate]");
  const info = document.getElementById("availability-info");

  function refreshRooms() {
    if (!ci.value || !co.value || !roomSelect) return;
    const params = new URLSearchParams({ check_in: ci.value, check_out: co.value });
    if (excludeId) params.set("exclude", excludeId);
    fetch(availabilityUrl + "?" + params, { headers: { Accept: "application/json" } })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        const current = roomSelect.value;
        roomSelect.innerHTML = "";
        if (data.error) { info.textContent = data.error; return; }
        const placeholder = new Option(data.rooms.length ? "Select a room" : "No rooms free for these dates", "");
        roomSelect.add(placeholder);
        let groups = {};
        data.rooms.forEach(function (room) {
          if (!groups[room.type]) {
            groups[room.type] = document.createElement("optgroup");
            groups[room.type].label = room.type + " – KES " + Number(room.rate).toLocaleString() + "/night";
            roomSelect.appendChild(groups[room.type]);
          }
          const label = room.number + (room.ready ? "" : " (" + room.hk_status.toLowerCase() + ")");
          const opt = new Option(label, room.id);
          opt.dataset.rate = room.rate;
          groups[room.type].appendChild(opt);
        });
        if (current && roomSelect.querySelector('option[value="' + current + '"]')) roomSelect.value = current;
        info.textContent = data.rooms.length + " room(s) free for " + data.nights + " night(s).";
        updateRateHint();
      });
  }

  function updateRateHint() {
    if (!rateInput) return;
    const opt = roomSelect.selectedOptions[0];
    rateInput.placeholder = opt && opt.dataset.rate ? "Default: " + Number(opt.dataset.rate).toLocaleString() : "";
  }

  if (ci && co) {
    ci.addEventListener("change", function () {
      if (co.value <= ci.value) {
        const d = new Date(ci.value);
        d.setDate(d.getDate() + 1);
        co.value = d.toISOString().slice(0, 10);
      }
      refreshRooms();
    });
    co.addEventListener("change", refreshRooms);
    if (roomSelect) roomSelect.addEventListener("change", updateRateHint);
    refreshRooms();
  }

  // ---------------------------------------------------------------- guest search
  const search = document.getElementById("guest-search");
  const results = document.getElementById("guest-results");
  const guestInput = form.querySelector("[name=guest]");
  const chosen = document.getElementById("guest-chosen");
  const newGuest = document.getElementById("new-guest-fields");
  if (!search || !guestInput) return;

  function choose(g) {
    guestInput.value = g.id;
    chosen.innerHTML = '<div class="alert alert-success d-flex justify-content-between align-items-center mb-0">' +
      "<div><i class='bi bi-person-check'></i> <strong></strong> <span class='small text-body-secondary'></span></div>" +
      '<button type="button" class="btn btn-sm btn-outline-secondary">Change</button></div>';
    chosen.querySelector("strong").textContent = g.name + (g.vip ? " ★ VIP" : "");
    chosen.querySelector("span").textContent = " " + g.phone + (g.id_number ? " · ID " + g.id_number : "");
    if (g.blacklisted) chosen.querySelector(".alert").className = "alert alert-danger d-flex justify-content-between align-items-center mb-0";
    chosen.querySelector("button").addEventListener("click", clear);
    newGuest.classList.add("d-none");
    search.closest(".guest-search-wrap").classList.add("d-none");
    results.innerHTML = "";
  }

  function clear() {
    guestInput.value = "";
    chosen.innerHTML = "";
    newGuest.classList.remove("d-none");
    search.closest(".guest-search-wrap").classList.remove("d-none");
    search.value = "";
    search.focus();
  }

  let timer;
  search.addEventListener("input", function () {
    clearTimeout(timer);
    const q = search.value.trim();
    if (q.length < 2) { results.innerHTML = ""; return; }
    timer = setTimeout(function () {
      fetch(guestSearchUrl + "?q=" + encodeURIComponent(q), { headers: { Accept: "application/json" } })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          results.innerHTML = "";
          if (!data.results.length) {
            results.innerHTML = '<div class="list-group-item small text-body-secondary">No match – fill in the new guest details below.</div>';
            return;
          }
          data.results.forEach(function (g) {
            const a = document.createElement("button");
            a.type = "button";
            a.className = "list-group-item list-group-item-action";
            a.textContent = g.name + " · " + g.phone + (g.blacklisted ? " · BLACKLISTED" : "");
            a.addEventListener("click", function () { choose(g); });
            results.appendChild(a);
          });
        });
    }, 250);
  });

  if (form.dataset.preselected) choose(JSON.parse(form.dataset.preselected));
})();
