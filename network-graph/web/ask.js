/* Ask box: posts a question to /api/ask and renders the answer with its
   citations. Every string that comes back is model output, so everything
   is escaped before it touches the DOM. No dependencies. */
(function () {
  "use strict";

  var form = document.getElementById("askForm");
  var input = document.getElementById("askInput");
  var btn = document.getElementById("askBtn");
  var box = document.getElementById("askAnswers");
  if (!form || !input || !btn || !box) return;

  var MAX_CARDS = 3;

  function esc(s) {
    var d = document.createElement("div");
    d.textContent = s == null ? "" : String(s);
    return d.innerHTML.replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  function pct(w) {
    return Math.round(Math.max(0, Math.min(1, +w || 0)) * 100);
  }

  function basisLine(c) {
    if (c.advisory_seat) {
      var s = c.advisory_seat;
      return (s.title || "board seat") + " at " + c.company + (s.since ? " since " + s.since : "");
    }
    if (c.status === "current") {
      return "at " + c.company + " now" + (c.current_role ? ", " + c.current_role : "");
    }
    var line = "overlapped at " + (c.overlap_company || c.company) + (c.window ? " " + c.window : "");
    return line + (c.overlap_years ? ", " + c.overlap_years + " years" : "");
  }

  function citeRows(citations) {
    if (!citations || !citations.length) return "";
    return '<ul class="acard__cites">' + citations.map(function (c) {
      var extra = (!c.advisory_seat && c.status !== "current" && c.current_employer)
        ? '<span class="acite__now">now at ' + esc(c.current_employer) + "</span>" : "";
      var via = (c.advisory_seat || c.via_op === "direct") ? "partner" : "via " + c.via_op;
      return '<li><button type="button" class="acite" data-person="' + esc(c.person_id) + '">' +
        '<span class="acite__via">' + esc(via) + "</span>" +
        '<span class="acite__who">' + esc(c.person) + "</span>" +
        '<span class="acite__why">' + esc(basisLine(c)) + "</span>" + extra +
        '<span class="gstrength" role="img" aria-label="strength ' + pct(c.weight) + ' percent">' +
        '<i style="width:' + pct(c.weight) + '%"></i></span>' +
        "</button></li>";
    }).join("") + "</ul>";
  }

  var busy = false;

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    if (busy) return;
    var q = (input.value || "").trim().slice(0, 400);
    if (!q) return;

    busy = true;
    input.disabled = btn.disabled = true;

    var card = document.createElement("article");
    card.className = "acard is-pending";
    card.innerHTML = '<p class="acard__q">' + esc(q) + '</p><p class="acard__a">asking the graph</p>';
    box.insertBefore(card, box.firstChild);
    while (box.children.length > MAX_CARDS) box.removeChild(box.lastChild);

    function finish(bodyHtml) {
      card.classList.remove("is-pending");
      card.innerHTML = '<p class="acard__q">' + esc(q) + "</p>" + bodyHtml;
      busy = false;
      input.disabled = btn.disabled = false;
      input.value = "";
      input.focus();
    }

    function fail(msg) {
      finish('<p class="acard__a acard__err">' + esc(msg) + "</p>");
    }

    fetch("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ q: q })
    })
      .then(function (r) {
        if (r.status === 429) { fail("Give it a few seconds between questions."); return null; }
        if (r.status === 503) { fail("The ask server has no ANTHROPIC_API_KEY set."); return null; }
        if (!r.ok) { fail("Something went wrong asking the graph. Is the ask server running?"); return null; }
        return r.json();
      })
      .then(function (d) {
        if (!d) return;
        if (!d.answer) { fail("Something went wrong asking the graph. Try again."); return; }
        finish('<p class="acard__a">' + esc(d.answer) + "</p>" + citeRows(d.citations));
      })
      .catch(function () {
        fail("Could not reach the ask server. Start it with node ask/server.mjs.");
      });
  });

  /* Citation clicks light the person's route on the graph. */
  box.addEventListener("click", function (e) {
    var b = e.target.closest ? e.target.closest("[data-person]") : null;
    if (b && window.NETWORK_GRAPH) window.NETWORK_GRAPH.focusPerson(b.getAttribute("data-person"));
  });
})();
