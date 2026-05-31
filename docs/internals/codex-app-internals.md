# Codex desktop app internals & API reverse-engineering notes

> Purpose: document the methodology used to locate the private endpoints
> `codex-accounts` relies on (`/wham/usage`, `/codex/responses`) so that
> when a future Codex release moves or renames them, anyone with a
> macOS environment can re-discover the new paths.
>
> **Disclaimer:** None of the endpoints described here are part of any
> public OpenAI API. They are internal to the Codex desktop client and
> may change or disappear without notice.

---

## Background

The Codex macOS client is an Electron application; it does not ship
public API documentation. The progress bars Codex shows in the top-right
corner ("5h" and "weekly") are driven by a single backend call. The
goal of this note is to locate that call.

---

## Step 1 — Locate the asar bundle

Electron applications package their JavaScript sources into an
`app.asar` archive (a flat, read-only tar-like format):

```text
/Applications/Codex.app/Contents/Resources/app.asar
```

## Step 2 — Extract the asar contents

```bash
mkdir -p /tmp/codex-asar-inspect
npx asar extract \
  /Applications/Codex.app/Contents/Resources/app.asar \
  /tmp/codex-asar-inspect
```

The `npx` invocation fetches `@electron/asar` on demand; you need
Node.js installed.

## Step 3 — Survey the layout

```text
/tmp/codex-asar-inspect/
├── .vite/
│   └── build/
│       └── main-<hash>.js              # Electron main process
└── webview/
    ├── index.html
    └── assets/
        ├── codex-api-<hash>.js         # API call layer
        ├── request-<hash>.js           # HTTP wrapper
        ├── vscode-api-<hash>.js        # VSCode IPC bridge
        ├── rate-limit-rows-<hash>.js   # React component for the quota UI
        └── …other React chunks
```

The `-<hash>` suffixes change with every Codex release — re-grep for
them after each upgrade.

## Step 4 — Find the quota call

```bash
grep -r "rate-limit" /tmp/codex-asar-inspect/webview/assets/ -l
# → rate-limit-rows-<hash>.js
```

Inside that file, formatted for readability:

```js
import { l as o, n as s } from "./codex-api-<hash>.js";

const QUERY_KEY = ['rate-limit-status'];

async function fetchRateLimit() {
  try {
    return await s();   // delegates to codex-api's exported `n`
  } catch (e) { … }
}
```

`s` is re-exported from `codex-api-<hash>.js`. Open that file and
search for the function it points at:

```js
import { t as y } from "./request-<hash>.js";

async function getUsage() {
  return y.safeGet('/wham/usage');
}
export { getUsage as n };
```

`safeGet` is a wrapper around `makeRequest('get', path, options)` and
the base URL is set by the main process:

```js
// main-<hash>.js
const PROD_BASE = 'https://chatgpt.com/backend-api';
const DEV_BASE  = 'http://localhost:8000/api';
```

## Result — quota endpoint

```text
GET https://chatgpt.com/backend-api/wham/usage
Authorization: Bearer <access_token>
```

The access token is the value at `tokens.access_token` in
`~/.codex/auth.json`. It is a standard JWT with the OpenAI custom
claims described below; expiry is roughly 10 days.

## Response shape

```json
{
  "user_id": "user-…",
  "account_id": "user-…",
  "email": "user@example.com",
  "plan_type": "plus",
  "rate_limit": {
    "allowed": true,
    "limit_reached": false,
    "primary_window": {
      "used_percent": 55,
      "limit_window_seconds": 18000,
      "reset_after_seconds": 2547,
      "reset_at": 1778670307
    },
    "secondary_window": {
      "used_percent": 51,
      "limit_window_seconds": 604800,
      "reset_after_seconds": 489405,
      "reset_at": 1779157165
    }
  },
  "credits": {
    "has_credits": false,
    "unlimited": false,
    "balance": "0"
  },
  "spend_control": {
    "reached": false,
    "individual_limit": null
  }
}
```

| Field | Meaning |
|---|---|
| `rate_limit.primary_window` | 5-hour sliding window (`limit_window_seconds = 18000`) |
| `rate_limit.secondary_window` | 7-day sliding window (`limit_window_seconds = 604800`) |
| `used_percent` | Percentage of the window already consumed (0–100) |
| `reset_after_seconds` | Seconds until the window resets |
| `reset_at` | Unix timestamp at which the window resets |
| `rate_limit.allowed` | `false` means the current request is throttled |
| `rate_limit.limit_reached` | `true` means quota is exhausted |
| `credits.has_credits` | Whether the account has paid credits available |

## JWT-only fields (offline decode)

The `access_token` is a standard three-part JWT. The middle segment,
once base64url-decoded, contains:

```json
{
  "https://api.openai.com/profile": {
    "email": "user@example.com",
    "email_verified": true
  },
  "https://api.openai.com/auth": {
    "chatgpt_plan_type": "plus",
    "chatgpt_account_id": "user-…",
    "chatgpt_user_id": "user-…"
  },
  "exp": 1715760000,
  "iat": 1714896000
}
```

This is why `codex-accounts list` and `info` can show email, plan, and
token expiry **without** making any network call.

## Other endpoints observed in the bundle

| Endpoint | Apparent purpose |
|---|---|
| `GET /wham/usage` | Live quota lookup (used by codex-accounts) |
| `GET /wham/accounts/check` | Account validity check |
| `GET /accounts/check/v4-2023-04-27` | Detailed account info |
| `GET /wham/tasks/{task_id}` | Single task status |
| `POST /codex/responses` | Inference request (used by `refresh`) |

Base URL: `https://chatgpt.com/backend-api`.

## Re-discovering the endpoints after a Codex upgrade

1. Re-extract the asar:

   ```bash
   npx asar extract /Applications/Codex.app/Contents/Resources/app.asar \
     /tmp/codex-asar-inspect
   ```

2. Re-locate the relevant files (hashes change every release):

   ```bash
   grep -rl "rate-limit-status" /tmp/codex-asar-inspect/webview/assets/
   grep -rl "wham"              /tmp/codex-asar-inspect/webview/assets/
   ```

3. Dump every `safeGet` / `safePost` invocation:

   ```bash
   grep -oE "safe(Get|Post)\('[^']+'\)" \
     /tmp/codex-asar-inspect/webview/assets/codex-api-*.js
   ```

4. Verify against a live token:

   ```bash
   TOKEN=$(python3 -c "import json; \
     print(json.load(open('$HOME/.codex/auth.json'))['tokens']['access_token'])")
   curl -s -H "Authorization: Bearer $TOKEN" \
     https://chatgpt.com/backend-api/wham/usage | python3 -m json.tool
   ```

5. If the response schema changed, update `Window.from_json` and
   `fetch_quota` in `src/codex_switch/api.py` accordingly.

## Notes

- The `/wham/usage` endpoint is a read-only lookup; calling it does
  not consume any rate-limit budget.
- The Vite-style content-hashed filenames change on every build, but
  the internal function names and routing strings have been stable
  across multiple Codex releases.
- Tokens are short-lived (~10 days); a 401 from `/wham/usage` is the
  signal to re-login in Codex and re-snapshot via
  `codex-accounts save <name>`.
