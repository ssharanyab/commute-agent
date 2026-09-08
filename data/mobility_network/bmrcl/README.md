# BMRCL metro network (Phase 5B topology + Phase 6C coordinates)

## Topology (official-derived)

| Field | Value |
| --- | --- |
| Authority | **OFFICIAL** (normalized/derived from BMRCL website materials) |
| Seed | `seed/bmrcl_network_seed.json` |
| Source | https://english.bmrc.co.in/schematic-route-map/ |

Station **topology** provenance remains `OFFICIAL_OPEN_DATA`. Coordinates are **not** claimed as official.

## Coordinates (community enrichment — Phase 6C)

| Field | Value |
| --- | --- |
| Authority | **COMMUNITY / UNOFFICIAL** |
| Producer | https://github.com/Vonter/bmrcl-gtfs |
| Spatial source | OpenStreetMap-derived (per producer) |
| Timetables | Approximations — **not** used by this project |

Do **not** label enriched coordinates as official BMRCL / government data.

### Fetch + publish

```bash
# Download community GTFS (do not commit the zip)
mkdir -p .tmp_bmrcl_gtfs && curl -fsSL -o .tmp_bmrcl_gtfs/bmrcl.zip \
  https://raw.githubusercontent.com/Vonter/bmrcl-gtfs/main/gtfs/bmrcl.zip

PYTHONPATH=. .venv/bin/python scripts/phase6c_bmrcl_audit.py \
  --gtfs .tmp_bmrcl_gtfs/bmrcl.zip
```

Normalized snapshots: `snapshots/` (gitignored).  
Audit reports: `audit/` (committed).

Matching: exact seed-id aliases (`enrichment/station_id_aliases.json`) then exact normalized name. No blind fuzzy matching. Unmatched stations keep `latitude`/`longitude` = null.
