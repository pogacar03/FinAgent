# Frontend engineer report

## Delivery

Implemented the Chinese React/Vite/TypeScript research terminal in `frontend/`. It submits and reloads run history, polls run and backtest jobs with abort cleanup, persists the selected run, and displays frozen Top 10 picks, research details, persona assumptions and risks, safe source links, PIT status, valuation breakdowns, benchmark availability, audit events, and actual nested backtest results. The comparison keeps portfolio returns as percentages and backend excess fields as percentage points. DEMO screens and details carry a visible `DEMO / SYNTHETIC` label; REAL mode displays provider and PIT requirements.

The frontend uses Vite's `/api` development proxy and a Node build plus Nginx production image that proxies `/api` to the Compose `api` service. No component framework or chart dependency was added.

## Files

- `frontend/src/App.tsx`, `frontend/src/api.ts`, `frontend/src/main.tsx`, `frontend/src/styles.css`, `frontend/src/vite-env.d.ts`
- `frontend/index.html`, `frontend/package.json`, `frontend/package-lock.json`, `frontend/tsconfig.json`, `frontend/tsconfig.node.json`, `frontend/vite.config.ts`, `frontend/.gitignore`
- `frontend/Dockerfile`, `frontend/nginx.conf`

## Verification

- `npm ci --no-audit --no-fund` — completed successfully (67 packages installed).
- `npm run build` — passed initially with Vite 5.4.11, then was re-run after the security update below.
- An earlier build attempt before installing dependencies stopped at `tsc: command not found`; the clean install and final build passed afterward.
- Browser E2E and Docker image build were not run by this frontend subtask; root is handling browser verification.

## Backtest provenance review follow-up

The comparison panel now reads the SA benchmark source only from the selected backtest job's saved `payload.benchmark`. A pinned source shows its URI, period, publication time, verification note, and hash. An explicit `null` says that no SA list was bound when the backtest was submitted. An older payload without the field says the source cannot be confirmed. The separate current registry display is labeled as a reference for later backtests and is never presented as the source for the loaded result.

- Added `npm run check:provenance`, a focused dependency-free check for pinned, explicit-null, absent-field, and absent-payload backtest cases — passed.
- `npm run build` — passed with Vite 8.3.4 after the provenance changes; TypeScript check passed, 17 modules transformed, JS 178.21 kB (56.99 kB gzip), CSS 29.52 kB (7.23 kB gzip).
- `npm audit --json` — passed with 0 vulnerabilities (0 low, 0 moderate, 0 high, 0 critical).

## Dependency security follow-up

Updated the exact Vite pin from 5.4.11 to 8.3.4 and `@vitejs/plugin-react` from 4.3.4 to 6.1.2 after checking current npm registry metadata. Both current package manifests require Node `^20.19.0 || >=22.12.0`; the React plugin peer range is Vite `^8.0.0`. The Docker build stage now uses Node 22.

- `npm ci --no-audit --no-fund` — passed after the lockfile update (27 packages installed).
- `npm audit --json` — passed with 0 vulnerabilities (0 low, 0 moderate, 0 high, 0 critical).
- `npm run build` — passed with Vite 8.3.4; TypeScript check passed, 16 modules transformed, JS 176.19 kB (56.45 kB gzip), CSS 28.26 kB (7.02 kB gzip).
- Docker was unavailable in the environment (`docker: command not found`), so the updated image stage could not be built here.

## Runtime/model note

Assigned model mapping: `gpt-6-luna` with `max` reasoning effort. No hidden Fast flag was used.
