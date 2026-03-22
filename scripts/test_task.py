#!/usr/bin/env python3
"""
test_task.py
────────────
Simulates Slack messages being processed through the full pipeline:
  message → AI extraction → database → response

Usage:
  python3 scripts/test_task.py

Requirements:
  Backend must be running: uvicorn app.main:app --reload
"""

import json
import sys
import urllib.request
import urllib.error

API = "http://localhost:8000"

TEST_MESSAGES = [
    {
        "message": "Hey Sarah, please finish the Q3 report by Friday. It's high priority!",
        "source": "test",
    },
    {
        "message": "Marcus — deploy the hotfix ASAP, production database is throwing 500 errors. Critical!",
        "source": "test",
    },
    {
        "message": "Can someone review the design mockups whenever you get a chance? No rush at all.",
        "source": "test",
    },
]

COLORS = {
    "green":  "\033[92m",
    "red":    "\033[91m",
    "yellow": "\033[93m",
    "blue":   "\033[94m",
    "bold":   "\033[1m",
    "reset":  "\033[0m",
}

def c(color, text):
    return f"{COLORS.get(color, '')}{text}{COLORS['reset']}"

def _request(method, path, data=None, timeout=30):
    body = json.dumps(data).encode() if data is not None else None
    headers = {"Content-Type": "application/json"} if body else {}
    req = urllib.request.Request(
        f"{API}{path}",
        data=body,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode(errors="replace")
        # Try to extract FastAPI detail field
        try:
            detail = json.loads(body_text).get("detail", body_text)
        except Exception:
            detail = body_text
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Network error: {exc.reason}") from exc

def get(path, timeout=10):
    return _request("GET", path, timeout=timeout)

def post(path, data, timeout=30):
    return _request("POST", path, data=data, timeout=timeout)

def patch(path, data, timeout=10):
    return _request("PATCH", path, data=data, timeout=timeout)

def separator():
    print(c("blue", "─" * 60))

# ── Health check ──────────────────────────────────────────────────
separator()
print(c("bold", "  AI Workflow Coordinator — Integration Test"))
separator()
print()

print("🔍 Health check...")
try:
    health = get("/", timeout=5)
    print(f"   {c('green', '✅')} {health['service']} v{health['version']} — online")
except RuntimeError as e:
    print(f"   {c('red', '❌')} Backend not reachable: {e}")
    print()
    print("   Make sure the backend is running:")
    print(c("yellow", "     uvicorn app.main:app --reload"))
    sys.exit(1)

print()

# ── Process test messages ─────────────────────────────────────────
created_ids = []

for i, payload in enumerate(TEST_MESSAGES, 1):
    msg = payload["message"]
    print(f"📨 Test {i}/{len(TEST_MESSAGES)}")
    print(f"   Message: {c('yellow', msg[:70])}{'...' if len(msg) > 70 else ''}")

    try:
        result = post("/process-message", payload)
        e = result["extracted"]
        t = result["task"]
        created_ids.append(t["id"])

        priority_colors = {"critical": "red", "high": "yellow", "medium": "blue", "low": "green"}
        p_color = priority_colors.get(e["priority"], "reset")

        print(f"   {c('green', '✅')} Task #{t['id']} created")
        print(f"   Task:     {e['task']}")
        print(f"   Assignee: {e['assignee'] or c('yellow', 'Unassigned')}")
        print(f"   Deadline: {e['deadline'] or '—'}")
        print(f"   Priority: {c(p_color, e['priority'].upper())}")
        print(f"   Status:   {t['status']}")

    except RuntimeError as ex:
        print(f"   {c('red', '❌')} {ex}")

    print()

# ── Test status update ────────────────────────────────────────────
if created_ids:
    test_id = created_ids[0]
    print(f"🔄 Testing status update (Task #{test_id}: pending → in_progress)...")
    try:
        updated = patch(f"/tasks/{test_id}/status", {"status": "in_progress"})
        print(f"   {c('green', '✅')} Status updated to: {updated['status']}")
    except RuntimeError as ex:
        print(f"   {c('red', '❌')} Status update failed: {ex}")
    print()

# ── List all tasks ────────────────────────────────────────────────
print("📋 Current tasks in database:")
try:
    tasks_data = get("/tasks")
    total = tasks_data["total"]
    tasks = tasks_data["tasks"]

    status_counts: dict = {}
    for t in tasks:
        status_counts[t["status"]] = status_counts.get(t["status"], 0) + 1

    print(f"   Total: {c('bold', str(total))}")
    for s, count in status_counts.items():
        print(f"   {s}: {count}")

    print()
    print("   Most recent tasks:")
    for t in tasks[:5]:
        desc = t["task_description"][:45]
        assignee = t.get("assignee") or "Unassigned"
        print(f"   #{t['id']:3d}  [{t['status']:11s}]  {desc:<48}  → {assignee}")

except RuntimeError as ex:
    print(f"   {c('red', '❌')} Could not fetch tasks: {ex}")

print()
separator()
print(c("green", "  ✅ Test complete! Open http://localhost:3000 to see the dashboard."))
separator()
print()
