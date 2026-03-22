# AI Workflow Coordinator — v0.2 MVP

A SaaS backend that listens to Slack channels, uses OpenAI to extract tasks, assigns them to people, and tracks them on a Kanban dashboard.

```
Slack message → AI extraction → PostgreSQL → Kanban dashboard + Slack reply
```

## Stack

| Layer     | Technology                        |
|-----------|-----------------------------------|
| Backend   | FastAPI + SQLAlchemy 2.0 + Alembic |
| AI        | OpenAI GPT-4o-mini (JSON mode)    |
| Slack     | Slack Bolt for Python             |
| Database  | PostgreSQL 16                     |
| Frontend  | React 18 (Create React App)       |
| Deploy    | Render (backend) + Vercel (frontend) + Supabase (DB) |

---

## Project Structure

```
ai-workflow-coordinator/
├── .env.example              ← Copy to .env and fill in keys
├── Dockerfile                ← Docker build for backend
├── docker-compose.yml        ← Local: db + backend containers
├── render.yaml               ← One-click Render deployment
├── requirements.txt
├── alembic.ini
├── alembic/
│   ├── env.py                ← Reads DATABASE_URL from .env
│   └── versions/
│       └── 0001_initial_tasks.py   ← Creates tasks table
├── app/
│   ├── main.py               ← FastAPI app entry point
│   ├── config.py             ← Pydantic settings (reads .env)
│   ├── database.py           ← SQLAlchemy engine + session
│   ├── models.py             ← Task ORM model
│   ├── schemas.py            ← Pydantic request/response types
│   ├── crud.py               ← DB operations
│   ├── ai_extractor.py       ← OpenAI task extraction
│   ├── slack_bot.py          ← Bolt app + message handler
│   └── routers/
│       ├── messages.py       ← POST /process-message
│       ├── tasks.py          ← GET/PATCH /tasks
│       └── slack.py          ← POST /slack/events
├── frontend/
│   ├── vercel.json           ← Vercel deployment config
│   ├── .env.example          ← Copy to .env.local for production
│   ├── package.json
│   └── src/
│       ├── api.js            ← Backend API calls
│       ├── App.jsx           ← Main app + Kanban layout
│       ├── hooks/useTasks.js ← Data fetching + optimistic updates
│       └── components/
│           ├── KanbanColumn.jsx
│           ├── TaskCard.jsx
│           └── AddTaskModal.jsx
└── scripts/
    ├── test_task.py          ← Python integration test
    ├── test_task.sh          ← Shell integration test
    └── ngrok_start.sh        ← Start server + ngrok tunnel
```

---

## Quick Start (Local)

### 1. Install dependencies

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env` and fill in your keys:

```env
DATABASE_URL=postgresql://postgres:password@localhost:5432/ai_workflow
OPENAI_API_KEY=sk-...
SLACK_BOT_TOKEN=xoxb-...
SLACK_SIGNING_SECRET=...
```

### 3. Start PostgreSQL

```bash
docker-compose up -d db
```

### 4. Run database migrations

```bash
alembic upgrade head
```

> ✅ This creates the `tasks` table in PostgreSQL.

### 5. Start the backend

```bash
uvicorn app.main:app --reload
```

- API: http://localhost:8000
- Interactive docs: http://localhost:8000/docs

### 6. Start the frontend (new terminal)

```bash
cd frontend
npm install
npm run dev
```

- Dashboard: http://localhost:3000

### 7. Test it works

```bash
# Python (recommended — shows colored output)
python3 scripts/test_task.py

