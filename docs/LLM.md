# LLM layer (Step 5)

Models produce **text only**. They never touch tools, the database or workspaces. Any real action a model
suggests must later go through the execution kernel (Steps 5.4-5.5), so intelligence never gets authority.

## Substep 5.1

    app/llm/
      types.py     Message, LLMRequest (frozen, strict, temperature 0 by default), LLMResponse, Usage
      errors.py    LLMError tree with generic messages; retryable flag per class
      base.py      LLMProvider contract: complete(request, timeout) -> LLMResponse
      fake.py      FAKE / TEST ONLY deterministic provider (scripted replies/errors, echo default)
      registry.py  PROVIDERS map; add a provider = one entry; unknown -> LLMConfigError
      service.py   LLMService: the only way the OS calls a model

**LLMService guarantees**
- Input limits (`LLM_MAX_INPUT_CHARS`, max 50 messages) checked before any provider call.
- Output tokens always capped by `LLM_MAX_OUTPUT_TOKENS`; callers can only ask for less.
- Per-call timeout (`LLM_TIMEOUT_SECONDS`) passed to the provider.
- Retries only for retryable errors (rate limit, timeout, unavailable), at most `LLM_MAX_RETRIES`, with
  exponential backoff. Auth/config/input/bad-response errors are never retried.
- Unexpected provider exceptions are converted to a generic `LLMError` (original is not chained).
- One **content-free** audit event per call in the workspace's trail: `llm.completed` / `llm.failed` with
  purpose label, provider, model, attempts, latency, `usage` {input, output} or error code (the audit redactor hides any key containing "token", so counts are nested under `usage`). Prompts and completions are
  never logged or stored.

**Config:** `LLM_PROVIDER` (default `fake`), `LLM_MODEL`, `LLM_TIMEOUT_SECONDS`, `LLM_MAX_RETRIES`,
`LLM_MAX_INPUT_CHARS`, `LLM_MAX_OUTPUT_TOKENS`. `LLM_PROVIDER=fake` is rejected in production.

**Known gaps (planned):** no real provider yet (5.2); no structured/validated outputs (5.3); no per-workspace
token budgets or rate limits (Step 14 / policies in Step 12); timeout is enforced by the provider, not by a
wall-clock guard in the service.

## Substep 5.2: real provider

    app/llm/openai_compatible.py   OpenAICompatibleProvider (Chat Completions; OpenAI, Groq, Together, vLLM, ...)
    app/llm/credentials.py         workspace "llm" credentials, resolve_provider(), workspace_llm(), connection test

**Provider hardening:** fixed endpoint path; no redirects (key never forwarded); 1 MB response cap; SSRF host
guard (every resolved address must be public); https required in production; generic errors that never include
request/response bodies or the key; key held in a `SecretStr` and only sent in the Authorization header.
Status mapping: 401/403 auth; 429 rate-limited (retryable); timeout, 408/409, 5xx, transport failure
unavailable/timeout (retryable); other 4xx input error; 3xx or unusable body bad-response.

**Platform key:** `LLM_PROVIDER=openai_compatible` + `LLM_BASE_URL` + `LLM_API_KEY` (+ `LLM_MODEL`).
Validated at startup; https required in production.

**Workspace key (bring your own):** create a credential with provider `llm`, config `{base_url, model,
timeout_seconds?}` and the API key as the secret (AES-GCM encrypted, workspace-bound like all credentials).
Resolution: the workspace's single active `llm` credential if present, else the platform provider. Several
active credentials are refused, a revoked one falls back to the platform provider, rotation applies at once.
`POST /workspaces/{id}/credentials/{cid}/test` makes one 1-token call (admin/owner, cooldown-limited) and
records the result. Callers use `workspace_llm(db, settings, workspace_id)` which always closes the HTTP client.

**Known gaps:** a new HTTP client per call (no pooling yet); no streaming; no per-workspace spend limits
(Steps 12/14); DNS-rebinding window as for connectors (Step 14); a workspace can point its key at any public
OpenAI-compatible host, which is intended, but prompts then leave the platform: surface this in the product UI.

## Substep 5.3: structured outputs

    app/llm/structured.py   generate_structured(), parse_model_output(), schema_instructions(), wrap_untrusted()

Model text is **untrusted data** until it validates. `generate_structured(llm, ..., schema, messages)` returns a
typed pydantic object plus attempt count and summed usage, or raises `LLMStructuredOutputError`.

