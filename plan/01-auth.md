# Plan 01 — Gmail OAuth setup (one-time, user-facing)

This is the runbook for the one-time Google Cloud setup that produces the
credentials the `/scan-email` skill consumes. It pairs with `auth/oauth-client.json`
(client secret) and `auth/gmail-config.json` (CLI config).

The broader design — what gets built, where, why — lives in
[`02-scan-email.md`](./02-scan-email.md). Read that for context; this file is
just the steps you run once.

---

## 0. Credential hygiene (do this first, before any OAuth flow)

Two things on disk that need attention before anything else:

1. **Rename the OAuth client file.** Google Cloud Console downloads the client
   secret with a long filename that has a Windows `(1)` suffix:
   ```
   auth/client_secret_534755532640-t6gcdlfaj8kq47r0jg2vr154l251qaev.apps.googleusercontent.com (1).json
   ```
   Rename to:
   ```
   auth/oauth-client.json
   ```
   Content unchanged. The CLI reads this stable name.

2. **Add `scopes` and a stable redirect URI to `auth/gmail-config.json`.** The
   file currently lacks both. Final shape:
   ```json
   {
     "client_id": "534755532640-t6gcdlfaj8kq47r0jg2vr154l251qaev.apps.googleusercontent.com",
     "project_id": "job-applications-502912",
     "auth_uri": "https://accounts.google.com/o/oauth2/auth",
     "token_uri": "https://oauth2.googleapis.com/token",
     "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
     "client_secret": "<secret>",
     "redirect_uris": ["http://localhost:3000/oauth2callback"],
     "scopes": ["https://www.googleapis.com/auth/gmail.readonly"]
   }
   ```
   The example file at `auth/gmail-config.example.json` is the source of truth
   for the schema; the real file is gitignored.

3. **Update root `.gitignore`** to keep the credentials and tokens out of git:
   ```gitignore
   # OAuth credentials and tokens (never commit)
   auth/oauth-client.json
   auth/gmail-config.json
   auth/tokens.json
   auth/*.token
   auth/*token*.json
   # Allow the example template to be tracked
   !auth/gmail-config.example.json
   ```
   `git status` should then show no `auth/` files. The example stays tracked
   because it has no real values.

4. **Retire the old setup at `C:\Users\yashd\.gmail-mcp\`** — it carries a
   broader `gmail.modify` scope on a different GCP project (`adept-stage-483720-e1`)
   and we no longer need it. Two steps:
   - Delete the directory and both files inside it.
   - Visit https://myaccount.google.com/permissions and remove the old
     `adept-stage-483720-e1` app's access. One click in the "Third-party apps
     with account access" list.

5. **Sanity check.** `git status` should not show `auth/` after step 3.

---

## 1. Google Cloud project setup

These steps happen in the browser, once.

1. Open Google Cloud Console: https://console.cloud.google.com/
2. Select project `job-applications-502912` (or create it if you've not already
   created one dedicated to this skill — keep job-search tooling on its own
   project, not a personal one).
3. **APIs & Services → Library** → search "Gmail API" → **Enable**.
4. **APIs & Services → OAuth consent screen**:
   - User type: **External** (or Internal if it's a Workspace account).
   - App name: `job-search-email-scanner`.
   - Scopes: **only** `https://www.googleapis.com/auth/gmail.readonly`. Do
     not add any other scope. No `gmail.modify`, no `gmail.send`, no
     `gmail.compose`, no `gmail.settings.basic`. Read-only is the whole point.
   - Test users: add `candidate@example.com` while the app is in
     "Testing" mode (GCP requires this for unverified apps).
5. **APIs & Services → Credentials → Create OAuth client ID**:
   - Application type: **Desktop app** (or **Web application** if you want a
     local HTTP callback — the CLI supports both).
   - Name: `job-search-email-scanner`.
   - Authorised redirect URIs: `http://localhost:3000/oauth2callback`.
   - Download the JSON. Save as `auth/oauth-client.json` (overwriting the
     renamed file from step 0.1, or just confirming the rename was correct).
6. **APIs & Services → Credentials → Create API key** (optional, not used by
   the read-only path; skip unless you later add cloud classification).

---

## 2. Run the consent flow

After the GCP setup, run the CLI's login subcommand to do the OAuth dance and
write the refresh token:

