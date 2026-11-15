"use strict";
// Read-only operations dashboard. Every server value is written with textContent (no HTML parsing of server values); the token lives in a variable only.
(function () {
  var $ = function (id) { return document.getElementById(id); };
  var UUID = /^[A-Za-z0-9_-]{1,64}$/;
  var MESSAGES = { 401: "The token was not accepted.", 403: "You need the admin or owner role to see this.", 404: "Workspace not found.",
                   422: "Invalid window.", 429: "Too many requests. Try again shortly." };

  function clear(el) { while (el.firstChild) el.removeChild(el.firstChild); }
  function text(tag, value, cls) { var e = document.createElement(tag); e.textContent = String(value); if (cls) e.className = cls; return e; }
  function rows(dl, pairs) { clear(dl); pairs.forEach(function (p) { dl.appendChild(text("dt", p[0])); dl.appendChild(text("dd", p[1] === null || p[1] === undefined ? "-" : p[1])); }); }
  function list(ul, items, empty) { clear(ul); if (!items.length) { ul.appendChild(text("li", empty, "muted")); return; } items.forEach(function (i) { ul.appendChild(i); }); }
  function counts(o) { var k = Object.keys(o || {}).sort(); return k.length ? k.map(function (x) { return x + " " + o[x]; }).join(", ") : "none"; }
  function names(a) { return a && a.length ? a.map(function (x) { return x.name + " " + x.count; }).join(", ") : "none"; }
  function pct(r) { return r === null || r === undefined ? "-" : (r * 100).toFixed(1) + "%"; }
  function ms(v) { return v === null || v === undefined ? "-" : v + " ms"; }
  function secs(v) { return v === null || v === undefined ? "-" : v + " s"; }

  function render(d) {
    var s = d.summary, h = d.health, a = d.alerts;
    var badge = $("alerts-badge");
    badge.textContent = a.firing_count ? a.firing_count + " firing" : "all clear";
    badge.className = "badge " + (a.highest_severity || "ok");
    list($("alerts"), a.alerts.map(function (x) {
      var li = document.createElement("li");
      li.appendChild(text("span", x.severity.toUpperCase() + " ", x.severity));
      li.appendChild(text("span", x.message + " (" + x.rule + ": " + x.value + ", threshold " + x.threshold + ")"));
      return li;
    }), "Nothing is firing.");
    var e = s.executions;
    rows($("executions"), [["Total", e.total], ["By status", counts(e.by_status)], ["Failure rate", pct(e.failure_rate)],
      ["Average / p50 / p95 / max", [e.avg_duration_ms, e.p50_duration_ms, e.p95_duration_ms, e.max_duration_ms].map(ms).join(" / ")],
      ["Denials", s.denials_in_window + " (" + names(s.denial_reasons) + ")"], ["Top failing tools", names(s.top_failing_tools)]]);
    var p = s.approvals;
    rows($("approvals"), [["Pending", p.pending], ["Oldest pending", secs(p.oldest_pending_age_seconds)], ["Rejected / expired", p.rejected_in_window + " / " + p.expired_in_window],
      ["Decided", p.decided_in_window], ["Decision time avg / p95", secs(p.avg_decision_seconds) + " / " + secs(p.p95_decision_seconds)]]);
    list($("connections"), h.connections.connections.map(function (c) {
      var li = document.createElement("li");
      li.appendChild(text("span", c.state + " ", c.state === "failing" ? "critical" : c.state === "ok" ? "ok" : "warning"));
      li.appendChild(text("span", c.provider + " / " + c.name + (c.last_test_message ? " (" + c.last_test_message + ")" : "")));
      return li;
    }), "No active connections.");
    var ar = h.agent_runs, wr = h.workflow_runs;
    rows($("runs"), [["Agent runs", counts(ar.by_status)], ["Agent runs overdue", ar.overdue_active], ["Agent failure codes", names(ar.failure_codes)],
      ["Workflow runs", counts(wr.by_status)], ["Workflow steps overdue", wr.overdue_steps], ["Steps waiting to retry", wr.steps_waiting_retry],
      ["Workflow failure codes", names(wr.failure_codes)]]);
    var sc = h.schedules, ev = h.events;
    rows($("sched"), [["Schedules", sc.enabled + " enabled, " + sc.disabled + " disabled"], ["Overdue / auto-disabled", sc.overdue + " / " + sc.auto_disabled],
      ["Skipped slots", sc.skipped_slots_total], ["Events in window", ev.received_in_window + " received, " + ev.dispatched_in_window + " dispatched"],
      ["Truncated / stuck", ev.truncated_in_window + " / " + ev.stuck_undispatched]]);
    list($("failures"), s.recent_failures.map(function (f) { return text("li", (f.finished_at || "-") + "  " + f.tool_id + "  " + (f.error || "")); }), "No failures in the window.");
    $("generated").textContent = "Generated " + d.generated_at;
    $("out").hidden = false;
  }

  $("connect").addEventListener("submit", function (ev) {
    ev.preventDefault();
    var ws = $("ws").value.trim(), token = $("token").value, w = $("window").value, st = $("status");
    if (!UUID.test(ws)) { st.textContent = "Enter a valid workspace id."; return; }
    st.textContent = "Loading...";
    fetch("/workspaces/" + encodeURIComponent(ws) + "/monitoring/overview?window_seconds=" + encodeURIComponent(w),
          { headers: { "Authorization": "Bearer " + token }, cache: "no-store", credentials: "omit" })
      .then(function (r) { if (!r.ok) { throw new Error(MESSAGES[r.status] || "Could not load (" + r.status + ")."); } return r.json(); })
      .then(function (d) { render(d); st.textContent = ""; })
      .catch(function (err) { $("out").hidden = true; st.textContent = err && err.message ? err.message : "Could not load."; });
  });
})();
