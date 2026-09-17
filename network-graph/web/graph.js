/* Force-directed partner network graph. Reads window.NETWORK_DATA.
 *
 * The highlighted route is the warmest path (Dijkstra over cost 1 - weight),
 * not the fewest hops. Force layout is O(n squared), fine to a few hundred
 * nodes. No dependencies, no external requests.
 */
(function () {
  "use strict";

  var svg = document.getElementById("g");
  var DATA = window.NETWORK_DATA;
  if (!svg || !DATA || !DATA.nodes || !DATA.edges) return;

  var SVGNS = "http://www.w3.org/2000/svg";
  var reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* The viewBox follows the container size so one unit is one pixel. */
  var W = 900, H = 620;
  function measure() {
    var box = svg.parentNode.getBoundingClientRect();
    W = Math.max(320, Math.round(box.width));
    H = Math.max(360, Math.round(box.height));
    svg.setAttribute("viewBox", "0 0 " + W + " " + H);
  }
  measure();

  /* ---------- build the graph from the data file ---------- */

  var nodes = [], byId = {}, links = [];

  DATA.nodes.forEach(function (d) {
    if (byId[d.id]) return;
    var n = {
      id: d.id,
      name: d.name || d.id,
      kind: d.kind,
      tier: d.tier || null,
      title: d.title || "",
      employer: d.employer || "",
      location: d.location || "",
      asOf: d.as_of || "",
      x: W / 2 + (Math.random() - 0.5) * 320,
      y: H / 2 + (Math.random() - 0.5) * 260,
      vx: 0, vy: 0, deg: 0
    };
    nodes.push(n);
    byId[n.id] = n;
  });

  DATA.edges.forEach(function (e) {
    var a = byId[e.source], b = byId[e.target];
    if (!a || !b || a === b) return;
    var w = Math.max(0.01, Math.min(1, +e.weight || 0));
    /* Warm edges pull tighter, so strength is visible in distance too. */
    var len = (a.kind === "fund" || b.kind === "fund") ? 120 : 90 + (1 - w) * 150;
    links.push({ a: a, b: b, w: w, tier: e.tier || "possible", basis: e.basis || null, len: len });
    a.deg++; b.deg++;
  });

  var fund = null;
  for (var fi = 0; fi < nodes.length; fi++) {
    if (nodes[fi].kind === "fund") { fund = nodes[fi]; break; }
  }
  if (!fund) return;

  /* ---------- style per kind, colleague style per tier ---------- */

  function styleOf(n) {
    if (n.kind === "fund") return { r: 15, fill: "#2563eb", stroke: "none", shape: "diamond", label: 1 };
    if (n.kind === "op") return { r: 8, fill: "#1f2328", stroke: "none", shape: "diamond", label: 1 };
    if (n.tier === "strong") return { r: 7, fill: "#ffffff", stroke: "#2563eb", shape: "circle", label: 1 };
    return { r: 5, fill: "#9aa4b2", stroke: "none", shape: "circle", label: 0 };
  }
  nodes.forEach(function (n) { n.style = styleOf(n); });

  function kindLabel(n) {
    if (n.kind === "fund") return "The fund";
    if (n.kind === "op") return "Partner";
    return n.tier === "strong" ? "Likely colleague / strong" : "Likely colleague / possible";
  }

  function basisText(l) {
    if (l.tier === "confirmed") return "confirmed";
    if (!l.basis) return "";
    var parts = [];
    if (l.basis.company) parts.push("overlapped at " + l.basis.company);
    if (l.basis.window) parts.push(l.basis.window);
    if (l.basis.overlap_years) parts.push(l.basis.overlap_years + " years");
    return parts.join(", ");
  }

  function pct(x) { return Math.round(x * 100); }

  var stats = { ops: 0, colleagues: 0, confirmed: 0, strong: 0, possible: 0 };
  nodes.forEach(function (n) {
    if (n.kind === "op") stats.ops++;
    if (n.kind === "colleague") stats.colleagues++;
  });
  links.forEach(function (l) {
    if (l.tier === "confirmed") stats.confirmed++;
    else if (l.tier === "strong") stats.strong++;
    else stats.possible++;
  });
  /* board seats are confirmed doors that are not drawn as edges */
  var seats = (DATA.advisorySeats || []).length;

  /* ---------- render skeleton ---------- */

  var root = document.createElementNS(SVGNS, "g");
  var gLinks = document.createElementNS(SVGNS, "g");
  var gNodes = document.createElementNS(SVGNS, "g");
  root.appendChild(gLinks); root.appendChild(gNodes);
  svg.appendChild(root);

  links.forEach(function (l) {
    l.el = document.createElementNS(SVGNS, "line");
    l.el.setAttribute("class", "glink");
    l.el.setAttribute("stroke-width", (0.6 + 2.2 * l.w).toFixed(2));
    l.el.setAttribute("stroke-opacity", (0.25 + 0.6 * l.w).toFixed(2));
    gLinks.appendChild(l.el);
  });

  nodes.forEach(function (n) {
    var s = n.style;
    var g = document.createElementNS(SVGNS, "g");
    g.setAttribute("class", "gnode");
    var shape;
    if (s.shape === "diamond") {
      shape = document.createElementNS(SVGNS, "path");
      shape.setAttribute("d", "M0 " + -s.r + " L" + s.r + " 0 L0 " + s.r + " L" + -s.r + " 0 Z");
    } else {
      shape = document.createElementNS(SVGNS, "circle");
      shape.setAttribute("r", s.r);
    }
    shape.setAttribute("fill", s.fill);
    if (s.stroke !== "none") {
      shape.setAttribute("stroke", s.stroke);
      shape.setAttribute("stroke-width", "1.6");
    }
    g.appendChild(shape);

    var t = document.createElementNS(SVGNS, "text");
    t.setAttribute("y", s.r + 11);
    t.textContent = n.name;
    g.appendChild(t);

    n.el = g; n.textEl = t;
    /* Label a node if its kind says so, or if more than one edge touches it:
       a colleague shared by two partners is the node worth reading. */
    n.labelDefault = (s.label || n.deg > 1) ? 1 : 0;
    if (!n.labelDefault) t.setAttribute("opacity", "0");
    gNodes.appendChild(g);
  });

  /* ---------- label declutter ----------
     Most connected labels first, below the node if free, above if not,
     dropped if neither fits. About 5.1px per character at 9px. */
  function placeLabels() {
    var placed = [];
    var order = nodes.filter(function (n) { return n.labelDefault; })
      .sort(function (a, b) {
        if (a.kind === "fund") return -1;
        if (b.kind === "fund") return 1;
        return b.deg - a.deg;
      });

    order.forEach(function (n) {
      var r = n.style.r;
      var w = n.name.length * 5.1;
      var opts = [n.y + r + 11, n.y - r - 4];
      var chosen = null;

      for (var i = 0; i < opts.length && chosen === null; i++) {
        var box = { x1: n.x - w / 2, x2: n.x + w / 2, y1: opts[i] - 8, y2: opts[i] + 2 };
        var clash = placed.some(function (p) {
          return !(box.x2 < p.x1 || box.x1 > p.x2 || box.y2 < p.y1 || box.y1 > p.y2);
        });
        if (!clash) { chosen = opts[i]; placed.push(box); }
      }

      if (chosen === null) {
        n.labelHidden = true;
        n.textEl.setAttribute("opacity", "0");
      } else {
        n.labelHidden = false;
        n.textEl.setAttribute("y", (chosen - n.y).toFixed(1));
        n.textEl.setAttribute("opacity", "1");
      }
    });
  }

  /* ---------- force simulation ---------- */

  var alpha = 1;

  function tick() {
    var i, j, a, b, dx, dy, d, f;

    for (i = 0; i < nodes.length; i++) {
      a = nodes[i];
      for (j = i + 1; j < nodes.length; j++) {
        b = nodes[j];
        dx = b.x - a.x; dy = b.y - a.y;
        d = Math.sqrt(dx * dx + dy * dy) || 0.01;
        if (d > 460) continue;
        f = (3200 / (d * d)) * alpha;
        if (f > 7) f = 7;
        dx /= d; dy /= d;
        a.vx -= dx * f; a.vy -= dy * f;
        b.vx += dx * f; b.vy += dy * f;
      }
    }

    for (i = 0; i < links.length; i++) {
      var l = links[i];
      dx = l.b.x - l.a.x; dy = l.b.y - l.a.y;
      d = Math.sqrt(dx * dx + dy * dy) || 0.01;
      f = ((d - l.len) * 0.045) * alpha;
      dx /= d; dy /= d;
      l.a.vx += dx * f; l.a.vy += dy * f;
      l.b.vx -= dx * f; l.b.vy -= dy * f;
    }

    for (i = 0; i < nodes.length; i++) {
      a = nodes[i];
      if (a.fixed) { a.vx = 0; a.vy = 0; continue; }
      /* The fund is pinned to the middle. */
      if (a.kind === "fund") {
        a.vx += (W / 2 - a.x) * 0.06;
        a.vy += (H / 2 - a.y) * 0.06;
      } else {
        a.vx += (W / 2 - a.x) * 0.0009 * alpha;
        a.vy += (H / 2 - a.y) * 0.0013 * alpha;
      }
      a.vx *= 0.82; a.vy *= 0.82;
      a.x += a.vx; a.y += a.vy;
      a.x = Math.max(56, Math.min(W - 56, a.x));
      a.y = Math.max(30, Math.min(H - 30, a.y));
    }

    if (alpha > 0.02) alpha *= 0.985;
  }

  function draw() {
    for (var i = 0; i < links.length; i++) {
      var l = links[i];
      l.el.setAttribute("x1", l.a.x); l.el.setAttribute("y1", l.a.y);
      l.el.setAttribute("x2", l.b.x); l.el.setAttribute("y2", l.b.y);
    }
    for (i = 0; i < nodes.length; i++) {
      nodes[i].el.setAttribute("transform", "translate(" + nodes[i].x.toFixed(1) + "," + nodes[i].y.toFixed(1) + ")");
    }
  }

  var raf, labelsDirty = true;
  function loop() {
    tick(); draw();
    if (labelsDirty && alpha < 0.06) { placeLabels(); labelsDirty = false; }
    raf = requestAnimationFrame(loop);
  }

  function reseed() {
    nodes.forEach(function (n) {
      if (n.kind === "fund") { n.x = W / 2; n.y = H / 2; }
      else {
        var ang = Math.random() * Math.PI * 2;
        var rad = n.kind === "op" ? 120 : 250;
        n.x = W / 2 + Math.cos(ang) * rad;
        n.y = H / 2 + Math.sin(ang) * rad * 0.78;
      }
      n.vx = 0; n.vy = 0;
    });
    alpha = 1;
    labelsDirty = true;
  }

  reseed();
  /* Settle before the first paint so it does not start as a hairball. */
  for (var wu = 0; wu < 260; wu++) tick();
  draw();
  loop();

  var rt;
  window.addEventListener("resize", function () {
    clearTimeout(rt);
    rt = setTimeout(function () {
      var ow = W, oh = H;
      measure();
      if (Math.abs(ow - W) < 2 && Math.abs(oh - H) < 2) return;
      nodes.forEach(function (n) { n.x += (W - ow) / 2; n.y += (H - oh) / 2; });
      alpha = Math.max(alpha, 0.5);
      labelsDirty = true;
    }, 180);
  });

  /* ---------- pan and zoom ---------- */

  var view = { x: 0, y: 0, k: 1 };
  function applyView() {
    root.setAttribute("transform", "translate(" + view.x + "," + view.y + ") scale(" + view.k + ")");
  }
  applyView();

  var dragNode = null, panning = false, last = null;

  function toLocal(evt) {
    var r = svg.getBoundingClientRect();
    var sx = (evt.clientX - r.left) / r.width * W;
    var sy = (evt.clientY - r.top) / r.height * H;
    return { x: (sx - view.x) / view.k, y: (sy - view.y) / view.k, sx: sx, sy: sy };
  }

  svg.addEventListener("pointerdown", function (e) {
    var p = toLocal(e);
    var hit = null, best = 1e9;
    nodes.forEach(function (n) {
      var dx = n.x - p.x, dy = n.y - p.y, d = dx * dx + dy * dy;
      var rr = (n.style.r + 6) * (n.style.r + 6);
      if (d < rr && d < best) { best = d; hit = n; }
    });
    if (hit) {
      dragNode = hit; hit.fixed = true;
      select(hit);
    } else {
      panning = true;
      svg.classList.add("is-drag");
    }
    last = p;
    svg.setPointerCapture(e.pointerId);
  });

  svg.addEventListener("pointermove", function (e) {
    if (!dragNode && !panning) return;
    var p = toLocal(e);
    if (dragNode) {
      dragNode.x = p.x; dragNode.y = p.y;
      alpha = Math.max(alpha, 0.25);
      labelsDirty = true;
    } else {
      view.x += (p.sx - last.sx); view.y += (p.sy - last.sy);
      applyView();
    }
    last = p;
  });

  function endDrag(e) {
    if (dragNode) dragNode.fixed = false;
    dragNode = null; panning = false;
    svg.classList.remove("is-drag");
    if (e && e.pointerId != null && svg.hasPointerCapture(e.pointerId)) {
      svg.releasePointerCapture(e.pointerId);
    }
  }
  svg.addEventListener("pointerup", endDrag);
  svg.addEventListener("pointercancel", endDrag);

  svg.addEventListener("wheel", function (e) {
    e.preventDefault();
    var p = toLocal(e);
    var k = view.k * (e.deltaY < 0 ? 1.12 : 1 / 1.12);
    k = Math.max(0.45, Math.min(3.2, k));
    view.x = p.sx - p.x * k;
    view.y = p.sy - p.y * k;
    view.k = k;
    applyView();
  }, { passive: false });

  /* ---------- selection and highlighting ---------- */

  var panel = document.getElementById("panel");

  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function neighboursOf(n) {
    var out = [];
    links.forEach(function (l) {
      if (l.a === n) out.push({ n: l.b, link: l });
      else if (l.b === n) out.push({ n: l.a, link: l });
    });
    return out;
  }

  function clearHighlight() {
    links.forEach(function (l) { l.el.setAttribute("class", "glink"); });
    nodes.forEach(function (n) {
      n.el.setAttribute("class", "gnode");
      n.textEl.setAttribute("opacity", n.labelDefault && !n.labelHidden ? "1" : "0");
    });
  }

  function highlight(set, linkSet) {
    links.forEach(function (l) {
      l.el.setAttribute("class", "glink " + (linkSet.has(l) ? "is-lit" : "is-dim"));
    });
    nodes.forEach(function (n) {
      var on = set.has(n);
      n.el.setAttribute("class", "gnode " + (on ? "is-lit" : "is-dim"));
      n.textEl.setAttribute("opacity", on ? "1" : (n.labelDefault && !n.labelHidden ? "0.35" : "0"));
    });
  }

  /* ---------- warmest route: Dijkstra over cost 1 - weight ----------
     Strength of a route is the product of its edge weights. */
  function warmRoute(targetId) {
    var goal = byId[targetId];
    if (!goal || goal === fund) return null;
    var dist = {}, prev = {}, done = {};
    nodes.forEach(function (n) { dist[n.id] = Infinity; });
    dist[fund.id] = 0;

    for (;;) {
      var cur = null, best = Infinity;
      for (var id in dist) {
        if (!done[id] && dist[id] < best) { best = dist[id]; cur = id; }
      }
      if (cur === null || cur === goal.id) break;
      done[cur] = 1;
      for (var i = 0; i < links.length; i++) {
        var l = links[i];
        var other = null;
        if (l.a.id === cur) other = l.b;
        else if (l.b.id === cur) other = l.a;
        if (!other || done[other.id]) continue;
        var cost = dist[cur] + (1 - l.w);
        if (cost < dist[other.id]) {
          dist[other.id] = cost;
          prev[other.id] = { node: byId[cur], link: l };
        }
      }
    }

    if (!isFinite(dist[goal.id])) return null;
    var chain = [goal], steps = [], c = goal;
    while (prev[c.id]) {
      steps.unshift(prev[c.id].link);
      c = prev[c.id].node;
      chain.unshift(c);
    }
    var strength = 1;
    steps.forEach(function (l) { strength *= l.w; });
    return { chain: chain, links: steps, strength: strength };
  }

  function routeNames(route) {
    return route.chain.map(function (n) { return n.name; }).join(" > ");
  }

  /* ---------- panel views ---------- */

  function select(n) {
    var nb = neighboursOf(n);
    var set = new Set([n]);
    nb.forEach(function (x) { set.add(x.n); });
    var lset = new Set();
    links.forEach(function (l) { if (l.a === n || l.b === n) lset.add(l); });
    highlight(set, lset);

    var html = '<p class="gpanel__kind">' + esc(kindLabel(n)) + "</p>";
    html += "<h3>" + esc(n.name) + "</h3>";

    var meta = [];
    if (n.title) meta.push(n.title);
    if (n.employer && n.kind !== "fund") meta.push("now at " + n.employer);
    if (n.location) meta.push(n.location);
    if (meta.length) html += '<p class="gpanel__note">' + esc(meta.join(". ")) + ".</p>";
    if (n.asOf) html += '<p class="gpanel__asof">data as of: ' + esc(n.asOf) + "</p>";

    var own = (DATA.advisorySeats || []).filter(function (s) { return s.advisor_id === n.id; });
    if (own.length) {
      html += "<h4>Board and advisory seats (confirmed)</h4><ul>";
      html += own.map(function (s) {
        return "<li>" + esc(s.title + " at " + s.company + (s.since ? " since " + s.since : "")) + "</li>";
      }).join("");
      html += "</ul>";
    }

    html += "<h4>Connections (" + nb.length + ")</h4><ul>";
    html += nb.slice(0, 60).map(function (x) {
      var b = basisText(x.link);
      return "<li>" + esc(x.n.name) + (b ? " <b>" + esc(b) + "</b>" : "") +
        ' <span class="gpanel__w">' + pct(x.link.w) + "%</span></li>";
    }).join("");
    html += "</ul>";

    if (n !== fund) {
      var route = warmRoute(n.id);
      if (route) {
        html += "<h4>Warmest route from the fund</h4>" +
          '<p class="gpanel__note">' + esc(routeNames(route)) + " <b>" + pct(route.strength) + "%</b></p>";
      }
    }
    panel.innerHTML = html;
  }

  function warmPath(targetId) {
    var route = warmRoute(targetId);
    var goal = byId[targetId];
    if (!route || !goal) return;
    highlight(new Set(route.chain), new Set(route.links));

    var html = '<p class="gpanel__kind">Warmest route</p>';
    html += "<h3>" + esc(goal.name) + "</h3>";
    html += '<p class="gpanel__note">Route strength <b>' + pct(route.strength) +
      "%</b>: the product of the edge weights along the way.</p>";
    html += "<h4>Route</h4><ul>";
    route.chain.forEach(function (n, i) {
      var via = "";
      if (i > 0) {
        var b = basisText(route.links[i - 1]);
        if (b) via = " <b>" + esc(b) + "</b>";
      }
      html += "<li>" + (i + 1) + ". " + esc(n.name) + via + "</li>";
    });
    html += "</ul>";
    panel.innerHTML = html;
  }

  function intro() {
    var busiest = null;
    nodes.forEach(function (n) {
      if (n.kind === "op" && (!busiest || n.deg > busiest.deg)) busiest = n;
    });
    var html = '<p class="gpanel__kind">Built from career-history data</p>';
    html += "<h3>" + nodes.length + " nodes, " + links.length + " edges</h3>";
    html += '<p class="gpanel__note">The fund, ' + stats.ops + " partners and " + stats.colleagues +
      " colleagues they likely know. " + stats.confirmed + " edges are confirmed; " +
      (stats.strong + stats.possible) + " are inferred from employment overlap.</p>";
    html += "<h4>Read this first</h4><ul>";
    html += "<li>Inferred edges say <b>likely knows</b>, never knows.</li>";
    html += "<li>Edge width and brightness follow strength. So does distance.</li>";
    html += "</ul><h4>Try</h4><ul>";
    html += "<li>Ask the box above for a door into any company.</li>";
    if (busiest) html += "<li>Click <b>" + esc(busiest.name) + "</b>, the most connected partner.</li>";
    html += "</ul>";
    panel.innerHTML = html;
  }

  /* ---------- controls ---------- */

  document.getElementById("clearPath").addEventListener("click", function () {
    clearHighlight();
    intro();
  });

  document.getElementById("reheat").addEventListener("click", function () {
    reseed();
    view = { x: 0, y: 0, k: 1 };
    applyView();
  });

  /* ---------- computed stats and tier counts ---------- */

  function statCell(label, value, note) {
    return "<div><dt>" + esc(label) + "</dt><dd>" + esc(String(value)) +
      "<small>" + esc(note) + "</small></dd></div>";
  }

  var box = document.getElementById("netstats");
  if (box) {
    box.innerHTML =
      statCell("Nodes", nodes.length, "1 fund, " + stats.ops + " partners, " + stats.colleagues + " colleagues") +
      statCell("Edges", links.length, "width follows strength") +
      statCell("Confirmed", stats.confirmed + seats, stats.confirmed + " fund ties, " + seats + " board seats") +
      statCell("Inferred", stats.strong + stats.possible, "from employment overlap, tiered");
  }

  Array.prototype.forEach.call(document.querySelectorAll("[data-tier-count]"), function (el) {
    var t = el.getAttribute("data-tier-count");
    el.textContent = String(t === "confirmed" ? stats.confirmed + seats : stats[t]);
  });

  intro();

  /* Stop the simulation when the tab is hidden. */
  document.addEventListener("visibilitychange", function () {
    if (document.hidden) { cancelAnimationFrame(raf); raf = null; }
    else if (!raf) { raf = requestAnimationFrame(loop); }
  });

  /* Hook for ask.js: light a person's warmest route and bring the graph into view. */
  window.NETWORK_GRAPH = {
    focusPerson: function (personId) {
      if (!byId[personId]) return;
      warmPath(personId);
      document.getElementById("graph").scrollIntoView({ behavior: reduce ? "auto" : "smooth" });
    }
  };
})();