**Accepted output:** exactly one JSON object (optionally in a ```json fence), <= 64,000 chars, nesting <= 20,
no duplicate keys, not truncated (`finish_reason=length` is rejected), and it validates **strictly** (no
"7" -> 7 coercion) against a schema that sets `extra="forbid"`. A schema without `extra="forbid"`, or over
8,000 chars of JSON Schema, is refused before any model call. Extra fields are rejected, so a model cannot
smuggle in a tool name, permission or approval flag.

**Repair:** `LLM_MAX_REPAIRS` (default 1, max 3) extra attempts. The retry message carries only field paths and
validation messages, **never the model's own output**, and replaces (not accumulates) earlier feedback, so
context stays bounded. Provider errors (auth, etc.) are never treated as repairs; transient ones use the
service's own retries.

**Prompt-injection stance:** `wrap_untrusted(text)` fences third-party/user text in `<untrusted_input>` tags
(closing tags inside the text are neutralised) and the schema prompt tells the model it is data. This is a
defence in depth, not a guarantee; the real guarantees are the strict schema here and the kernel's
permission/approval checks later. Validated output is still only a *proposal*.

**Audit:** one `llm.structured_completed` / `llm.structured_failed` event per request in the workspace trail:
purpose, schema name, attempts and rejection categories (`not_json`, `not_object`, `duplicate_key`,
`too_large`, `too_deep`, `truncated`, `schema`). No content.

**Known gaps:** validation is structural, not semantic (a well-formed wrong answer passes; 5.5 adds checks
against the real tool registry); no provider-native JSON-schema mode yet (json_mode hint only); no streaming.

## Substep 5.4: request understanding

    app/intelligence/catalog.py        build_catalog(): tools THIS caller may use (kernel `evaluate`, no DENY)
    app/intelligence/understanding.py  RequestUnderstandingService, ModelIntent, ResolvedIntent, resolve()
    app/api/ai.py                      POST /workspaces/{id}/ai/understand  (permission ai:use)
    app/runtime.py                     the one tool registry the API uses (built-in + connector tools)

**Flow:** user text -> `wrap_untrusted` -> strict structured model call (5.3) -> deterministic `resolve()`
against the caller's catalog -> `ResolvedIntent`. The result is a **proposal with no authority**; nothing here
executes a tool.

**The model only sees what the caller could use.** The catalog is filtered through the kernel's own policy
evaluation (permission, agent scope, disabled tools, workspace policy), so a viewer's prompt never lists
write tools and one role's catalog never reveals another's. A tool the model names that is not in the caller's
catalog is treated as unknown.

**Resolution rules (code, not model):** unknown tool ids dropped (`unknown_tools_dropped`); tools ignored for
smalltalk/out_of_scope/unclear (`tools_ignored_for_kind`); a `tool_request` with no valid tool becomes
`unclear` with a fixed question (`no_matching_capability`); tool/goal intents below `INTENT_MIN_CONFIDENCE`
(default 0.5) require clarification (`low_confidence`); risk level and approval requirement are attached from
the registry/policy, never from the model. If the model's output never validates, the answer degrades to
`unclear` + a generic question (`model_output_invalid`): the system asks rather than guesses.

**Permissions/roles:** new `ai:use` permission for member, admin and owner (viewers cannot spend model calls).
Message length 1-4,000 chars. Provider failures map to generic 422/429/502/503 responses with no details.

**Audit:** `intent.resolved` per request: kind, tool ids, confidence, flags, warnings. Never the user's text or
the model's summary. Plus the usual `llm.*` events (also content-free).

**Known gaps:** the catalog lists registered tools, not whether the workspace has a working connection for them
(5.5/Step 10 can add availability); no conversation history (single message); no per-user/workspace rate limit
or spend budget (Steps 12/14); `summary` is model-written text shown to users and must be output-encoded by
any UI.

## Substep 5.5: safe AI-to-tool planning

    app/intelligence/planning.py   ToolCallPlanner, ModelPlan, ToolCallProposal, PlanResult, submit_proposal()
    app/api/ai.py                  POST /workspaces/{id}/ai/plan   (permission ai:use; proposal only)

**Flow:** `ResolvedIntent` -> model proposes ONE tool + arguments -> deterministic validation ->
`ToolCallProposal`. Only `tool_request` and `question` intents are planned; `goal` returns `no_action`
(`goal_needs_orchestration`) until Step 7, so there is no multi-step autonomy here.

**Guarantees**
- The model may pick only tools that are named by the intent AND still in the caller's live catalog
  (re-evaluated at planning time, so a stale or forged intent cannot widen authority). Anything else is
  `rejected / tool_not_allowed`, with no repair attempt.
- Arguments are validated **strictly** against the tool's own input schema (no coercion, no extra fields), with
  size (8,000 chars) and depth (10) limits. Repair feedback (up to `LLM_MAX_REPAIRS`) carries field paths only,
  never values. Defaults are filled by the tool schema, not the model.
- Risk level, approval requirement and the policy decision come from the registry/policy, never from the model.
- Missing information yields `needs_information` (no arguments are validated or proposed); declining yields
  `no_action`; unusable output yields `rejected / model_output_invalid`.
- The planner never runs a handler. `submit_proposal(service, principal, proposal)` is the only bridge to
  execution: it refuses a proposal made for another user/workspace, then calls the kernel's
  `ToolExecutionService.submit`, which re-validates input, re-checks permission/policy/approval and audits.
  A forged or edited proposal gains nothing: the kernel ignores its claimed risk/approval flags.
- **Audit** (`plan.proposed|needs_information|no_action|rejected`): reason, attempts, tool id, risk, approval
  flag. Never arguments, request text or rationale.

**Known gaps:** there is no HTTP endpoint that submits a proposal yet (agents/orchestration in Steps 6-7 will
drive `submit_proposal`); argument values are not checked for being grounded in the user's words (risky
tools are protected by approval, not by grounding); one tool call per request; availability of the
workspace's connection is not checked at plan time; no rate/spend limits (Steps 12/14).