# Or shell
./scripts/test_task.sh
```

---

## Slack App Setup (one-time)

### Step 1 — Create a Slack App

1. Go to https://api.slack.com/apps → **Create New App** → From scratch
2. Name: `AI Workflow Coordinator`, pick your workspace

### Step 2 — Add Bot Token Scopes

**OAuth & Permissions** → **Bot Token Scopes**, add:

| Scope              | Purpose                       |
|--------------------|-------------------------------|
| `channels:history` | Read public channel messages  |
| `groups:history`   | Read private channel messages |
| `chat:write`       | Post replies in threads       |
| `app_mentions:read`| Respond to @mentions          |

### Step 3 — Install to Workspace

**OAuth & Permissions** → **Install to Workspace** → Authorize

Copy the **Bot User OAuth Token** (`xoxb-...`) → paste into `.env` as `SLACK_BOT_TOKEN`

### Step 4 — Copy Signing Secret

**Basic Information** → **App Credentials** → **Signing Secret**

Paste into `.env` as `SLACK_SIGNING_SECRET`

### Step 5 — Expose local server with ngrok

```bash
# Option A: automated (starts server + tunnel)
./scripts/ngrok_start.sh

# Option B: manual
ngrok http 8000
```

### Step 6 — Set the Request URL

**Event Subscriptions** → Enable Events → **Request URL**:

```
https://your-ngrok-id.ngrok.io/slack/events
```

Slack sends a one-time challenge — the handler responds automatically. ✅

### Step 7 — Subscribe to Events

**Event Subscriptions** → **Subscribe to bot events**:
- `message.channels`
- `message.groups`

Click **Save Changes**.

### Step 8 — Invite the bot to a channel

In Slack: `/invite @AI Workflow Coordinator`

---

## REST API

| Method  | Endpoint                | Description                        |
|---------|-------------------------|------------------------------------|
| `GET`   | `/`                     | Health check                       |
| `POST`  | `/process-message`      | Manual message → AI → DB           |
| `GET`   | `/tasks`                | List tasks (filter + paginate)     |
| `GET`   | `/tasks/{id}`           | Get task by ID                     |
| `PATCH` | `/tasks/{id}/status`    | Update task status                 |
| `POST`  | `/slack/events`         | Slack Events API webhook           |

### Example: Process a message manually

```bash
curl -X POST http://localhost:8000/process-message \
  -H "Content-Type: application/json" \
  -d '{"message": "Sarah, fix the login bug by Monday. Urgent!", "source": "manual"}'
```

Response:

```json
{
  "message": "Task extracted and saved successfully.",
  "extracted": {
    "task": "Fix the login bug",
    "assignee": "Sarah",
    "deadline": "Monday",
    "priority": "high"
  },
  "task": {
    "id": 1,
    "task_description": "Fix the login bug",
    "assignee": "Sarah",
    "deadline": "Monday",
    "priority": "high",
    "status": "pending",
    "created_at": "2025-01-01T12:00:00Z",
    ...
  }
}
```

---

## Deployment

### Database → Supabase

1. Create a project at [supabase.com](https://supabase.com)
2. **Settings → Database → Connection string** → copy the URI
3. Use as `DATABASE_URL` in Render environment variables

### Backend → Render

**Option A: `render.yaml` (recommended)**

1. Push to GitHub
2. Go to [render.com](https://render.com) → **New** → **Blueprint**
3. Connect your repo — Render reads `render.yaml` automatically
4. Set `OPENAI_API_KEY`, `SLACK_BOT_TOKEN`, `SLACK_SIGNING_SECRET` in the dashboard

**Option B: Manual**

1. **New Web Service** → connect GitHub repo
2. **Build command**: `pip install -r requirements.txt`
3. **Start command**: `alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT`
4. Add all environment variables from `.env.example`
5. Copy the deployed URL: `https://your-app.onrender.com`

### Frontend → Vercel

