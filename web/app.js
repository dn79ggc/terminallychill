(function () {
  "use strict";

  var TZ = "America/New_York";
  var DEMO_CONCOURSE = "B";
  var GATE_RE = /^[TABCDEF]\d{1,2}$/;
  var SCOPE_MESSAGE = "We're currently available in Concourse B. More concourses are planned.";
  var BUCKET_MIN = 5;
  var MOCK = new URLSearchParams(location.search).get("mock") === "1";

  var state = {
    graph: null,
    mapReady: false,
    activeConcourse: null,
    gate: null,
    boarding: null,
    forecast: null,
    recommend: null,
    assumptions: null,
    selectedSpotId: null,
    inspectedZoneId: null,
    horizonBucket: 0,
    loading: false,
    dataSource: null,
    usingMock: false,
    view: "input",
    zoomed: false,
    baseBox: null,
    box: null,
    zoomFrame: 0
  };

  var AIRPORT_QUERY = "Hartsfield-Jackson Atlanta International Airport Concourse B";

  var els = {
    app: document.getElementById("app"),
    results: document.getElementById("results"),
    editBtn: document.getElementById("edit-btn"),
    scopeNote: document.getElementById("scope-note"),
    mapReset: document.getElementById("map-reset"),
    listTitle: document.getElementById("list-title"),
    pick: document.getElementById("pick"),
    pickLabel: document.getElementById("pick-label"),
    pickName: document.getElementById("pick-name"),
    pickWalk: document.getElementById("pick-walk"),
    pickLeave: document.getElementById("pick-leave"),
    pickCountdown: document.getElementById("pick-countdown"),
    pickCrowd: document.getElementById("pick-crowd"),
    pickNote: document.getElementById("pick-note"),
    linkGoogle: document.getElementById("link-google"),
    linkApple: document.getElementById("link-apple"),
    mockBanner: document.getElementById("mock-banner"),
    sourceBadge: document.getElementById("source-badge"),
    sourceBadgeValue: document.getElementById("source-badge-value"),
    aboutSource: document.getElementById("about-source"),
    aboutAssumptionsVersion: document.getElementById("about-assumptions-version"),
    assumptionsEmpty: document.getElementById("assumptions-empty"),
    now: document.getElementById("atl-now"),
    day: document.getElementById("atl-day"),
    form: document.getElementById("trip"),
    gate: document.getElementById("gate"),
    chip: document.getElementById("concourse-chip"),
    letter: document.getElementById("concourse-letter"),
    gateError: document.getElementById("gate-error"),
    date: document.getElementById("board-date"),
    time: document.getElementById("board-time"),
    boardReadout: document.getElementById("board-readout"),
    boardError: document.getElementById("board-error"),
    formError: document.getElementById("form-error"),
    formStatus: document.getElementById("form-status"),
    go: document.getElementById("go-btn"),
    mapTitle: document.getElementById("map-title"),
    mapKicker: document.getElementById("map-kicker"),
    mapCaption: document.getElementById("map-caption"),
    mapHost: document.getElementById("map-host"),
    stage: document.getElementById("stage"),
    horizon: document.getElementById("horizon"),
    forecastFor: document.getElementById("forecast-for"),
    spotsKicker: document.getElementById("spots-kicker"),
    resultsTitle: document.getElementById("results-title"),
    spotsStatus: document.getElementById("spots-status"),
    resultsStatus: document.getElementById("results-status"),
    areaInfo: document.getElementById("area-info"),
    warnings: document.getElementById("warnings"),
    spots: document.getElementById("spots"),
    assumptionsList: document.getElementById("assumptions-list")
  };

  var dateFmt = new Intl.DateTimeFormat("en-US", { timeZone: TZ, weekday: "long", month: "short", day: "numeric" });
  var timeFmt = new Intl.DateTimeFormat("en-US", { timeZone: TZ, hour: "numeric", minute: "2-digit" });
  var clockFmt = new Intl.DateTimeFormat("en-US", { timeZone: TZ, hour: "numeric", minute: "2-digit" });
  var dayFmt = new Intl.DateTimeFormat("en-US", { timeZone: TZ, weekday: "short", month: "short", day: "numeric", timeZoneName: "short" });

  function zoneParts(date) {
    var dtf = new Intl.DateTimeFormat("en-US", {
      timeZone: TZ,
      hourCycle: "h23",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit"
    });
    var out = {};
    dtf.formatToParts(date).forEach(function (part) {
      if (part.type !== "literal") out[part.type] = part.value;
    });
    if (out.hour === "24") out.hour = "00";
    return out;
  }

  function zoneOffsetMs(date) {
    var p = zoneParts(date);
    var asUtc = Date.UTC(+p.year, +p.month - 1, +p.day, +p.hour, +p.minute, +p.second);
    return asUtc - date.getTime();
  }

  function atlantaToUtc(year, month, day, hour, minute) {
    var guess = Date.UTC(year, month - 1, day, hour, minute, 0);
    var utc = guess - zoneOffsetMs(new Date(guess));
    return new Date(guess - zoneOffsetMs(new Date(utc)));
  }

  function readBoarding() {
    if (!els.date.value || !els.time.value) return null;
    var d = els.date.value.split("-");
    var t = els.time.value.split(":");
    if (d.length < 3 || t.length < 2) return null;
    return atlantaToUtc(+d[0], +d[1], +d[2], +t[0], +t[1]);
  }

  function setError(el, message) {
    if (!message) {
      el.hidden = true;
      el.textContent = "";
      return;
    }
    el.hidden = false;
    el.textContent = message;
  }

  function crowdClass(index) {
    if (index == null || Number.isNaN(+index)) return "unknown";
    if (index <= 33) return "quiet";
    if (index <= 66) return "moderate";
    return "busy";
  }

  function crowdLabel(index) {
    var c = crowdClass(index);
    if (c === "quiet") return "less crowded";
    if (c === "moderate") return "moderate";
    if (c === "busy") return "busy";
    return "no estimate";
  }

  function cssEscape(value) {
    if (window.CSS && CSS.escape) return CSS.escape(value);
    return String(value).replace(/[^a-zA-Z0-9_-]/g, "\\$&");
  }

  function formatWalk(seconds) {
    if (seconds == null || Number.isNaN(+seconds)) return "walk time unavailable";
    var m = Math.max(1, Math.round(seconds / 60));
    return m + (m === 1 ? " min walk" : " min walk");
  }

  // Missing or unparseable API times render as "—" instead of throwing in Intl.
  function formatTime(iso) {
    if (!iso) return "—";
    var d = new Date(iso);
    return Number.isNaN(d.getTime()) ? "—" : timeFmt.format(d);
  }

  function crowdSummary(index) {
    if (index == null || Number.isNaN(+index)) return "no crowd estimate";
    return crowdLabel(index) + " (crowd " + index + ")";
  }

  function apiErrorDetail(body, fallback) {
    if (!body) return fallback;
    if (typeof body.detail === "string") return body.detail;
    if (Array.isArray(body.detail)) {
      return body.detail.map(function (item) { return item.msg || JSON.stringify(item); }).join(" ");
    }
    return fallback;
  }

  async function fetchJson(url, options) {
    var res = await fetch(url, options);
    var body = null;
    try { body = await res.json(); } catch (e) { body = null; }
    if (!res.ok) {
      var err = new Error(apiErrorDetail(body, "Request failed (" + res.status + ")"));
      err.status = res.status;
      err.body = body;
      throw err;
    }
    return body;
  }

  function paintClock() {
    var now = new Date();
    els.now.dateTime = now.toISOString();
    els.now.textContent = clockFmt.format(now);
    var parts = dayFmt.formatToParts(now);
    var zone = "";
    var day = [];
    parts.forEach(function (part) {
      if (part.type === "timeZoneName") zone = part.value;
      else if (part.type !== "literal") day.push(part.value);
    });
    els.day.textContent = day.join(" ") + (zone ? " · " + zone : "");
  }

  function paintReadout() {
    var instant = readBoarding();
    var text = instant
      ? dateFmt.format(instant) + " · " + timeFmt.format(instant) + " Atlanta"
      : "Choose a boarding date and time.";
    // This region is aria-live and repainted on a timer; only touch it when the text changes.
    if (els.boardReadout.textContent !== text) els.boardReadout.textContent = text;
  }

  function syncChip() {
    var value = els.gate.value.toUpperCase().replace(/[^A-Z0-9]/g, "").slice(0, 4);
    if (value !== els.gate.value) els.gate.value = value;
    var letter = value.charAt(0);
    if (letter === DEMO_CONCOURSE) {
      els.letter.textContent = letter;
      els.chip.hidden = false;
    } else {
      els.chip.hidden = true;
      els.letter.textContent = "";
    }
  }

  // Boarding fields start blank; only the earliest selectable date is set (Atlanta today).
  function initBoardingFields() {
    var today = zoneParts(new Date());
    els.date.min = today.year + "-" + today.month + "-" + today.day;
  }

  function setView(name) {
    state.view = name;
    els.app.setAttribute("data-view", name);
    els.results.hidden = name !== "results";
    els.form.hidden = name !== "input";
  }

  function gateInDemoRange(gate) {
    if (!GATE_RE.test(gate) || gate.charAt(0) !== DEMO_CONCOURSE) return false;
    var n = parseInt(gate.slice(1), 10);
    if (!state.graph || !state.graph.zones) return n >= 1 && n <= 39;
    for (var i = 0; i < state.graph.zones.length; i++) {
      var span = state.graph.zones[i].gate_range;
      if (span && n >= span[0] && n <= span[1]) return true;
    }
    return false;
  }

  async function loadConcourseB() {
    var graph = null;
    var graphErrors = [];

    if (!MOCK) {
      try {
        graph = await fetchJson("/api/graph");
        if (String(graph.concourse || "").toUpperCase() !== DEMO_CONCOURSE) {
          graphErrors.push("/api/graph returned concourse " + (graph.concourse || "?"));
          graph = null;
        }
      } catch (e) {
        graphErrors.push("/api/graph failed (" + (e.status || "network") + ")");
        graph = null;
      }
    }

    if (!graph) {
      try {
        graph = await fetchJson("atl_graph.b.json");
      } catch (e) {
        graphErrors.push("atl_graph.b.json failed");
        graph = null;
      }
    }

    if (graph && graph.zones) {
      state.graph = graph;
      state.mapReady = true;
      return true;
    }
    if (graphErrors.length) console.warn("Concourse B map load:", graphErrors.join("; "));
    state.mapReady = false;
    return false;
  }

  function zoneIdForGate(gate) {
    if (!gate || !state.graph || !state.graph.zones) return null;
    if (gate.charAt(0) !== DEMO_CONCOURSE) return null;
    var n = parseInt(gate.slice(1), 10);
    if (Number.isNaN(n)) return null;
    for (var i = 0; i < state.graph.zones.length; i++) {
      var span = state.graph.zones[i].gate_range;
      if (span && n >= span[0] && n <= span[1]) return state.graph.zones[i].id;
    }
    return null;
  }

  // Out-of-scope gates: stay on the input form, keep the Concourse B map as is.
  function showScopeMessage() {
    els.scopeNote.textContent = SCOPE_MESSAGE;
    els.scopeNote.hidden = false;
  }

  function hideScopeMessage() {
    els.scopeNote.hidden = true;
    els.scopeNote.textContent = "";
  }

  function forecastBucketCount() {
    if (!state.forecast || !state.forecast.zones || !state.forecast.zones.length) return 0;
    var lengths = state.forecast.zones.map(function (zone) {
      return zone.index && zone.index.length ? zone.index.length : 0;
    });
    return Math.max.apply(null, lengths.concat([0]));
  }

  function forecastSelectedInstant() {
    if (!state.forecast || !state.forecast.start) return null;
    var bucketMin = state.forecast.bucket_minutes || BUCKET_MIN;
    return new Date(new Date(state.forecast.start).getTime() + state.horizonBucket * bucketMin * 60000);
  }

  function paintForecastLabel() {
    var instant = forecastSelectedInstant();
    if (!instant) {
      els.forecastFor.textContent = "Forecast for —";
      return;
    }
    els.forecastFor.textContent = "Forecast for " + timeFmt.format(instant);
  }

  function syncHorizonControl() {
    var buckets = forecastBucketCount();
    if (!buckets) {
      els.horizon.disabled = true;
      els.horizon.min = "0";
      els.horizon.max = "0";
      els.horizon.value = "0";
      state.horizonBucket = 0;
      paintForecastLabel();
      return;
    }

    var maxBucket = buckets - 1;
    state.horizonBucket = Math.max(0, Math.min(maxBucket, state.horizonBucket || 0));
    els.horizon.disabled = false;
    els.horizon.min = "0";
    els.horizon.max = String(maxBucket);
    els.horizon.step = "1";
    els.horizon.value = String(state.horizonBucket);
    els.horizon.setAttribute(
      "aria-valuetext",
      "Forecast for " + timeFmt.format(forecastSelectedInstant())
    );
    paintForecastLabel();
  }

  // ---- Concourse B map ----------------------------------------------------------
  // Layout follows the official ATL Concourse B map: odd gates on the north side, even
  // gates on the south side, Centerpoint (Plane Train) between B18/B19 and B20/B21, and
  // B33+ around the far end. Positions are approximate, not surveyed.

  var MAP_BOX = { x: 0, y: 0, w: 1010, h: 300 };
  var HALL_Y = 150;
  var EDGE_N = 104;
  var EDGE_S = 196;
  var END_CAP = {
    33: { x: 880, y: 64, side: "n" }, 35: { x: 930, y: 64, side: "n" },
    34: { x: 880, y: 236, side: "s" }, 36: { x: 930, y: 236, side: "s" },
    37: { x: 950, y: 108, side: "e" }, 38: { x: 950, y: 150, side: "e" }, 39: { x: 950, y: 192, side: "e" }
  };

  function gateGeom(n) {
    if (!(n >= 1 && n <= 39)) return null;
    var g;
    if (n >= 33) g = END_CAP[n];
    else if (n <= 19) g = n % 2 ? { x: 70 + (n - 1) / 2 * 42, y: EDGE_N, side: "n" } : { x: 91 + (n - 2) / 2 * 42, y: EDGE_S, side: "s" };
    else g = n % 2 ? { x: 588 + (n - 21) / 2 * 52, y: EDGE_N, side: "n" } : { x: 566 + (n - 20) / 2 * 46, y: EDGE_S, side: "s" };
    var out = 16;
    var bridge = g.side === "n" ? { x: g.x, y: g.y - out } : g.side === "s" ? { x: g.x, y: g.y + out } : { x: g.x + out, y: g.y };
    var pill = g.side === "n" ? { x: g.x, y: bridge.y - 10 } : g.side === "s" ? { x: g.x, y: bridge.y + 10 } : { x: bridge.x + 17, y: g.y };
    return { n: n, x: g.x, y: g.y, side: g.side, bridge: bridge, pill: pill };
  }

  function travelerGate() {
    if (!state.gate || state.gate.charAt(0) !== DEMO_CONCOURSE) return null;
    return gateGeom(parseInt(state.gate.slice(1), 10));
  }

  function roundRect(x, y, w, h, r) {
    return "M" + (x + r) + "," + y + "H" + (x + w - r) + "Q" + (x + w) + "," + y + " " + (x + w) + "," + (y + r) +
      "V" + (y + h - r) + "Q" + (x + w) + "," + (y + h) + " " + (x + w - r) + "," + (y + h) +
      "H" + (x + r) + "Q" + x + "," + (y + h) + " " + x + "," + (y + h - r) +
      "V" + (y + r) + "Q" + x + "," + y + " " + (x + r) + "," + y + "Z";
  }

  // Seating areas sit inside the holdroom beside the gate named in the zone label.
  function nearGate(zone) {
    var m = /near\s+B(\d+)/i.exec(zone.label || "");
    return m ? parseInt(m[1], 10) : null;
  }

  function zoneGeom(zone) {
    switch (zone.id) {
      case "B-gates-1-10": return { d: "M58,104H270V196H58Q40,196 40,178V122Q40,104 58,104Z" };
      case "B-gates-11-20": return { d: "M270,104H577V196H270Z" };
      case "B-gates-21-30": return { d: "M577,104H820V196H577Z" };
      case "B-gates-31-39": return { d: "M820,104H860V82Q860,64 878,64H932Q950,64 950,82V218Q950,236 932,236H878Q860,236 860,218V196H820Z" };
      case "B-food-1": return { d: "M466,150V94Q466,80 480,80H534Q548,80 548,94V150Z", icon: "food", cx: 507, cy: 104, caption: "Food court", ax: 507, ay: 132 };
      case "B-shops-1": return { d: "M466,150H548V206Q548,220 534,220H480Q466,220 466,206Z", icon: "shop", cx: 507, cy: 174, caption: "Shops", ax: 507, ay: 168 };
      case "B-service": return { d: roundRect(689, 170, 30, 20, 6), icon: "info", cx: 704, cy: 180, ax: 704, ay: 170 };
    }
    if (zone.kind === "rest") {
      var g = gateGeom(nearGate(zone));
      if (!g || g.side === "e") return null;
      var y = g.side === "n" ? 110 : 170;
      return { d: roundRect(g.x - 19, y, 38, 20, 6), icon: "seat", cx: g.x, cy: y + 10, ax: g.x, ay: g.side === "n" ? y + 20 : y };
    }
    return null;
  }

  function placeName(id, fallback) {
    var zone = state.graph && state.graph.zones.find(function (z) { return z.id === id; });
    var label = (zone && zone.label) || fallback || id;
    var near = zone && zone.kind === "rest" ? nearGate(zone) : null;
    return near ? "B" + near + " seating" : label;
  }

  function escapeXml(value) {
    return String(value).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }

  var GLYPHS = {
    food: '<circle class="poi poi-food" r="9"/><path class="poi-mark" d="M-3.2,-5V5M-4.8,-5V-1.6Q-4.8,0 -3.2,0Q-1.6,0 -1.6,-1.6V-5M3,5V-5Q5,-4 5,0H3"/>',
    shop: '<circle class="poi poi-shop" r="9"/><path class="poi-mark" d="M-2,-2V-3.3Q-2,-5.3 0,-5.3Q2,-5.3 2,-3.3V-2"/><path class="poi-fill" d="M-4.6,-2H4.6L4,4.8H-4Z"/>',
    info: '<path class="glyph" d="M-1.2,-1.5H1.2V5H-1.2ZM0,-5.6A1.4,1.4 0 1 1 0,-2.8A1.4,1.4 0 1 1 0,-5.6Z"/>',
    seat: '<path class="glyph" d="M-6,0H6V4.5H-6ZM-4.5,-5H4.5V0H-4.5ZM-5,4.5H-3.5V6.5H-5ZM3.5,4.5H5V6.5H3.5Z"/>'
  };

  var HEAT_GRADIENTS = ["quiet", "moderate", "busy"].map(function (c) {
    return '<radialGradient id="heat-' + c + '">' +
      '<stop offset="0" style="stop-color:var(--zone-' + c + ');stop-opacity:0.9"/>' +
      '<stop offset="0.6" style="stop-color:var(--zone-' + c + ');stop-opacity:0.5"/>' +
      '<stop offset="1" style="stop-color:var(--zone-' + c + ');stop-opacity:0"/>' +
      "</radialGradient>";
  }).join("");

  // Grouped gate zones glow at each of their gates; other zones glow at their own center.
  function heatSpots(zone, geom) {
    if (zone.kind === "gates" && zone.gate_range) {
      var spots = [];
      for (var n = zone.gate_range[0]; n <= zone.gate_range[1]; n++) {
        var g = gateGeom(n);
        if (!g) continue;
        if (g.side === "n") spots.push({ x: g.x, y: g.y + 23, r: 21 });
        else if (g.side === "s") spots.push({ x: g.x, y: g.y - 23, r: 21 });
        else spots.push({ x: g.x - 24, y: g.y, r: 21 });
      }
      return spots;
    }
    if (geom.cx == null) return [];
    return [{ x: geom.cx, y: geom.cy, r: geom.caption ? 34 : 24 }];
  }

  function buildConcourseSvg() {
    var out = [];
    out.push('<svg xmlns="http://www.w3.org/2000/svg" class="atl-map" viewBox="0 0 ' + MAP_BOX.w + " " + MAP_BOX.h + '">');

    out.push('<g class="train" aria-hidden="true"><line x1="507" y1="0" x2="507" y2="300"/>' +
      '<text x="515" y="14">Plane Train · A, T, baggage claim</text>' +
      '<text x="515" y="293">Plane Train · C, D, E, F</text></g>');

    var bldgPaths = [
      "M58,104H860V82Q860,64 878,64H932Q950,64 950,82V218Q950,236 932,236H878Q860,236 860,218V196H58Q40,196 40,178V122Q40,104 58,104Z",
      roundRect(466, 80, 82, 140, 14)
    ];
    out.push("<defs>" + HEAT_GRADIENTS +
      '<clipPath id="bldg-clip">' + bldgPaths.map(function (d) { return '<path d="' + d + '"/>'; }).join("") + "</clipPath></defs>");
    bldgPaths.forEach(function (d) { out.push('<path class="bldg" d="' + d + '"/>'); });

    var gates = [];
    var spots = [];
    state.graph.zones.forEach(function (zone) {
      var geom = zoneGeom(zone);
      if (!geom) return;
      (zone.kind === "gates" ? gates : spots).push({ zone: zone, geom: geom });
    });

    // Circular heat glows, clipped to the concourse; painted per zone by paintHeatmap().
    var heat = '<g id="heat-layer" clip-path="url(#bldg-clip)" aria-hidden="true">';
    gates.concat(spots).forEach(function (item) {
      heatSpots(item.zone, item.geom).forEach(function (c) {
        heat += '<circle class="heat" data-zone="' + escapeXml(item.zone.id) + '" cx="' + c.x + '" cy="' + c.y + '" r="' + c.r + '"/>';
      });
    });
    out.push(heat + "</g>");

    gates.concat(spots).forEach(function (item) {
      var geom = item.geom;
      var html = '<g id="' + escapeXml(item.zone.id) + '" class="zone zone-' + escapeXml(item.zone.kind) + '">' +
        "<title>" + escapeXml(placeName(item.zone.id)) + "</title>" +
        '<path class="zone-shape" d="' + geom.d + '"/>';
      if (geom.icon) html += '<g class="icon" transform="translate(' + geom.cx + "," + geom.cy + ')">' + GLYPHS[geom.icon] + "</g>";
      if (geom.caption) html += '<text class="caption" x="' + geom.cx + '" y="' + (geom.cy + 22) + '">' + escapeXml(geom.caption) + "</text>";
      out.push(html + "</g>");
    });

    out.push('<text class="cp-label" x="507" y="70">Centerpoint</text>');
    out.push('<g id="route-layer"></g>');

    for (var n = 1; n <= 39; n++) {
      var g = gateGeom(n);
      out.push('<g class="gate" data-gate="B' + n + '"><title>Gate B' + n + "</title>" +
        '<line class="bridge" x1="' + g.x + '" y1="' + g.y + '" x2="' + g.bridge.x + '" y2="' + g.bridge.y + '"/>' +
        '<rect x="' + (g.pill.x - 17) + '" y="' + (g.pill.y - 9.5) + '" width="34" height="19" rx="9.5"/>' +
        '<text x="' + g.pill.x + '" y="' + g.pill.y + '">B' + n + "</text></g>");
    }

    out.push("</svg>");
    return out.join("");
  }

  function renderBMap() {
    state.activeConcourse = DEMO_CONCOURSE;
    els.mapTitle.textContent = "Concourse B";
    els.mapKicker.textContent = state.gate ? "Gate " + state.gate : "ATL";
    if (!state.mapReady) {
      els.mapCaption.hidden = false;
      els.mapHost.hidden = true;
      els.mapHost.innerHTML = "";
      els.mapCaption.textContent = "The Concourse B map could not be loaded.";
      syncHorizonControl();
      return;
    }

    els.mapCaption.hidden = true;
    els.mapHost.hidden = false;
    els.mapHost.innerHTML = buildConcourseSvg();
    syncHorizonControl();

    var svg = els.mapHost.querySelector("svg");
    if (svg) {
      // A group, not an image: the zones inside are focusable buttons.
      svg.setAttribute("role", "group");
      svg.setAttribute("aria-label", "Map of ATL Concourse B, gates B1 to B39");
      state.baseBox = { x: MAP_BOX.x, y: MAP_BOX.y, w: MAP_BOX.w, h: MAP_BOX.h };
      state.box = { x: MAP_BOX.x, y: MAP_BOX.y, w: MAP_BOX.w, h: MAP_BOX.h };
      state.zoomed = false;
    }
    els.mapReset.hidden = true;

    paintHeatmap();
    paintSelection();
  }

  // ---- Zoom (SVG viewBox) ----------------------------------------------------

  function applyBox(box) {
    var svg = els.mapHost.querySelector("svg");
    if (!svg) return;
    state.box = { x: box.x, y: box.y, w: box.w, h: box.h };
    svg.setAttribute("viewBox", box.x + " " + box.y + " " + box.w + " " + box.h);
  }

  function animateBox(target) {
    if (state.zoomFrame) cancelAnimationFrame(state.zoomFrame);
    var reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduce || !state.box) {
      applyBox(target);
      return;
    }
    var from = { x: state.box.x, y: state.box.y, w: state.box.w, h: state.box.h };
    var start = performance.now();
    var duration = 520;
    function ease(t) { return t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2; }
    function step(now) {
      var t = Math.min(1, (now - start) / duration);
      var k = ease(t);
      applyBox({
        x: from.x + (target.x - from.x) * k,
        y: from.y + (target.y - from.y) * k,
        w: from.w + (target.w - from.w) * k,
        h: from.h + (target.h - from.h) * k
      });
      if (t < 1) state.zoomFrame = requestAnimationFrame(step);
      else state.zoomFrame = 0;
    }
    state.zoomFrame = requestAnimationFrame(step);
  }

  function zoneBBox(zoneId) {
    var group = els.mapHost.querySelector("#" + cssEscape(zoneId));
    if (!group) return null;
    var shape = group.querySelector(".zone-shape");
    if (!shape || !shape.getBBox) return null;
    var b = shape.getBBox();
    return { x: b.x, y: b.y, w: b.width, h: b.height };
  }

  function zoomBoxFor(zoneId) {
    var base = state.baseBox;
    var focus = zoneBBox(zoneId);
    if (!base || !focus) return null;

    var gate = travelerGate();
    if (gate) {
      var pill = { x: gate.pill.x - 20, y: gate.pill.y - 12, w: 40, h: 24 };
      var x1 = Math.min(focus.x, pill.x);
      var y1 = Math.min(focus.y, pill.y);
      var x2 = Math.max(focus.x + focus.w, pill.x + pill.w);
      var y2 = Math.max(focus.y + focus.h, pill.y + pill.h);
      focus = { x: x1, y: y1, w: x2 - x1, h: y2 - y1 };
    }

    // Keep both rows of gate numbers in view: never shorter than the holdrooms plus pills.
    var aspect = base.w / base.h;
    var h = Math.max(190, focus.h + 40);
    var w = Math.max(h * aspect, focus.w + 140);
    h = w / aspect;
    if (w >= base.w) return { x: base.x, y: base.y, w: base.w, h: base.h };

    var cx = focus.x + focus.w / 2;
    var cy = Math.max(focus.y + focus.h / 2, HALL_Y - 10);
    return {
      x: Math.max(base.x, Math.min(base.x + base.w - w, cx - w / 2)),
      y: Math.max(base.y, Math.min(base.y + base.h - h, cy - h / 2)),
      w: w,
      h: h
    };
  }

  function zoomToZone(zoneId) {
    var box = zoomBoxFor(zoneId);
    if (!box) return;
    state.zoomed = true;
    els.mapReset.hidden = false;
    animateBox(box);
  }

  function resetZoom() {
    if (!state.baseBox) return;
    state.zoomed = false;
    els.mapReset.hidden = true;
    animateBox(state.baseBox);
  }

  // ---- Walk route: from the traveler's gate along the hall to the spot ---------

  function paintRoute(spot) {
    var layer = els.mapHost.querySelector("#route-layer");
    if (!layer) return;
    layer.replaceChildren();
    var gate = travelerGate();
    var zone = spot && state.graph && state.graph.zones.find(function (z) { return z.id === spot.id; });
    var geom = zone ? zoneGeom(zone) : null;
    if (!gate || !geom || geom.ax == null) return;

    var pts = [[gate.x, gate.y]];
    if (gate.side === "e") pts.push([905, gate.y], [905, HALL_Y]);
    else pts.push([gate.x, HALL_Y]);
    pts.push([geom.ax, HALL_Y], [geom.ax, geom.ay]);
    var d = pts.map(function (p, i) { return (i ? "L" : "M") + p[0] + "," + p[1]; }).join("");

    var ns = "http://www.w3.org/2000/svg";
    ["route-casing", "route-line"].forEach(function (cls) {
      var path = document.createElementNS(ns, "path");
      path.setAttribute("class", cls);
      path.setAttribute("d", d);
      layer.appendChild(path);
    });
    var end = document.createElementNS(ns, "circle");
    end.setAttribute("class", "route-end");
    end.setAttribute("cx", geom.ax);
    end.setAttribute("cy", geom.ay);
    end.setAttribute("r", "4.5");
    layer.appendChild(end);
  }

  function forecastIndexForZone(zoneId) {
    if (!state.forecast || !state.forecast.zones) return null;
    var zone = null;
    for (var i = 0; i < state.forecast.zones.length; i++) {
      if (state.forecast.zones[i].id === zoneId) {
        zone = state.forecast.zones[i];
        break;
      }
    }
    if (!zone || !zone.index || !zone.index.length) return null;
    var bucket = Math.max(0, Math.min(zone.index.length - 1, state.horizonBucket || 0));
    var value = zone.index[bucket];
    return value == null || Number.isNaN(+value) ? null : +value;
  }

  function paintHeatmap() {
    if (!state.mapReady || !state.graph || state.activeConcourse !== DEMO_CONCOURSE) return;
    var svg = els.mapHost.querySelector("svg");
    if (!svg) return;

    state.graph.zones.forEach(function (zone) {
      var group = els.mapHost.querySelector("#" + cssEscape(zone.id));
      if (!group) return;
      var shape = group.querySelector(".zone-shape") || group.querySelector("rect");
      if (!shape) return;
      var idx = forecastIndexForZone(zone.id);
      var level = crowdClass(idx);
      // Crowd color lives only on the circular heat glows; zone shapes stay neutral and clickable.
      Array.prototype.forEach.call(svg.querySelectorAll('.heat[data-zone="' + zone.id + '"]'), function (c) {
        c.setAttribute("fill", level === "unknown" ? "none" : "url(#heat-" + level + ")");
      });
      shape.setAttribute("data-crowd", idx == null ? "na" : String(idx));
      shape.setAttribute("tabindex", "0");
      shape.setAttribute("role", "button");
      shape.setAttribute(
        "aria-label",
        placeName(zone.id) + (idx == null ? ", no crowd estimate" : ", crowd index " + idx + ", " + crowdLabel(idx))
      );
      shape.onclick = function () { selectZone(zone.id); };
      shape.onkeydown = function (event) {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          selectZone(zone.id);
        }
      };
    });
  }

  function zoneDef(zoneId) {
    return (state.graph && state.graph.zones.find(function (z) { return z.id === zoneId; })) || null;
  }

  function recommendedSpotForZone(zoneId) {
    if (!state.recommend || !state.recommend.spots) return null;
    var zone = zoneDef(zoneId);
    // A grouped gate zone is not itself a seating area, so never map it onto a spot via zone_id.
    var byZone = zone && zone.kind !== "gates";
    return state.recommend.spots.find(function (s) {
      return s.id === zoneId || (byZone && s.zone_id === zoneId);
    }) || null;
  }

  function selectZone(zoneId) {
    var match = recommendedSpotForZone(zoneId);
    if (match) {
      selectSpot(match.id, { focus: true });
      return;
    }
    // Not a ranked recommendation: describe the area, keep the current pick as is.
    paintAreaInfo(zoneId);
  }

  function announceResults(text) {
    els.resultsStatus.textContent = text;
  }

  // opts.quiet: refresh the text without a screen-reader announcement (slider scrubbing).
  function paintAreaInfo(zoneId, opts) {
    state.inspectedZoneId = zoneId || null;
    els.areaInfo.setAttribute("aria-live", opts && opts.quiet ? "off" : "polite");
    Array.prototype.forEach.call(els.mapHost.querySelectorAll(".zone-shape.is-inspected"), function (el) {
      el.classList.remove("is-inspected");
    });
    if (!zoneId) {
      els.areaInfo.hidden = true;
      els.areaInfo.textContent = "";
      return;
    }
    var group = els.mapHost.querySelector("#" + cssEscape(zoneId));
    var shape = group && group.querySelector(".zone-shape");
    if (shape) shape.classList.add("is-inspected");

    var idx = forecastIndexForZone(zoneId);
    var instant = forecastSelectedInstant();
    var parts = [placeName(zoneId)];
    parts.push(idx == null
      ? "No crowd estimate" + (state.forecast ? " for this area" : " yet")
      : crowdLabelTitle(idx) + " (crowd " + idx + ")" + (instant ? " at " + timeFmt.format(instant) : ""));
    if (state.recommend && state.recommend.spots && state.recommend.spots.length) {
      parts.push("Not one of your recommended spots");
    }
    els.areaInfo.textContent = parts.join(" · ") + ".";
    els.areaInfo.hidden = false;
  }

  function paintSelection() {
    if (!els.mapHost) return;
    Array.prototype.forEach.call(els.mapHost.querySelectorAll(".zone-shape"), function (el) {
      el.classList.remove("is-selected");
      el.classList.remove("is-gate");
    });
    Array.prototype.forEach.call(els.spots.querySelectorAll(".spot"), function (el) {
      el.classList.toggle("is-selected", el.getAttribute("data-spot-id") === state.selectedSpotId);
    });

    Array.prototype.forEach.call(els.mapHost.querySelectorAll(".gate"), function (el) {
      el.classList.toggle("is-mine", el.getAttribute("data-gate") === state.gate);
    });

    var recommendedIds = {};
    ((state.recommend && state.recommend.spots) || []).forEach(function (s) { recommendedIds[s.id] = true; });
    Array.prototype.forEach.call(els.mapHost.querySelectorAll(".zone"), function (group) {
      var shape = group.querySelector(".zone-shape");
      if (shape) shape.classList.toggle("is-recommended", !!recommendedIds[group.id]);
    });

    var spot = selectedSpot();
    paintPick(spot);
    paintRoute(spot);

    if (!state.selectedSpotId) return;
    var group = els.mapHost.querySelector("#" + cssEscape(state.selectedSpotId));
    if (group) {
      var shape = group.querySelector(".zone-shape") || group.querySelector("rect");
      if (shape) shape.classList.add("is-selected");
    }
  }

  function selectedSpot() {
    if (!state.recommend || !state.recommend.spots || !state.selectedSpotId) return null;
    return state.recommend.spots.find(function (s) { return s.id === state.selectedSpotId; }) || null;
  }

  // Shortest walk among spots that are actually less crowded; otherwise the top-ranked spot.
  function closestSpot(spots) {
    var best = null;
    spots.forEach(function (spot) {
      if (spot.walk_s_from_gate == null) return;
      if (crowdClass(spot.crowd_index_now) !== "quiet") return;
      if (!best || spot.walk_s_from_gate < best.walk_s_from_gate) best = spot;
    });
    return best || spots[0] || null;
  }

  function paintPick(spot) {
    if (!spot) {
      els.pick.hidden = true;
      els.listTitle.hidden = true;
      return;
    }
    var spots = (state.recommend && state.recommend.spots) || [];
    var nearest = closestSpot(spots);
    els.pick.hidden = false;
    els.listTitle.hidden = spots.length < 2;
    var isQuiet = crowdClass(spot.crowd_index_now) === "quiet";
    els.pickLabel.textContent = !isQuiet
      ? "Seating option"
      : nearest && nearest.id === spot.id ? "Closest quiet space" : "Quiet space";
    els.pickName.textContent = placeName(spot.id, spot.label);
    els.pickWalk.textContent = spot.walk_s_from_gate == null ? "—" : formatWalk(spot.walk_s_from_gate).replace(" walk", "");
    els.pickLeave.textContent = formatTime(spot.leave_by);
    els.pickCountdown.setAttribute("data-leave-by", spot.leave_by || "");
    els.pickCountdown.textContent = leaveCountdown(spot.leave_by);
    els.pickCrowd.textContent =
      spot.crowd_index_now == null ? "No estimate" : crowdLabelTitle(spot.crowd_index_now);

    var notes = [];
    if (spot.stay_minutes != null && spot.stay_minutes > 0) notes.push("You can rest here for about " + spot.stay_minutes + " min.");
    if (spot.reasons && spot.reasons[0]) notes.push(spot.reasons[0] + ".");
    els.pickNote.textContent = notes.join(" ");

    var q = encodeURIComponent(AIRPORT_QUERY);
    els.linkGoogle.href = "https://www.google.com/maps/search/?api=1&query=" + q;
    els.linkApple.href = "https://maps.apple.com/?q=" + q;
    els.linkGoogle.textContent = "Open Concourse B in Google Maps";
    els.linkApple.textContent = "Apple Maps";
  }

  function crowdLabelTitle(index) {
    var l = crowdLabel(index);
    return l.charAt(0).toUpperCase() + l.slice(1);
  }

  // opts.zoom: animate the map to this spot. opts.focus: move keyboard focus to its list row.
  function selectSpot(spotId, opts) {
    opts = opts || {};
    state.selectedSpotId = spotId;
    paintAreaInfo(null);
    paintSelection();
    var spot = selectedSpot();
    if (spot && opts.announce !== false) {
      announceResults(placeName(spot.id, spot.label) + " selected. " + formatWalk(spot.walk_s_from_gate) +
        ", leave by " + formatTime(spot.leave_by) + ".");
    }
    if (opts.zoom !== false) zoomToZone(spotId);
    if (opts.focus) {
      var row = els.spots.querySelector('[data-spot-id="' + spotId + '"]');
      if (row) row.focus({ preventScroll: true });
    }
  }

  function paintWarnings(list) {
    els.warnings.replaceChildren();
    if (!list || !list.length) {
      els.warnings.hidden = true;
      return;
    }
    els.warnings.hidden = false;
    list.forEach(function (text) {
      var li = document.createElement("li");
      li.textContent = text;
      els.warnings.appendChild(li);
    });
  }

  function leaveCountdown(iso) {
    if (!iso) return "—";
    var leave = new Date(iso);
    if (Number.isNaN(leave.getTime())) return "—";
    var mins = Math.round((leave.getTime() - Date.now()) / 60000);
    if (mins < -1) return "passed";
    if (mins <= 1) return "now";
    if (mins < 60) return mins + " min left";
    var h = Math.floor(mins / 60);
    var m = mins % 60;
    return h + "h " + m + "m left";
  }

  function paintSpots() {
    els.spots.replaceChildren();
    var rec = state.recommend;
    paintPick(null);
    if (!rec) {
      els.spotsStatus.textContent = "Enter a gate and boarding time to see quiet places nearby.";
      paintWarnings([]);
      return;
    }

    if (rec.supported === false) {
      els.spotsStatus.textContent = SCOPE_MESSAGE;
      paintWarnings(rec.warnings || []);
      return;
    }

    if (!rec.spots || !rec.spots.length) {
      els.spotsStatus.textContent = "No quiet spots leave enough time for this boarding.";
      paintWarnings(rec.warnings || []);
      return;
    }

    els.spotsStatus.textContent = "Top quiet places near gate " + rec.gate + ".";
    paintWarnings(rec.warnings || []);

    rec.spots.forEach(function (spot, index) {
      var li = document.createElement("li");
      li.className = "spot";
      li.tabIndex = 0;
      li.setAttribute("data-spot-id", spot.id);
      li.setAttribute("role", "button");
      li.setAttribute(
        "aria-label",
        placeName(spot.id, spot.label) + ", " + formatWalk(spot.walk_s_from_gate) + ", " +
          crowdSummary(spot.crowd_index_now) + ", leave by " + formatTime(spot.leave_by)
      );

      var rank = document.createElement("span");
      rank.className = "rank";
      rank.textContent = String(index + 1);

      var body = document.createElement("div");
      body.className = "spot-body";
      var name = document.createElement("p");
      name.className = "spot-name";
      name.textContent = placeName(spot.id, spot.label);
      var meta = document.createElement("p");
      meta.className = "spot-meta";
      meta.textContent = formatWalk(spot.walk_s_from_gate) + " · " + crowdSummary(spot.crowd_index_now);
      body.append(name, meta);

      var leave = document.createElement("p");
      leave.className = "leave";
      leave.innerHTML = "<span>Leave by</span>";
      var strong = document.createElement("strong");
      strong.textContent = formatTime(spot.leave_by);
      var cd = document.createElement("span");
      cd.className = "countdown";
      cd.setAttribute("data-leave-by", spot.leave_by || "");
      cd.textContent = leaveCountdown(spot.leave_by);
      leave.append(strong, cd);

      li.append(rank, body, leave);
      li.addEventListener("click", function () { selectSpot(spot.id); });
      li.addEventListener("keydown", function (event) {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          selectSpot(spot.id);
        }
      });
      els.spots.appendChild(li);
    });

    // Default selection is the closest quiet space; the map zooms to it.
    if (!state.selectedSpotId) {
      var first = closestSpot(rec.spots);
      if (first) selectSpot(first.id, { announce: false });
    } else {
      paintSelection();
    }
  }

  function paintCountdowns() {
    Array.prototype.forEach.call(document.querySelectorAll("[data-leave-by]"), function (el) {
      el.textContent = leaveCountdown(el.getAttribute("data-leave-by"));
    });
  }

  function classifySource(ds, usingMock) {
    if (usingMock || MOCK) {
      return {
        kind: "sample",
        badge: "SAMPLE DATA",
        detail: "Demo values for testing. Not a live AeroAPI flight feed."
      };
    }
    if (!ds) {
      return {
        kind: "unknown",
        badge: "Not loaded",
        detail: "Source details appear after you search."
      };
    }

    var provider = String(ds.provider || "").toLowerCase();
    var synthetic = !!ds.synthetic || provider === "snapshot" || provider === "sample" || provider === "mock";
    var pulled = ds.pulled_at
      ? new Date(ds.pulled_at).toLocaleString("en-US", { timeZone: TZ, month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })
      : null;

    if (synthetic) {
      return {
        kind: "sample",
        badge: "SAMPLE DATA",
        detail:
          "SAMPLE DATA" +
          (pulled ? " · updated " + pulled + " Atlanta" : "") +
          ". Demo or recorded flights, not a live AeroAPI feed."
      };
    }

    var label = provider === "aeroapi" ? "AeroAPI" : (ds.provider || "Live source");
    return {
      kind: "live",
      badge: label,
      detail:
        "Flight schedules from " + label +
        (pulled ? " · updated " + pulled + " Atlanta" : "") +
        "."
    };
  }

  function paintSource() {
    var info = classifySource(state.dataSource, state.usingMock);
    els.mockBanner.hidden = info.kind !== "sample";
    els.mockBanner.textContent = state.usingMock || MOCK
      ? "Demo mode. These values are for testing — not live airport data."
      : "Sample data. These flights are synthetic or recorded — not live airport data.";

    els.sourceBadge.hidden = info.kind === "unknown";
    els.sourceBadge.className = "source-badge" + (info.kind === "sample" ? " is-sample" : info.kind === "live" ? " is-live" : "");
    els.sourceBadgeValue.textContent = info.badge;

    els.aboutSource.textContent = info.detail;

    els.assumptionsList.replaceChildren();
    if (state.assumptions && state.assumptions.parameters && state.assumptions.parameters.length) {
      els.aboutAssumptionsVersion.textContent = state.assumptions.version ? "(" + state.assumptions.version + ")" : "";
      els.assumptionsEmpty.hidden = true;
      state.assumptions.parameters.forEach(function (param) {
        var li = document.createElement("li");
        var label = document.createElement("span");
        label.textContent = param.label || param.key;
        var value = document.createElement("span");
        value.textContent = String(param.value) + (param.unit ? " " + param.unit : "");
        li.append(label, value);
        if (param.note) {
          var note = document.createElement("span");
          note.className = "note";
          note.textContent = param.note;
          li.appendChild(note);
        }
        els.assumptionsList.appendChild(li);
      });
    } else {
      els.aboutAssumptionsVersion.textContent = "";
      els.assumptionsEmpty.hidden = false;
    }
  }

  function mockForecast(startIso) {
    if (!state.graph || !state.graph.zones) return null;
    // Sample synthetic series for demo only — not measured ATL crowd data.
    var buckets = 37;
    return {
      concourse: DEMO_CONCOURSE,
      bucket_minutes: BUCKET_MIN,
      start: startIso,
      zones: state.graph.zones.map(function (zone, zi) {
        var salt = 0;
        for (var c = 0; c < zone.id.length; c++) salt += zone.id.charCodeAt(c);
        var phase = (salt % 13) + zi * 2;
        var index = [];
        for (var i = 0; i < buckets; i++) {
          var wave =
            48 +
            34 * Math.sin((i + phase) / 3.1) +
            14 * Math.cos((i * 0.55) + (salt % 7)) +
            ((salt + i * 3) % 11) - 5;
          index.push(Math.max(0, Math.min(100, Math.round(wave))));
        }
        return {
          id: zone.id,
          label: zone.label,
          capacity: zone.capacity,
          index: index
        };
      }),
      unassigned_flights: 0,
      unknown_aircraft_flights: 0,
      assumptions_version: "mock",
      data_source: { provider: "mock", pulled_at: startIso, synthetic: true }
    };
  }

  // Shortest walk (sum of graph edge walk_s) from a start node to every node.
  // Edge values are the graph's own hand estimates, not measured walking times.
  function shortestPaths(startId) {
    var out = {};
    if (!startId || !state.graph || !state.graph.edges) return out;
    var adj = {};
    state.graph.edges.forEach(function (e) {
      (adj[e.a] = adj[e.a] || []).push({ to: e.b, w: e.walk_s });
      (adj[e.b] = adj[e.b] || []).push({ to: e.a, w: e.walk_s });
    });
    var dist = {};
    var prev = {};
    var todo = [startId];
    dist[startId] = 0;
    var done = {};
    while (todo.length) {
      todo.sort(function (a, b) { return dist[a] - dist[b]; });
      var cur = todo.shift();
      if (done[cur]) continue;
      done[cur] = true;
      (adj[cur] || []).forEach(function (n) {
        var d = dist[cur] + n.w;
        if (dist[n.to] == null || d < dist[n.to]) {
          dist[n.to] = d;
          prev[n.to] = cur;
          todo.push(n.to);
        }
      });
    }
    Object.keys(dist).forEach(function (id) {
      var route = [id];
      while (prev[route[0]]) route.unshift(prev[route[0]]);
      out[id] = { walk_s: dist[id], route: route };
    });
    return out;
  }

  function mockRecommend(gate, boardingIso) {
    if (!state.graph || !state.graph.zones) {
      return {
        gate: gate,
        concourse: DEMO_CONCOURSE,
        boarding: boardingIso,
        supported: false,
        spots: [],
        warnings: ["Sample map data is not loaded yet."],
        assumptions_version: "mock",
        data_source: { provider: "mock", pulled_at: new Date().toISOString(), synthetic: true }
      };
    }

    var rest = state.graph.zones.filter(function (z) { return z.kind === "rest"; });
    var boarding = new Date(boardingIso);
    var gateZone = zoneIdForGate(gate);
    var paths = shortestPaths(gateZone);
    var bufferMs = 10 * 60 * 1000;
    var nowMs = Date.now();
    var ranked = rest.filter(function (zone) {
      // Only candidates with a known walk whose leave-by is still ahead of now.
      var path = paths[zone.id];
      if (!path || path.walk_s == null) return false;
      return boarding.getTime() - path.walk_s * 1000 - bufferMs > nowMs;
    }).map(function (zone) {
      var nowIdx = forecastIndexForZone(zone.id);
      var peak = nowIdx;
      if (state.forecast && state.forecast.zones) {
        var fz = state.forecast.zones.find(function (z) { return z.id === zone.id; });
        if (fz && fz.index && fz.index.length) {
          peak = Math.max.apply(null, fz.index);
        }
      }
      var path = paths[zone.id] || null;
      return {
        id: zone.id,
        label: zone.label,
        zone_id: zone.near_zone || zone.id,
        crowd_index_now: nowIdx,
        crowd_index_peak: peak,
        walk_s_from_gate: path ? path.walk_s : null,
        walk_s_back: path ? path.walk_s : null,
        route: path ? path.route : [zone.id],
        // Lower crowd and shorter walk both help; walk counts lightly.
        score: 100 - (nowIdx == null ? 60 : nowIdx) - (path ? path.walk_s / 15 : 10),
        reasons: [
          nowIdx != null && nowIdx <= 33
            ? "Less crowded seating with time to walk back"
            : "Seating nearby with a workable leave-by time"
        ]
      };
    }).sort(function (a, b) {
      return b.score - a.score;
    });
    // Sample recommendations skip spots forecast to be busy right now (unless all are).
    var notBusy = ranked.filter(function (s) { return crowdClass(s.crowd_index_now) !== "busy"; });
    ranked = (notBusy.length ? notBusy : ranked.slice(0, 1)).slice(0, 3).map(function (spot) {
      var leave = new Date(boarding.getTime() - spot.walk_s_from_gate * 1000 - bufferMs);
      spot.leave_by = leave.toISOString();
      spot.stay_minutes = Math.max(0, Math.round((leave.getTime() - nowMs) / 60000));
      return spot;
    });

    return {
      gate: gate,
      concourse: DEMO_CONCOURSE,
      boarding: boardingIso,
      supported: true,
      spots: ranked,
      warnings: [],
      assumptions_version: "mock",
      data_source: { provider: "mock", pulled_at: new Date().toISOString(), synthetic: true }
    };
  }

  async function loadAssumptions() {
    if (MOCK || state.usingMock) {
      state.assumptions = {
        version: "mock",
        parameters: [
          { key: "load_factor", label: "Seats filled", value: 0.85, unit: "fraction", note: "Mock default" },
          { key: "leave_buffer_min", label: "Safety buffer before boarding", value: 10, unit: "min", note: "Mock default" }
        ]
      };
      return;
    }
    try {
      state.assumptions = await fetchJson("/api/assumptions");
    } catch (e) {
      /* keep prior assumptions if any */
    }
  }

  async function runSearch(gate, boarding) {
    state.gate = gate;
    state.boarding = boarding;
    state.selectedSpotId = null;
    state.horizonBucket = 0;
    state.loading = true;
    state.usingMock = false;
    state.dataSource = null;
    paintAreaInfo(null);
    announceResults("");
    els.go.disabled = true;
    els.go.textContent = "Finding…";
    setError(els.formError, "");
    hideScopeMessage();

    if (gate.charAt(0) !== DEMO_CONCOURSE) {
      showScopeMessage();
      els.formStatus.textContent = SCOPE_MESSAGE;
      els.go.disabled = false;
      els.go.textContent = "Find quiet spots";
      state.loading = false;
      return;
    }

    els.formStatus.textContent = "Loading forecast and recommendations for gate " + gate + ".";

    if (!state.mapReady) {
      await loadConcourseB();
    }

    var boardingIso = boarding.toISOString();
    var startIso = new Date().toISOString();

    try {
      await loadAssumptions();

      if (MOCK) {
        state.usingMock = true;
        if (!state.graph) throw new Error("Sample Concourse B map data failed to load.");
        state.forecast = mockForecast(startIso);
        if (!state.forecast || !state.forecast.zones || !state.forecast.zones.length) {
          throw new Error("Sample crowd forecast could not be built for Concourse B.");
        }
        state.recommend = mockRecommend(gate, boardingIso);
        state.dataSource = state.recommend.data_source;
      } else {
        var forecastPromise = fetchJson(
          "/api/forecast?concourse=" + encodeURIComponent(DEMO_CONCOURSE) +
          "&start=" + encodeURIComponent(startIso) +
          "&hours=3"
        );
        var recommendPromise = fetchJson(
          "/api/recommend?gate=" + encodeURIComponent(gate) +
          "&boarding=" + encodeURIComponent(boardingIso) +
          "&limit=3"
        );

        var forecastResult = null;
        var recommendResult = null;
        var forecastErr = null;
        var recommendErr = null;

        try { forecastResult = await forecastPromise; }
        catch (e) { forecastErr = e; }
        try { recommendResult = await recommendPromise; }
        catch (e) { recommendErr = e; }

        if (recommendErr) throw recommendErr;

        state.recommend = recommendResult;
        state.dataSource = recommendResult.data_source || null;

        if (forecastResult) {
          state.forecast = forecastResult;
          if (!state.dataSource) state.dataSource = forecastResult.data_source;
        } else {
          state.forecast = null;
          if (forecastErr && forecastErr.status !== 422) {
            setError(els.formError, "Quiet spots loaded, but the crowd map is unavailable right now.");
          }
        }
      }

      // Results header + essentials on the left; heatmap + zoom on the right.
      els.spotsKicker.textContent = "Boards " + timeFmt.format(boarding) + " Atlanta";
      els.resultsTitle.textContent = "Gate " + gate;
      setView("results");
      renderBMap();
      syncHorizonControl();
      paintHeatmap();
      paintSpots();
      paintSource();
      els.formStatus.textContent = "Results ready for gate " + gate + ".";
      var pick = selectedSpot();
      announceResults(
        "Results ready for gate " + gate + ". " +
        (pick
          ? placeName(pick.id, pick.label) + ", " + formatWalk(pick.walk_s_from_gate) + ", leave by " + formatTime(pick.leave_by) + "."
          : els.spotsStatus.textContent)
      );
      els.resultsTitle.setAttribute("tabindex", "-1");
      els.resultsTitle.focus({ preventScroll: true });
      if (window.matchMedia("(max-width: 899px)").matches) {
        var reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
        els.app.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" });
      }
    } catch (err) {
      state.forecast = null;
      state.recommend = null;
      state.dataSource = null;
      state.usingMock = false;
      setView("input");
      syncHorizonControl();
      paintSpots();
      paintSource();
      renderBMap();
      var msg = err && err.message ? err.message : "Could not load recommendations.";
      if (err && err.status === 503) {
        msg = "Forecast service is unavailable right now. For a local demo, open the page with ?mock=1.";
      }
      if (!MOCK && (err.status === 404 || /failed \(404\)/.test(msg))) {
        msg = "Forecast API is not available on this preview server. Open with ?mock=1 for sample data.";
      }
      setError(els.formError, msg);
      els.formStatus.textContent = "Request failed.";
    } finally {
      state.loading = false;
      els.go.disabled = false;
      els.go.textContent = "Find quiet spots";
    }
  }

  function validate() {
    var gate = els.gate.value.trim().toUpperCase();
    var instant = readBoarding();
    var ok = true;

    if (!GATE_RE.test(gate)) {
      setError(els.gateError, "Enter a gate such as B22.");
      ok = false;
    } else if (gate.charAt(0) === DEMO_CONCOURSE && !gateInDemoRange(gate)) {
      setError(els.gateError, "Concourse B gates in this demo are B1–B39.");
      ok = false;
    } else {
      setError(els.gateError, "");
    }

    if (!instant) {
      setError(els.boardError, "Add a boarding date and time.");
      ok = false;
    } else if (instant.getTime() < Date.now() - 60 * 1000) {
      setError(els.boardError, "That boarding time has already passed in Atlanta. Choose a later time.");
      ok = false;
    } else {
      setError(els.boardError, "");
    }

    return ok ? { gate: gate, boarding: instant } : null;
  }

  els.gate.addEventListener("input", function () {
    syncChip();
    hideScopeMessage();
    setError(els.gateError, "");
  });
  els.date.addEventListener("input", function () {
    setError(els.boardError, "");
    paintReadout();
  });
  els.time.addEventListener("input", function () {
    setError(els.boardError, "");
    paintReadout();
  });
  function onHorizonInput() {
    state.horizonBucket = +els.horizon.value || 0;
    paintForecastLabel();
    els.horizon.setAttribute(
      "aria-valuetext",
      els.forecastFor.textContent
    );
    paintHeatmap();
    if (state.inspectedZoneId) paintAreaInfo(state.inspectedZoneId, { quiet: true });
  }
  els.horizon.addEventListener("input", onHorizonInput);
  els.horizon.addEventListener("change", onHorizonInput);
  els.editBtn.addEventListener("click", function () {
    setView("input");
    resetZoom();
    els.gate.focus();
  });
  els.mapReset.addEventListener("click", resetZoom);
  els.form.addEventListener("submit", function (event) {
    event.preventDefault();
    var parsed = validate();
    if (!parsed) {
      els.formStatus.textContent = "Check the gate and boarding time.";
      return;
    }
    runSearch(parsed.gate, parsed.boarding);
  });

  initBoardingFields();
  setView("input");
  paintClock();
  paintReadout();
  paintSource();
  paintSpots();
  syncHorizonControl();
  if (MOCK) els.mockBanner.hidden = false;

  loadConcourseB().then(function (ok) {
    if (ok) {
      renderBMap();
      els.formStatus.textContent = "Concourse B map ready. Enter a gate for quiet spots.";
    } else {
      els.mapCaption.hidden = false;
      els.mapCaption.textContent = "The Concourse B map could not be loaded.";
    }
  });

  setInterval(function () {
    paintClock();
    paintReadout();
    paintCountdowns();
  }, 15000);
})();
