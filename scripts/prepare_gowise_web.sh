#!/usr/bin/env bash
# Build GoWise Flutter web into static/gowise for the Cloud Run image.
# Same-origin API (empty base URL) — UI and /plan share one Cloud Run service.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP="$ROOT/src/app"
OUT="$ROOT/static/gowise"
CLOUD_RUN_URL_DEFAULT="https://commute-agent-242496011822.asia-south1.run.app"

# relative = same-origin when served by FastAPI. Override with absolute URL if needed:
#   API_BASE_URL=https://….run.app ./scripts/prepare_gowise_web.sh
API_BASE_URL="${API_BASE_URL:-relative}"

cd "$APP"
if command -v fvm >/dev/null 2>&1; then
  FLUTTER=(fvm flutter)
else
  FLUTTER=(flutter)
fi

echo "Building GoWise web (API_BASE_URL=$API_BASE_URL)…"
"${FLUTTER[@]}" pub get
"${FLUTTER[@]}" build web --release --dart-define="API_BASE_URL=$API_BASE_URL"

rm -rf "$OUT"
mkdir -p "$(dirname "$OUT")"
cp -R "$APP/build/web" "$OUT"

# Helpful marker for operators
cat > "$OUT/BUILD_INFO.txt" <<EOF
GoWise Flutter web build
API_BASE_URL=$API_BASE_URL
built_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
default_cloud_run=$CLOUD_RUN_URL_DEFAULT
EOF

echo "Wrote $OUT"
du -sh "$OUT"
