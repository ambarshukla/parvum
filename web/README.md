# web/

A read-only wealth dashboard over the Parvum serving API — the fifth layer of
the project, and the only one a non-engineer sees. Vite + React + TypeScript,
charts with Recharts, no application server of its own (it is static files that
talk to the Quarkus API).

## What it shows

One advisory firm (tenant) at a time, switched in the top bar; the sidebar
lists that firm's clients. Per client, five tabs map to the five gold
projections:

- **Overview** — headline wealth, positions, cash, and the FX rate used, plus
  the allocation donut and monthly-income chart.
- **Allocation** — asset-class breakdown (donut + table).
- **Income** — dividends and interest by month.
- **Holdings** — top holdings by owned value.
- **Ownership** — the accounts the client owns and the share held, with shared
  accounts and their co-owners called out (the 60/40 account is the case to
  look at).

The `books_reconcile` flag from the quality layer rides along as a badge on the
client header — the dashboard reports the number _and_ whether it ties out.

## Running it

```
npm install
npm run dev        # http://localhost:5173
```

Dev mode proxies API calls to the Quarkus app on `localhost:8080` (see
`vite.config.ts`), so start that first and load it (`make export-gold`). No
CORS is involved — the browser only ever calls its own origin.

```
npm run build      # tsc --noEmit && vite build → dist/
npm test           # vitest
npm run format:check
```

## Configuration

`VITE_API_BASE` (build-time) points the app at a separately hosted API for a
split deployment; unset, it calls the same origin. Nothing else is configured —
the tenant list is the two firms from D-028.

## Design

Colours come from the project's data-viz palette (a validated, CVD-safe
categorical set); charts carry a legend and direct labels so identity never
rests on colour alone, and the whole UI is theme-aware (light/dark, following
the OS or an explicit toggle).
