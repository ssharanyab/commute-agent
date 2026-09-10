# GoWise — Flutter MVP (Android / iOS)

Minimal UI for `POST /plan` and `POST /replan` against the FastAPI backend.

## Run

```bash
# Terminal 1 — API (0.0.0.0 so Android emulator can reach the host)
cd ../.. && .venv/bin/uvicorn src.api.app:app --host 0.0.0.0 --port 8000

# Terminal 2 — from this directory (src/app)
fvm flutter pub get

# Android emulator
fvm flutter run -d emulator-5554 \
  --dart-define=API_BASE_URL=http://10.0.2.2:8000

# iOS simulator
fvm flutter run -d ios \
  --dart-define=API_BASE_URL=http://127.0.0.1:8000
```

If `--dart-define` is omitted, the UI prefills the Cloud Run demo backend.
Override for local API:

```bash
fvm flutter run --dart-define=API_BASE_URL=http://127.0.0.1:8000
# Android emulator → host:
fvm flutter run --dart-define=API_BASE_URL=http://10.0.2.2:8000
```

## Checks

```bash
fvm flutter analyze
fvm flutter test
```
