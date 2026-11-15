# Credentials (Step 4.4)

**Storage:** `credentials` table, one row per (workspace, provider, name). The secret exists only as AES-256-GCM
ciphertext (`v1.<key_id>.<blob>`); `config` holds non-secret metadata (e.g. base URL) and rejects secret-looking keys.
Key = HMAC-derived from `APP_SECRET_KEY` with purpose "credentials" (separate from the JWT key).
The AAD binds each ciphertext to `workspace_id:credential_id`, so a blob copied to another row/workspace fails to decrypt.

**API** (`/workspaces/{id}/credentials`): create, list, get, `POST /{cid}/rotate`, `DELETE /{cid}` (revoke).
Create/rotate/revoke need `connection:write`; list/get need `connection:read` (admin and owner only). **No endpoint
returns a secret or ciphertext**; `CredentialOut` has no such field and request secrets are `SecretStr`.
Rotation bumps `version` and `rotated_at`; revocation erases the ciphertext, keeps the row and its audit trail,
and the name stays reserved (create a new name instead). Events: `credential.created|rotated|revoked`
(ids/provider/name/version only).

**Server-side use:** `CredentialService.reveal_secret(workspace_id, credential_id)` is the only decrypt path; Step 4.5
connector construction will call it. It is workspace-scoped and raises if revoked or if authentication fails.

**Changing APP_SECRET_KEY:** put the old value in `APP_SECRET_KEY_PREVIOUS` (decrypt-only), deploy, run
`python -m app.reencrypt`, then remove the old value. Without this, stored credentials become unreadable.

**Known gaps:** no envelope/KMS (root secret lives in the environment; a KMS is a Step 14 production-config item);
no per-read audit (4.5 audits connector use); no expiry reminders.
