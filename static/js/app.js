/* Spares Inventory - progressive enhancement only. No build step, no CDN. */
(function () {
  "use strict";

  // --- Mobile sidebar ---
  document.addEventListener("click", function (e) {
    var t = e.target.closest("[data-nav-toggle]");
    if (t) { document.body.classList.toggle("nav-open"); return; }
    if (e.target.classList && e.target.classList.contains("scrim")) {
      document.body.classList.remove("nav-open");
    }
  });

  // --- Confirm destructive actions ---
  document.addEventListener("submit", function (e) {
    var msg = e.target.getAttribute("data-confirm");
    if (msg && !window.confirm(msg)) { e.preventDefault(); }
  }, true);

  // --- Dependent selects: warehouse -> rack -> column -> table -> location ---
  function loadOptions(select, url, placeholder) {
    if (!select) return Promise.resolve();
    var keep = select.getAttribute("data-selected") || select.value;
    select.disabled = true;
    return fetch(url, { headers: { "X-Requested-With": "XMLHttpRequest" } })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        select.innerHTML = "";
        var blank = document.createElement("option");
        blank.value = ""; blank.textContent = placeholder || "---------";
        select.appendChild(blank);
        (data.results || []).forEach(function (row) {
          var o = document.createElement("option");
          o.value = row.id; o.textContent = row.text;
          if (String(row.id) === String(keep)) o.selected = true;
          select.appendChild(o);
        });
        select.disabled = false;
        select.dispatchEvent(new Event("change", { bubbles: false }));
      })
      .catch(function () { select.disabled = false; });
  }

  function wireChain(root) {
    var wh = root.querySelector("[data-chain='warehouse']");
    var rack = root.querySelector("[data-chain='rack']");
    var col = root.querySelector("[data-chain='column']");
    var tab = root.querySelector("[data-chain='table']");
    var loc = root.querySelector("[data-chain='location']");
    if (!wh) return;

    function refreshLocation() {
      if (!loc) return;
      var qs = "?warehouse=" + (wh.value || "");
      if (rack && rack.value) qs += "&rack=" + rack.value;
      if (col && col.value) qs += "&column=" + col.value;
      if (tab && tab.value) qs += "&table=" + tab.value;
      loadOptions(loc, "/masters/options/locations/" + qs, "Select location");
    }
    if (wh && rack) {
      wh.addEventListener("change", function () {
        loadOptions(rack, "/masters/options/racks/?warehouse=" + (wh.value || ""), "All racks")
          .then(refreshLocation);
      });
    } else if (wh) {
      wh.addEventListener("change", refreshLocation);
    }
    if (rack && col) {
      rack.addEventListener("change", function () {
        loadOptions(col, "/masters/options/columns/?rack=" + (rack.value || ""), "All columns")
          .then(refreshLocation);
      });
    }
    if (col && tab) {
      col.addEventListener("change", function () {
        loadOptions(tab, "/masters/options/tables/?column=" + (col.value || ""), "All tables")
          .then(refreshLocation);
      });
    }
    if (tab) tab.addEventListener("change", refreshLocation);
  }
  document.querySelectorAll("[data-location-chain]").forEach(wireChain);

  // --- Formset: add / remove rows ---
  document.querySelectorAll("[data-formset]").forEach(function (fs) {
    var body = fs.querySelector("[data-formset-body]");
    var tmpl = fs.querySelector("[data-formset-template]");
    var addBtn = fs.querySelector("[data-formset-add]");
    var totalInput = fs.querySelector("input[name$='-TOTAL_FORMS']");
    if (!body || !tmpl || !addBtn || !totalInput) return;

    addBtn.addEventListener("click", function () {
      var idx = parseInt(totalInput.value, 10);
      var html = tmpl.innerHTML.replace(/__prefix__/g, idx);
      var row = document.createElement("tr");
      row.className = "formset-row";
      row.innerHTML = html;
      body.appendChild(row);
      totalInput.value = idx + 1;
      wireChain(row);
      var first = row.querySelector("select,input");
      if (first) first.focus();
    });

    body.addEventListener("click", function (e) {
      var btn = e.target.closest("[data-formset-remove]");
      if (!btn) return;
      var row = btn.closest("tr");
      var del = row.querySelector("input[name$='-DELETE']");
      if (del) { del.checked = true; row.style.display = "none"; }
      else { row.remove(); totalInput.value = Math.max(0, parseInt(totalInput.value, 10) - 1); }
    });
  });

  // --- Scanner: keep focus on the scan field, submit on Enter ---
  var scanField = document.querySelector("[data-scan-input]");
  if (scanField) {
    var refocus = function () { setTimeout(function () { scanField.focus(); }, 30); };
    refocus();
    document.addEventListener("click", function (e) {
      if (e.target.closest("input,select,textarea,button,a")) return;
      refocus();
    });
  }

  // --- Live stock check on outward quantity fields ---
  document.querySelectorAll("[data-availability]").forEach(function (input) {
    var target = document.querySelector(input.getAttribute("data-availability"));
    input.addEventListener("input", function () {
      if (!target) return;
      var avail = parseFloat(target.getAttribute("data-available") || "0");
      var val = parseFloat(input.value || "0");
      input.style.borderColor = (val > avail) ? "var(--danger)" : "";
    });
  });

  // --- Print helper ---
  document.querySelectorAll("[data-print]").forEach(function (btn) {
    btn.addEventListener("click", function () { window.print(); });
  });

  // --- Auto-dismiss transient messages ---
  setTimeout(function () {
    document.querySelectorAll(".alert--success").forEach(function (el) {
      el.style.transition = "opacity .4s"; el.style.opacity = "0";
      setTimeout(function () { el.remove(); }, 400);
    });
  }, 6000);
})();
