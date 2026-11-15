# Authentication (Step 4.2)

- `POST /auth/register` -> creates a user (no workspace yet; workspaces arrive in 4.3). 409 on duplicate email (case-insensitive).
- `POST /auth/login` -> `{access_token, token_type: bearer, expires_in}`. One identical 401 for unknown email, wrong password, disabled account; unknown emails still burn a hash verify to equalize timing.
- `GET /auth/me` -> current user. `get_current_user` (app/api/deps.py) is the only way endpoints learn the caller; it re-checks the user exists and is active on every request.
- Passwords: stdlib scrypt, embedded params, auto-rehash on login if params change. Policy: 10-128 chars, not blank.
- Tokens: HS256 JWT, algorithm pinned, requires exp/iat/sub/iss, typ=access. Signing key = HMAC(APP_SECRET_KEY, "aceden-ai-os:jwt") so the root secret is never used directly (4.4 will derive a separate encryption key).
- Config: `ACCESS_TOKEN_TTL_MINUTES` (1-1440, default 60), `REMEMBER_ME_TTL_DAYS` (1-90, default 30; used when login or password change sends `remember_me: true`), `JWT_ISSUER`.

Known gaps, scheduled later: login/register rate limiting (Step 14), refresh tokens / token revocation and password change/reset (not in roadmap yet; decide after 4.6), email verification.
