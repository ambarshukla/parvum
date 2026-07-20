# internal/

Authenticated internal tools over the Parvum serving API — data operations
and the alts human-in-the-loop (HITL) review queue, neither of which are for
client eyes. A separate app from `web/` (the public client dashboard) because
these need a real access-control boundary the client dashboard was never
designed for; see `docs/DECISIONS.md` D-046.

## What's here

Today: a single shared login (password + signed session cookie, no per-user
accounts — see D-046 for why that's the right amount of auth for one
internal team, not a shortcut). The Ops page and the alts review queue land
on top of this in later slices.

## Running it

```
npm install
npm run dev        # http://localhost:5174 (web/ uses 5173, so both can run at once)
```

Dev mode proxies `/internal/*` calls to the Quarkus app on `localhost:8080`
(see `vite.config.ts`) — same-origin, so no CORS is involved locally even
though the production deployment is cross-origin (a separate Vercel project
calling the same API as `web/`).

```
npm run build      # tsc --noEmit && vite build → dist/
npm test           # vitest
npm run format:check
```

## Configuration

`VITE_API_BASE` (build-time) points the app at the API's production origin
for the split deployment; unset, it calls the same origin (dev only).

## Auth model

One shared credential, not a user table — see D-046 for the full reasoning.
Every request to `/internal/**` carries `credentials: "include"` (the session
cookie) and a custom header (`X-Parvum-Internal`) the server's
`InternalAuthFilter` requires even on the login/logout endpoints, as a cheap
CSRF mitigation (a cross-site form post cannot set a custom header).
