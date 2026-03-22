#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────
# scripts/test_task.sh
# Simulates a Slack message via the /process-message endpoint.
# Requires: curl  (jq is optional but recommended for pretty output)
#
# Usage:
#   chmod +x scripts/test_task.sh
#   ./scripts/test_task.sh
# ─────────────────────────────────────────────────────────────────
set -e

API="http://localhost:8000"
PRETTY="cat"
command -v jq &>/dev/null && PRETTY="jq ."

echo ""
echo "═══════════════════════════════════════════════════════"
echo "  AI Workflow Coordinator — Shell Test"
echo "═══════════════════════════════════════════════════════"
echo ""

# ── Health check ──────────────────────────────────────────────
echo "🔍 Health check..."
curl -sf "${API}/" | ${PRETTY}
echo ""

# ── Test 1: High priority task with assignee + deadline ───────
echo "📨 Test 1 — High priority task:"
curl -sf -X POST "${API}/process-message" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Hey Sarah, please finish the Q3 financial report by this Friday. High priority!",
    "source": "test"
  }' | ${PRETTY}
echo ""

# ── Test 2: Critical task ─────────────────────────────────────
echo "📨 Test 2 — Critical production issue:"
curl -sf -X POST "${API}/process-message" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "URGENT: production API is down, Marcus please fix immediately!",
    "source": "test"
  }' | ${PRETTY}
echo ""

# ── Test 3: Low priority, no assignee ────────────────────────
echo "📨 Test 3 — Low priority, no assignee:"
curl -sf -X POST "${API}/process-message" \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Someone should update the README documentation whenever they get a chance.",
    "source": "test"
  }' | ${PRETTY}
echo ""

# ── List all tasks ────────────────────────────────────────────
echo "📋 All tasks in database:"
curl -sf "${API}/tasks" | ${PRETTY}
echo ""

echo "═══════════════════════════════════════════════════════"
echo "  ✅ Done! Dashboard: http://localhost:3000"
echo "     API docs:  http://localhost:8000/docs"
echo "═══════════════════════════════════════════════════════"
echo ""
