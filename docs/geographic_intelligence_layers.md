# Geographic Intelligence Map — Data Layers

Each layer is a toggleable overlay on a tiled base map (Mapbox/MapLibre GL).
Every layer answers one operational question for a child welfare director.

---

## 1. Foster Home Density

**Visual:** Hexbin (1 sq mi) — colour from cool grey → teal → amber as homes/mi² increases; cross-hatch pattern applied when capacity utilisation > 85 %.

| Property | Value |
|----------|-------|
| **Data source** | `families` table (geocoded address → lat/lng via census Geocoder or Google Maps Geocoding API). `capacity`, `available_capacity` determine utilisation. Only `active = TRUE` homes shown. |
| **Refresh** | Daily — geocode batch at 02:00 UTC, cache tiles for 24 h. |
| **Director action** | Spot a cold zone (grey hex) where removal rates are high → approve a licensing surge in that district. See an amber cluster at 90 %+ utilisation → open a temporary shelter contract before the next removal spike. |

---

## 2. Child Welfare Demand

**Visual:** Choropleth by ZIP code — saturation scales with children-in-care per 1 000 child population. Outline weight increases for districts above state median removal rate.

| Property | Value |
|----------|-------|
| **Data source** | `children` table filtered `WHERE status IN ('in_care','approved')`, grouped by ZIP (from `children.zip_code` added in migration 0004). Population denominators from ACS 5-year estimates (census API). |
| **Refresh** | Daily (children table is live). Census denominators refreshed annually. |
| **Director action** | A ZIP with 3× the county average removal rate → deploy a prevention team, fund a community-based family support centre, or request a root-cause review from the state. |

---

## 3. Resource Gap Overlay

**Visual:** Computed as *homes/mi²* – *children/mi²* per hex. Positive → blue (surplus), near-zero → grey (balanced), negative → orange→red (deficit). Red zones pulse slowly when the gap exceeds >2 children per home.

| Property | Value |
|----------|-------|
| **Data source** | Layer 1 ÷ Layer 2 — computed server-side from the same cached hex grid. |
| **Refresh** | Daily (derived, so same cadence as layers 1 & 2). |
| **Director action** | A persistent red pocket means children are being placed 20+ miles from their neighbourhood → justify a mobile casework unit or a satellite office in that pocket. A growing surplus (deep blue) where no children are being removed → question whether the recruitment drive overshot actual need and redirect resources. |

---

## 4. Caseworker Travel Burden

**Visual:** Contour isolines (10‑minute drive-time bands) radiating from each caseworker's home office. Fill colour = average round-trip minutes per home visit for that district: green (<30), amber (30–60), red (>60). Dashed lines show county boundaries.

| Property | Value |
|----------|-------|
| **Data source** | `caseworker_assignments` + geocoded family addresses from `families`. Drive times computed via OSRM (self-hosted) or Mapbox Matrix API. District boundaries from county GIS feed. |
| **Refresh** | Weekly — drive-time matrix is expensive to recompute; rerun Saturday 03:00 UTC. |
| **Director action** | A caseworker with 75‑minute average visits → split their district, hire a second caseworker, or authorise a remote/virtual visit policy for low-risk check-ins. A district where every caseworker is in the red zone → relocate a supervisor to that quadrant and adjust mileage reimbursement thresholds. |

---

## 5. Outcome Heatmap

**Visual:** Kernel density estimate of placement disruption events (from `child_life_events` where `event_type = placement_end` with negative outcome). Smooth 2‑mi radius. Colour ramp: green (stable, <5 % disruption) → yellow → red (unstable, >25 % disruption). Opacity blended with population density to avoid false positives in sparsely populated areas.

| Property | Value |
|----------|-------|
| **Data source** | `child_life_events` (placement_end events + disruption flags), `placements` (duration, outcome), `crisis_predictions` (historic disruption probabilities). Location derived from placement family's ZIP at event time. |
| **Refresh** | Weekly — the KDE computation batches over the trailing 12 months of events. |
| **Director action** | A county with 30 % disruption vs. a neighbouring county at 8 % → study what the high‑performing county does differently (different provider network? higher visit frequency? faster kinship placement?) and replicate. A red spot that persists for three consecutive weeks → dispatch a quality assurance team for an on-site review. |

---

## Implementation Notes

- **Tile server:** Self-hosted MapLibre GL with PMTiles — no third-party API keys for production.
- **GeoJSON generation:** A scheduled Python script (`scripts/build_geo_layers.py`) reads from PostgreSQL, computes hexbins/KDE/choropleths, writes PMTiles to `artx/public/tiles/`.
- **Frontend component** (`artx/src/components/GeographicIntelligenceMap.tsx`) — layer toggle panel, legend, click-to-inspect tooltip showing raw counts per hex/ZIP.
- **Auth scope:** `geointel:read` — distinct from `crisis:read` because the map aggregates across all children and families (sensitive).

## Layer Dependency Graph

```
families ───→ 1. Foster Density ──┐
children ───→ 2. Demand       ────┼──→ 3. Gap Overlay
                                    │
caseworker_assignments ─→ 4. Travel ┘
                                    │
child_life_events ─────→ 5. Outcome │
```

Layer 3 is purely a derived arithmetic overlay of layers 1 & 2 and reuses their tile caches.