1. Go to [vercel.com](https://vercel.com) → **New Project** → connect repo
2. **Root Directory**: `frontend`
3. Add environment variable:
   ```
   REACT_APP_API_BASE=https://your-app.onrender.com
   ```
4. Deploy

### Update Slack Request URL

After deploying the backend, update your Slack App:

**Event Subscriptions → Request URL**:
```
https://your-app.onrender.com/slack/events
```

---

## How It Works

```
User posts in Slack
       │
       ▼
POST /slack/events
(Bolt verifies X-Slack-Signature)
       │
       ▼
handle_message()  in slack_bot.py
       │
       ├─ Guard: skip bot messages, edits, sub-types
       │
       ├─ Step 1: extract_task_from_message(text)
       │          → OpenAI GPT-4o-mini (JSON mode, temp=0)
       │          → { task, assignee, deadline, priority }
       │
       ├─ Step 2: crud.create_task(db, message, extracted)
       │          → INSERT INTO tasks ...
       │
       └─ Step 3: say(reply, thread_ts=...)
                  → ✅ Task #7 created and assigned to *Sarah*
                     › finish the landing page redesign
                     › Deadline: Thursday  |  Priority: 🟠 high
```

---

## Priority Levels

| Value      | Emoji | Assigned when                                     |
|------------|-------|---------------------------------------------------|
| `critical` | 🔴    | Production down, security breach, data loss, ASAP |
| `high`     | 🟠    | Urgent, blocking a team, due today/tomorrow       |
| `medium`   | 🟡    | Normal request, this-week deadline (default)      |
| `low`      | 🟢    | "Nice to have", no rush, far-future deadline      |

---

## Task Status Flow

```
pending  →  in_progress  →  completed
   ↑              ↓
   └──────────────┘  (can move back)
   
pending / in_progress → cancelled
cancelled → pending (restore)
```

---

## DB Migrations

```bash
# Create a new migration after changing models.py
alembic revision --autogenerate -m "describe your change"

# Apply migrations
alembic upgrade head

# Roll back one step
alembic downgrade -1
```

---

## Environment Variables Reference

| Variable             | Required | Description                              |
|----------------------|----------|------------------------------------------|
| `DATABASE_URL`       | ✅       | PostgreSQL connection string             |
| `OPENAI_API_KEY`     | ✅       | OpenAI API key                           |
| `SLACK_BOT_TOKEN`    | ✅       | Slack Bot User OAuth Token (`xoxb-...`)  |
| `SLACK_SIGNING_SECRET` | ✅    | Slack app signing secret                 |
| `SLACK_CHANNEL_ID`   | ⬜       | Restrict bot to one channel (optional)   |
| `APP_ENV`            | ⬜       | `development` or `production`            |
| `APP_SECRET_KEY`     | ⬜       | App secret (auto-generated on Render)    |


A SaaS backend that listens to Slack channels, uses AI to extract tasks,
assigns them, and tracks them in PostgreSQL. Replies directly in Slack threads.

## Stack
- **FastAPI** — async Python web framework
- **Slack Bolt** — official Slack bot SDK (Events API + signature verification)
- **PostgreSQL** — task storage
- **OpenAI GPT-4o-mini** — task + priority extraction
- **SQLAlchemy 2.0** — ORM
- **Alembic** — DB migrations

---

## Project Structure
```
ai-workflow-coordinator/
├── .env.example
├── .gitignore
├── README.md
├── alembic.ini
├── docker-compose.yml
├── requirements.txt
├── scripts/
│   └── ngrok_start.sh        ← Start dev server + tunnel in one command
├── alembic/
│   └── env.py
└── app/
    ├── main.py               ← FastAPI app + router registration
    ├── config.py             ← Settings (reads .env)
    ├── database.py           ← SQLAlchemy engine + get_db()
    ├── models.py             ← Task ORM model
    ├── schemas.py            ← Pydantic types
    ├── crud.py               ← DB operations
    ├── ai_extractor.py       ← OpenAI structured extraction
    └── routers/
        ├── messages.py       ← POST /process-message
        ├── tasks.py          ← GET/PATCH /tasks
        └── slack.py          ← POST /slack/events  ← NEW
    slack_bot.py              ← Bolt app + message handler ← NEW
```

---

## Quick Start

### 1. Install dependencies
```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure environment
```bash
cp .env.example .env
# Fill in OPENAI_API_KEY, SLACK_BOT_TOKEN, SLACK_SIGNING_SECRET
```

### 3. Start PostgreSQL
```bash
docker-compose up -d
```

### 4. Run the server
```bash
uvicorn app.main:app --reload
```

---

## Slack App Setup (one-time)

### Step 1 — Create a Slack App
1. Go to https://api.slack.com/apps → **Create New App** → From scratch
2. Name it "AI Workflow Coordinator", pick your workspace

### Step 2 — Add Bot Token Scopes
Navigate to **OAuth & Permissions** → **Bot Token Scopes**, add:

| Scope              | Purpose                        |
|--------------------|--------------------------------|
| `channels:history` | Read public channel messages   |
| `groups:history`   | Read private channel messages  |
| `chat:write`       | Post replies in threads        |
| `app_mentions:read`| Respond to @mentions           |

### Step 3 — Install App to Workspace
**OAuth & Permissions** → **Install to Workspace** → Authorize

Copy the **Bot User OAuth Token** (`xoxb-...`) → paste into `.env` as `SLACK_BOT_TOKEN`

### Step 4 — Copy Signing Secret
**Basic Information** → **App Credentials** → **Signing Secret**
Paste into `.env` as `SLACK_SIGNING_SECRET`

### Step 5 — Expose your local server with ngrok
```bash
# Option A: one command (starts both server + tunnel)
./scripts/ngrok_start.sh

# Option B: manually
ngrok http 8000
```

### Step 6 — Set the Request URL
In your Slack App: **Event Subscriptions** → Enable Events → **Request URL**:
```
https://your-ngrok-subdomain.ngrok.io/slack/events
```
Slack sends a challenge POST — the handler responds automatically. ✅

### Step 7 — Subscribe to Events
**Event Subscriptions** → **Subscribe to bot events**:
- `message.channels`
- `message.groups` (if using private channels)

Click **Save Changes**.

### Step 8 — Invite the bot to a channel
In Slack: `/invite @AI Workflow Coordinator`

---

## How It Works

```
User posts a message in Slack
        │
        ▼
POST /slack/events  (Bolt verifies X-Slack-Signature)
        │
        ▼
handle_message()  in slack_bot.py
        │
        ├─ Guard: skip bot messages, edits, sub-types
        │
        ├─ Step 1: extract_task_from_message(text)
        │          → OpenAI GPT-4o-mini (JSON mode)
        │          → returns task / assignee / deadline / priority
        │
        ├─ Step 2: crud.create_task(db, message, extracted)
        │          → INSERT INTO tasks ...
        │
        └─ Step 3: say(reply, thread_ts=...)
                   → ✅ Task #7 created and assigned to *Sarah*
                      › finish the landing page redesign
                      › Deadline: Thursday  |  Priority: 🟠 high
```

---

## Example Slack Interaction

**User** (in #dev channel):
> Hey Sarah, the login page is broken in production — please hotfix ASAP, it's critical!

**Bot** (replies in thread):
> ✅ Task #12 created and assigned to **Sarah**
> › Fix the broken login page in production
> › Deadline: ASAP  |  Priority: 🔴 critical

---

## REST API

| Method | Endpoint                 | Description                        |
|--------|--------------------------|------------------------------------|
| POST   | `/process-message`       | Manual message → AI → DB           |
| GET    | `/tasks`                 | List tasks (filter + paginate)     |
| GET    | `/tasks/{id}`            | Get task by ID                     |
| PATCH  | `/tasks/{id}/status`     | Update task status                 |
| POST   | `/slack/events`          | Slack Events API webhook           |

Interactive docs: `http://localhost:8000/docs`

---

## DB Migrations (Alembic)
```bash
alembic revision --autogenerate -m "describe change"
alembic upgrade head
```

## Priority levels
| Value      | Emoji | When assigned                                     |
|------------|-------|---------------------------------------------------|
| `critical` | 🔴    | Production down, security breach, "ASAP"          |
| `high`     | 🟠    | Urgent, blocking another team, due today/tomorrow |
| `medium`   | 🟡    | Normal request, this-week deadline (default)      |
| `low`      | 🟢    | "Nice to have", no rush, far-future deadline      |
