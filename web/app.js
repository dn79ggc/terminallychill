(function () {
  "use strict";

  var TZ = "America/New_York";
  var CONCOURSES = "TABCDEF";
  var GATE = /^[TABCDEF]\d{1,2}$/;

  var nowEl = document.getElementById("atl-now");
  var dayEl = document.getElementById("atl-day");
  var form = document.getElementById("trip");
  var gateEl = document.getElementById("gate");
  var chip = document.getElementById("concourse-chip");
  var letterEl = document.getElementById("concourse-letter");
  var gateError = document.getElementById("gate-error");
  var dateEl = document.getElementById("board-date");
  var timeEl = document.getElementById("board-time");
  var boardWhen = document.getElementById("board-when");
  var boardUntil = document.getElementById("board-until");
  var boardError = document.getElementById("board-error");
  var formStatus = document.getElementById("form-status");
  var mapTitle = document.getElementById("map-title");
  var mapKicker = document.getElementById("map-kicker");
  var mapCaption = document.getElementById("map-caption");
  var stage = document.getElementById("stage");
  var spotsKicker = document.getElementById("spots-kicker");
  var spotsStatus = document.getElementById("spots-status");
  var spots = document.querySelector(".spots");

  var dateFmt = new Intl.DateTimeFormat("en-US", {
    timeZone: TZ,
    weekday: "long",
    month: "short",
    day: "numeric"
  });
  var timeFmt = new Intl.DateTimeFormat("en-US", {
    timeZone: TZ,
    hour: "numeric",
    minute: "2-digit"
  });
  var clockFmt = new Intl.DateTimeFormat("en-US", {
    timeZone: TZ,
    hour: "numeric",
    minute: "2-digit"
  });
  var dayFmt = new Intl.DateTimeFormat("en-US", {
    timeZone: TZ,
    weekday: "short",
    month: "short",
    day: "numeric",
    timeZoneName: "short"
  });

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

  // Treat the picker’s numbers as an Atlanta wall-clock time, not the phone’s zone.
  function atlantaToUtc(year, month, day, hour, minute) {
    var guess = Date.UTC(year, month - 1, day, hour, minute, 0);
    var utc = guess - zoneOffsetMs(new Date(guess));
    return new Date(guess - zoneOffsetMs(new Date(utc)));
  }

  function readBoarding() {
    if (!dateEl.value || !timeEl.value) return null;
    var d = dateEl.value.split("-");
    var t = timeEl.value.split(":");
    if (d.length < 3 || t.length < 2) return null;
    return atlantaToUtc(+d[0], +d[1], +d[2], +t[0], +t[1]);
  }

  function relativePhrase(instant) {
    var minutes = Math.round((instant.getTime() - Date.now()) / 60000);
    if (minutes < -1) return "already passed";
    if (minutes <= 1) return "about now";
    if (minutes < 60) return "in " + minutes + " min";
    var hours = Math.floor(minutes / 60);
    var rest = minutes % 60;
    if (!rest) return "in " + hours + (hours === 1 ? " hr" : " hrs");
    return "in " + hours + (hours === 1 ? " hr " : " hrs ") + rest + " min";
  }

  function paintClock() {
    var now = new Date();
    nowEl.dateTime = now.toISOString();
    nowEl.textContent = clockFmt.format(now);
    var parts = dayFmt.formatToParts(now);
    var zone = "";
    var day = [];
    parts.forEach(function (part) {
      if (part.type === "timeZoneName") zone = part.value;
      else if (part.type !== "literal") day.push(part.value);
    });
    dayEl.textContent = day.join(" ") + (zone ? " · " + zone : "");
  }

  function paintReadout() {
    var instant = readBoarding();
    if (!instant) {
      boardWhen.textContent = "Choose a boarding date and time in Atlanta.";
      boardUntil.textContent = "";
      return;
    }
    var phrase = relativePhrase(instant);
    boardWhen.textContent = dateFmt.format(instant) + " · " + timeFmt.format(instant) + " Atlanta";
    boardUntil.textContent = phrase.charAt(0).toUpperCase() + phrase.slice(1);
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

  function syncChip() {
    var value = gateEl.value.toUpperCase().replace(/[^A-Z0-9]/g, "").slice(0, 4);
    if (value !== gateEl.value) gateEl.value = value;
    var letter = value.charAt(0);
    if (letter && CONCOURSES.indexOf(letter) !== -1) {
      letterEl.textContent = letter;
      chip.hidden = false;
    } else {
      chip.hidden = true;
      letterEl.textContent = "";
    }
  }

  function defaultBoarding() {
    var plus = new Date(Date.now() + 90 * 60 * 1000);
    var p = zoneParts(plus);
    var minute = +p.minute;
    var extra = (5 - (minute % 5)) % 5;
    var base = atlantaToUtc(+p.year, +p.month, +p.day, +p.hour, minute);
    var rounded = zoneParts(new Date(base.getTime() + extra * 60 * 1000));
    var today = zoneParts(new Date());
    dateEl.min = today.year + "-" + today.month + "-" + today.day;
    dateEl.value = rounded.year + "-" + rounded.month + "-" + rounded.day;
    timeEl.value = rounded.hour + ":" + rounded.minute;
  }

  function applyTrip(gate, instant) {
    var concourse = gate.charAt(0);
    form.dataset.gate = gate;
    form.dataset.boarding = instant.toISOString();
    form.dataset.concourse = concourse;
    mapTitle.textContent = "Concourse " + concourse;
    mapKicker.textContent = "Gate " + gate;
    mapCaption.textContent = "The Concourse " + concourse + " schematic will appear here, colored by the crowd forecast for gate " + gate + ".";
    stage.dataset.concourse = concourse;
    spotsKicker.textContent = "Gate " + gate + " · " + timeFmt.format(instant);
    spotsStatus.textContent = "Ranked places for gate " + gate + " will fill this list, with walk time and a leave-by countdown. Rankings are not loaded in this layout yet.";
    spots.classList.add("is-armed");
    spots.querySelectorAll(".spot-meta").forEach(function (el) {
      el.textContent = "How quiet · walk to " + gate;
    });
    formStatus.textContent = "Layout ready for gate " + gate + ", boarding " + timeFmt.format(instant) + " Atlanta time.";
  }

  gateEl.addEventListener("input", function () {
    syncChip();
    setError(gateError, "");
  });

  dateEl.addEventListener("input", function () {
    setError(boardError, "");
    paintReadout();
  });
  timeEl.addEventListener("input", function () {
    setError(boardError, "");
    paintReadout();
  });

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    var gate = gateEl.value.trim().toUpperCase();
    var instant = readBoarding();
    var ok = true;

    if (!GATE.test(gate)) {
      setError(gateError, "Enter an ATL gate such as B22. Concourses are T, A, B, C, D, E, and F.");
      ok = false;
    } else {
      setError(gateError, "");
    }

    if (!instant) {
      setError(boardError, "Add a boarding date and time.");
      ok = false;
    } else if (instant.getTime() < Date.now() - 60 * 1000) {
      setError(boardError, "That boarding time has already passed in Atlanta. Choose a later time.");
      ok = false;
    } else {
      setError(boardError, "");
    }

    if (!ok) {
      formStatus.textContent = "Check the gate and boarding time.";
      return;
    }

    applyTrip(gate, instant);
    var reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    stage.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" });
  });

  defaultBoarding();
  paintClock();
  paintReadout();
  setInterval(function () {
    paintClock();
    paintReadout();
  }, 15000);
})();
