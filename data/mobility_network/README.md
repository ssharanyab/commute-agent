# Bengaluru static mobility seeds (Phase 5B)

Normalized / provenance-bearing artifacts consumed by Phase 5A sync adapters.

| Path | Dataset | Authority |
| --- | --- | --- |
| `bmtc/` | BMTC community GTFS (fetch separately) | COMMUNITY_UNOFFICIAL |
| `bmrcl/seed/` | BMRCL network topology seed | OFFICIAL (normalized/derived) |
| `bmrcl/enrichment/` | Community GTFS coordinate aliases | COMMUNITY_UNOFFICIAL coords |
| `bmrcl/audit/` | Phase 6C geographic audit artifacts | — |
| `auto_fares/seed/` | Regulated auto fare | GOVERNMENT_REGULATED |
| `shakti/seed/` | Shakti eligibility policy | OFFICIAL_GOVERNMENT |

Runtime planning must use the last **valid published** snapshot under each dataset directory; failed syncs are archived and do not replace `active.json`.
