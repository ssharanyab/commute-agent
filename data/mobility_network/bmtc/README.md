# BMTC community GTFS (Phase 5B / 6A)

## Provenance

| Field | Value |
| --- | --- |
| Authority | **COMMUNITY / UNOFFICIAL** — not BMTC official GTFS |
| MobilityDatabase | https://mobilitydatabase.org/feeds/gtfs/mdb-2595 |
| Producer | https://github.com/Vonter/bmtc-gtfs |
| Notes | Producer describes the feed as unofficial; source is the Namma BMTC app; timetable accuracy can be imperfect |

Do **not** label this feed as “BMTC official GTFS” in UI or metadata.

## Local layout

```
data/mobility_network/bmtc/
  README.md          # this file
  audit/             # Phase 6A connectivity / data-quality reports (committed)
  snapshots/         # normalized publish output (gitignored — regenerate locally)
  failed/            # rejected sync candidates (gitignored)
  # place extracted GTFS here (not committed by default):
  # gtfs/  or  bmtc-gtfs.zip
```

Tiny fixture used by tests (not the full feed):

`tests/fixtures/bmtc_gtfs_sample/`

## How to fetch the full community feed

Do **not** commit the full GTFS archive into git (≈40MB+ zip; multi-GB if fully expanded into JSON with shapes/stop_times).

```bash
# Clone / download from the producer, then point the sync pipeline at the zip:
git clone --depth 1 https://github.com/Vonter/bmtc-gtfs /tmp/bmtc-gtfs

# Phase 6A: compact publish + connectivity audit
PYTHONPATH=. .venv/bin/python scripts/phase6a_bmtc_audit.py \
  --gtfs /tmp/bmtc-gtfs/gtfs/bmtc.zip

# Or sync only (compact = topology + stats; omits bulk shapes/stop_times/trips):
PYTHONPATH=. .venv/bin/python -c "
from src.network.file_repository import FileStaticMobilityRepository
from src.network.ingest.bmtc_gtfs import build_bmtc_sync_pipeline

repo = FileStaticMobilityRepository('data/mobility_network')
pipeline = build_bmtc_sync_pipeline(
    '/tmp/bmtc-gtfs/gtfs/bmtc.zip', repo, compact=True
)
print(pipeline.run(version='community-gtfs').to_dict())
"
```

### Compact normalization (documented)

For the full community archive, `compact=True`:

* validates stop/route/trip/stop_time references while building route sequences
* publishes stops + routes (with `stop_ids`) + calendars + `dataset_meta.statistics`
* omits bulk `stop_times`, `shapes`, `trips`, and raw GTFS fare tables from the snapshot

This is a repository size policy, not data fabrication. Authority remains `COMMUNITY_UNOFFICIAL`.

Normalized snapshots land under `data/mobility_network/bmtc/snapshots/` (gitignored).
Audit reports land under `data/mobility_network/bmtc/audit/`.
