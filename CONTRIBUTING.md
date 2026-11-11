# Contributing

Thanks for improving Project Research Loop Assistant.

## Development setup

1. Copy `.env.example` to `.env` and fill in a local MySQL connection and an OpenAI-compatible LLM endpoint.
2. Backend: `cd services/api && uv sync --extra dev && uv run alembic upgrade head`
3. API: `uv run python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8002`
4. Worker: `uv run python -m app.workers.worker_service --queue default --poll-interval 2`
5. Frontend: `npm --prefix apps/web install && npm --prefix apps/web run dev -- --hostname 127.0.0.1 --port 3000`

## Checks before a pull request

```powershell
cd services/api
uv run --extra dev python -m pytest tests -q

cd ../../apps/web
npm test
npx tsc --noEmit
npm run build
```

- Keep changes focused and add a regression test for behavior changes.
- Do not commit `.env`, API keys, database passwords, cloned repositories under `workspace/projects/`, or logs under `.tmp/`.
- Do not use the LLM to bypass deterministic evidence checks; model output remains advisory.
- For user-visible behavior, include a short before/after description and any known limitations.
