# Document Q&A — Frontend

Minimal React + TypeScript (Vite) client for the FastAPI RAG backend in
`../backend`.

## What it does

- **Auth** — `POST /auth/register` + `POST /auth/login`; the JWT is held in
  React state (memory only), so a page refresh signs you out.
- **Documents** — `POST /documents` (PDF upload) and `GET /documents`
  (list with ingestion status).
- **Ask** — `POST /ask` with a source-count selector; renders the answer plus
  the cited chunks and their cosine similarity scores.

A `401` from any request clears the session and returns to the login screen.

## Running it

The backend must be running on `http://127.0.0.1:8000` (see `../README.md`).

```bash
npm install
npm run dev          # http://localhost:5173
```

Point the proxy somewhere else with `VITE_BACKEND_URL`:

```bash
VITE_BACKEND_URL=http://127.0.0.1:9000 npm run dev
```

## How requests reach the backend

The backend configures no CORS middleware, so instead of calling it
cross-origin the Vite dev server proxies `/api/*` and strips the prefix
([vite.config.ts](vite.config.ts)). The browser only ever talks to the Vite
origin; the API client in [src/api.ts](src/api.ts) prefixes every path with
`/api`.

This proxy is a dev-server feature only. A production build is static files and
would need either the API served from the same origin (reverse proxy) or CORS
enabled on the backend.

## Scripts

| Command | Purpose |
| --- | --- |
| `npm run dev` | Dev server with HMR + API proxy |
| `npm run build` | Type-check (`tsc -b`) and build to `dist/` |
| `npm run preview` | Serve the production build locally (no proxy) |
| `npm run lint` | Run oxlint |

## Layout

```
src/
  api.ts                       # typed fetch client + URL types (the API contract)
  App.tsx                      # session gate: AuthForm <-> dashboard
  components/
    AuthForm.tsx               # login / register tabs
    DocumentsPanel.tsx         # upload + document list
    AskPanel.tsx               # question input, answer and sources
  index.css                    # design tokens and all component styles
```
