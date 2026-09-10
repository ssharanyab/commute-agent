# GoWise on Cloud Run (API + Flutter web)

Serve the Flutter web UI from the **same** FastAPI Cloud Run service.
Browser calls `/plan`, `/places/*`, `/health` on the same origin.

## 1. Build the web UI into `static/gowise`

```bash
# from repo root
chmod +x scripts/prepare_gowise_web.sh
./scripts/prepare_gowise_web.sh
```

Uses `--dart-define=API_BASE_URL=relative` (same-origin). Override if needed:

```bash
API_BASE_URL=https://YOUR-SERVICE-xxxxx.run.app ./scripts/prepare_gowise_web.sh
```

## 2. Deploy to Cloud Run

```bash
# Example — adjust project/region/service name
gcloud run deploy commute-agent \
  --source . \
  --region asia-south1 \
  --allow-unauthenticated \
  --memory 1Gi \
  --min-instances 1
```

Or with Docker:

```bash
./scripts/prepare_gowise_web.sh
docker build -t gowise-api .
# push + gcloud run deploy --image …
```

## 3. Verify

- UI: `https://YOUR-SERVICE.run.app/`
- API: `https://YOUR-SERVICE.run.app/health`
- Places: `https://YOUR-SERVICE.run.app/places/autocomplete?q=Majestic`

If you skipped step 1, `/` shows a small placeholder page; API routes still work.

**Note:** `static/gowise/` build output (~28MB) is gitignored except a placeholder `index.html`. Always run the prepare script before `gcloud run deploy --source` or `docker build` so the image includes the real UI.

## Local check

```bash
./scripts/prepare_gowise_web.sh
.venv/bin/uvicorn src.api.app:app --host 127.0.0.1 --port 8000
# open http://127.0.0.1:8000/
```
