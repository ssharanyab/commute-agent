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

## Fares (Phase 7K-6)

| Field | Value |
| --- | --- |
| Authority | **OFFICIAL** (BMRCL Revised Fare Chart 14.02.2025) |
| Artifact | `fares/bmrcl_token_fare_slabs_v20250214.json` |
| Source | https://english.bmrc.co.in:8282/English/uploads/news/english/fileuploads/Revised_Fare_Chart_for_webiste.pdf |
| Metric | Stations travelled excluding originating station (token face fare) |

Smart-card discounts are documented on the chart but not applied. FFC km-distance zones use the same rupee amounts but are not used here (no authoritative OD distances in the topology snapshot).

