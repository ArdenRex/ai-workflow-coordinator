# Step 5: Core AI Intelligence (closed)

Goal: turn the infrastructure into something that can understand a request and safely work out the right
capability, without giving intelligence any authority.

## What exists

| Substep | Capability | Where |
|---|---|---|
| 5.1 | Provider-neutral LLM service: limits, bounded retries, timeouts, content-free audit, fake provider | `app/llm/{service,types,errors,fake,registry}.py` |
| 5.2 | OpenAI-compatible provider; platform key or per-workspace encrypted key; SSRF/size/redirect hardening | `app/llm/{openai_compatible,credentials}.py` |
| 5.3 | Structured outputs: strict schema validation, bounded content-free repair, untrusted-text fencing | `app/llm/structured.py` |
| 5.4 | Request understanding: caller-scoped capability catalog, deterministic intent resolution | `app/intelligence/{catalog,understanding}.py` |
| 5.5 | Safe tool planning: strict argument validation, proposals only, single kernel bridge | `app/intelligence/planning.py` |
| 5.6 | End-to-end safety suite across the whole chain | `tests/test_step5_e2e.py` |

HTTP: `POST /workspaces/{id}/ai/understand` and `/ai/plan` (permission `ai:use`: member, admin, owner).
Neither executes anything.

## The chain

    user text
      -> LLMService (size limits, timeout, retries, content-free audit)
      -> generate_structured (strict JSON, extra fields forbidden, bounded repair)
      -> RequestUnderstandingService (caller-scoped catalog; deterministic resolve())
      -> ToolCallPlanner (candidate tools only; strict arguments; registry/policy facts)
      -> ToolCallProposal                      <- data, not authority
      -> submit_proposal -> ToolExecutionService.submit   <- the only bridge; kernel decides

## Guarantees (each backed by tests)

1. **No execution from the AI packages.** `app/llm` and `app/intelligence` never call a handler, create an
   execution row or approve anything. The only `.submit(` is in `planning.submit_proposal`, and a source-scan
   test fails if another appears. Only `openai_compatible.py` may import a network library.
2. **The model sees only what the caller can use.** Catalog and prompts are filtered by the kernel's own
   permission/policy evaluation; names outside it are treated as unknown, and are re-checked at plan time.
3. **Model output is data.** Strict schemas with `extra="forbid"`, no coercion, size/depth caps; smuggled
   fields (role, skip_approval, execute_now, ...) are rejected; unusable output degrades to a clarifying
   question, never a guess.
4. **Facts come from code.** Risk level, approval requirement and policy decision are attached from the
   registry/policy; a forged "no approval needed" is ignored by the kernel.
5. **Proposals are bound** to the user and workspace they were made for, and the kernel re-validates input and
   re-checks permission, policy and approval at submit time.
6. **Workspace isolation:** each workspace uses only its own model key; audit events stay in their own trail;
   outsiders get the same 404 as for a nonexistent workspace.
7. **No secrets or content in logs/audit/errors:** prompts, completions, arguments, request text and keys never
   appear in logs, audit payloads or client errors; provider failures map to generic 422/429/502/503.

## Carried forward (not done in Step 5, by design)

- Per-workspace token/rate/spend limits and policies: Steps 12 and 14.
- Multi-step plans, delegation, aggregation: Step 7. Agents with scoped principals: Step 6.
- HTTP endpoint that submits a proposal: arrives with agents/orchestration (they will call `submit_proposal`).
- Connection-availability awareness in the catalog (does the workspace have a working connector?): Step 10.
- Conversation history and memory in understanding: Step 8.
- DNS-rebinding window (connectors and LLM provider), HTTP client pooling, Postgres-specific testing,
  login/register rate limiting: Step 14.
- Argument values are not checked for grounding in the user's words; risky tools rely on approval.
