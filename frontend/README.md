# ACEDEN AI OS: web interface (Step F1)

React 18 with `react-scripts`, no other runtime dependencies. Design tokens come from the AI Workflow Coordinator.

## Run
```
cd frontend
npm install
npm start            # http://localhost:3000, proxies API calls to http://localhost:8000
npm test             # unit tests for session storage and error text
npm run build        # production build (CI=true makes lint warnings fatal, as on Vercel)
```

## F1 contents
Register, sign in with an optional **remember me for 30 days**, sign out (ends the session on every device), change password, recent account activity. The other sidebar items are placeholders for F2 to F5.

## F2 contents
- A workspace picker in the sidebar (the choice is remembered in `localStorage`; it is only an id), and a "create your first workspace" screen for new accounts.
- **Connections:** list the workspace's systems with a status (Working, Test failed, Not tested, Revoked), a **Test** button, **Replace secret** and **Revoke**, and a "Connect a system" form for Slack, HubSpot, Asana, Gmail, Google Calendar, Aceden and an AI model.
- Buttons follow the user's permissions: a member with read-only access sees the list but no Connect, Replace or Revoke controls. The server enforces the same rules.
- The form only sends secrets in the `secret` field, never in `config`. The address must be https, and the suggested addresses are editable defaults.
- "Allow the AI to make changes" is off by default and maps to `allow_write`.

## F3 contents
**Goals & plans** page: type a goal, the AI proposes a plan (nothing runs yet), you review the steps (agent, instruction, dependencies) and choose **Approve and run** or **Discard**. A running plan shows step progress and refreshes every 3 seconds until it finishes; plans can be cancelled. Steps that need a human approval show as "Waiting for approval" (the approval inbox arrives in F4).
- If the AI needs more information, or finds nothing to do, the page says so and no plan is created.
- A goal is sent with an idempotency key, so a double click does not create two plans. Editing the goal creates a new key.
- The API deliberately returns no goal or instruction text for stored plans, so the recent-plans list shows time, step count and status only. The goal and steps you just reviewed are held in the page only until you run or discard them.
- Planning needs an **AI model** connection (Connections page); without one the page shows the API error and points there.

## Sessions
- Without "remember me" the token is kept in `sessionStorage` and disappears when the tab closes.
- With it, the token is kept in `localStorage` for the lifetime the API issued (`REMEMBER_ME_TTL_DAYS`, default 30, set on the server). The page removes an expired entry and never sends it.
- Signing out or changing the password invalidates every token on the server.
- Trade-off: any script running on the page can read `localStorage`. The app has no third-party scripts and renders all API text as plain text, but keep it that way.

## Deploy (Vercel)
- Set `REACT_APP_API_URL` to the API origin, **and** add the frontend origin to the API's `ALLOWED_ORIGINS` (production refuses `*`). Alternatively leave `REACT_APP_API_URL` empty and add rewrites for `/auth/*` and the other API prefixes to the API host in `vercel.json`.
- The API must run on a container host, not on Vercel functions (see docs/LAUNCH.md).
- Billing, trials and subscription gates from the Coordinator are not part of the AI OS yet.

## F4 contents
Approvals page (sidebar): an inbox of requests that wait for a person, with risk level, who asked, expiry, and a "Review details" view of exactly what the AI wants to do. Approvers can Approve (asks to confirm) or Reject with an optional note. Anyone else sees only their own requests, without details. Auditors also get an Activity tab (the workspace audit trail in plain words). Approving does not run anything: go back to Goals & plans (or the run) to continue it.
Also fixed: the UI now understands wildcard permissions (`connection:*`, `*`), which is how admins and owners are stored.

## F5 contents
Monitoring page (sidebar, admins and owners): the four headline numbers (completed, pending approval, in progress, failed), firing alerts and a plain-words "needs attention" list, connection health, action statistics with recent failures, and automation health. A time window selector (hour, 24 hours, 7 days) and a 30-second refresh. It reads the existing `GET /monitoring/overview`. The old paste-a-token page at `/dashboard` on the API is unchanged and still works for operators.