```bash
python -m tools.email_scanner auth-login
```

What happens:
1. The CLI starts a local HTTP server on `http://localhost:3000`.
2. It opens your browser to the Google consent screen.
3. You sign in as `candidate@example.com` and grant the
   `gmail.readonly` scope only. Read the consent screen carefully — if it
   asks for any other scope, deny and re-check step 1.4 above.
4. The CLI captures the authorisation code, exchanges it for tokens, and
   writes `auth/tokens.json` in the same folder as the config.
5. The local server shuts down.

Subsequent runs use the refresh token silently. Access tokens expire after
~1 hour; the CLI refreshes them transparently.

---

## 3. Verify the setup

```bash
python -m tools.email_scanner status
```

Expected output:
- `tokens_file: present` (path is `auth/tokens.json`).
- `token_expiry: <some future timestamp>`.
- `scopes: gmail.readonly` (the CLI checks the token's scope claim).
- `ollama_available: yes` (if you've installed Ollama — see step 4).
- `cloud_classify: disabled` (default; opt-in only).

If `scopes` shows anything other than `gmail.readonly`, **stop and re-run
`auth-login`** after checking the GCP consent screen configuration. Do not
proceed with broader scopes.

---

## 4. Local classification (Ollama)

The classifier runs locally via Ollama so email content never leaves the
laptop. Setup:

1. Download Ollama from https://ollama.com.
2. `ollama pull llama3.2:3b` (~2 GB). Alternative: `ollama pull qwen2.5:7b`
   for slightly better classification at the cost of speed.
3. Verify: `ollama list` should show the pulled model.

If Ollama is not installed when you run `/scan-email`, the CLI exits with a
clear setup message — it will **not** silently fall back to a cloud API.
Cloud classification is opt-in only via the `--cloud-classify` flag.

---

## 5. Revoking access (kill switch)

If your laptop is stolen, or you want to stop using the tool:

1. **Fast path:** run `python -m tools.email_scanner revoke`. This:
   - Calls Google's token revocation endpoint.
   - Deletes `auth/tokens.json`.
   - Prints the URL to also remove the grant manually.
2. **Belt-and-suspenders:** visit
   https://myaccount.google.com/permissions and confirm
   "job-search-email-scanner" is no longer listed. Remove it if it is.
3. **Optional but recommended after a theft:** rotate the OAuth client
   secret at Google Cloud Console → APIs & Services → Credentials →
   your client → **Regenerate Secret**. Old secrets stop working
   immediately. Update `auth/oauth-client.json` with the new value.

The `revoke` subcommand is idempotent — safe to run when no tokens exist
(it just prints "no tokens to revoke").

---

## 6. Rotating the OAuth secret if the repo is ever made public

If you push the repo to a public location, the `auth/oauth-client.json` is
gitignored but still present on disk. Treat it as exposed.

1. Google Cloud Console → APIs & Services → Credentials → click your
   OAuth client → **Regenerate Secret**.
2. Replace the `client_secret` value in `auth/oauth-client.json`.
3. Run `python -m tools.email_scanner auth-login` to re-consent with the
   new secret. The old refresh token is invalidated automatically; the
   new flow issues a new one tied to the new secret.

---

## 7. Disk encryption baseline

The credentials and the email archive contain sensitive content. Recommended
baselines:

- **Windows:** BitLocker on the system drive. Check with
  `manage-bde -status`. Enable via Settings → Privacy & security → Device
  encryption if it's off.
- **macOS:** FileVault on the system drive.
- **Linux:** LUKS on the data partition, or `fscrypt` / `eCryptfs` for
  per-directory encryption.

Disk encryption does not stop a logged-in attacker from reading files,
but it does stop a stolen-laptop or disk-image attacker. Pair with
short screen-lock timeouts.

---

## 8. Cloud-sync exclusion (optional but recommended)

If you sync your `Documents` folder to OneDrive, iCloud, Dropbox, or
similar, exclude the email archive from that sync:

- `documents/applications/**/emails/` — the archived recruiter email
  content. Plaintext, includes PII, attachments.
- `auth/` — the credentials and tokens.

Full-disk encryption plus exclusion from cloud sync is the recommended
posture. The CLI does not enforce this — it relies on you to configure
your sync tool.
