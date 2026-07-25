# Frontend (React + TypeScript + Vite)

The React client for the Portfolio Decision Tool. The FastAPI backend is a
separate deployable — this talks to it over HTTP only.

```bash
npm install
npm run dev        # http://localhost:5173, proxies /api to localhost:8000
npm run build      # -> dist/
npm run typecheck
```

Run the API alongside it: `task dev` from the repo root.

## Deploying to Vercel

Vercel hosts this frontend well; it is **not** a good host for the Python API
(serverless execution limits, no persistent disk for the parquet price cache or
SQLite). The intended split is **frontend on Vercel, API on AWS App Runner**.

1. Import the repo in Vercel and set the root directory to `frontend/`
2. Vercel auto-detects Vite (`vercel.json` pins it anyway)
3. Set `VITE_API_BASE` to your deployed API origin, e.g.
   `https://xxxx.us-west-1.awsapprunner.com`
4. On the API, allow that Vercel origin in the CORS config

Without `VITE_API_BASE` the client calls same-origin `/api`, which is what the
dev proxy and the single-container Docker build both provide.
