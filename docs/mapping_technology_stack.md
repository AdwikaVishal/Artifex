# Mapping Technology Stack

## Evaluation

| Criteria | Mapbox GL JS v3 | Google Maps JS | Leaflet.js + plugins | deck.gl + MapLibre GL |
|----------|-----------------|----------------|----------------------|-----------------------|
| **10k+ point performance** | WebGL — smooth at 100k+ | Canvas overlay needed past 5k | DOM-based — stutters past 1k without canvas plugin | WebGL — smooth at 1M+ points |
| **Choropleth** | Native `fill-color` expressions | Custom `FeatureStyleFunction` paints tiles | `choropleth` plugin or manual GeoJSON | `GeoJsonLayer` with accessor |
| **Real-time** | `source.setData()` — 16 ms round-trip | `data.add` + `setMap` — clunky | `addData` + redraw — fine for <500 features | `setProps({data:})` — efficient diffing |
| **SaaS licensing cost (10 seats)** | £0 (free tier) → ~£800/mo at 50k MAU | ~$700/mo pay-as-you-go (28k map loads/mo) | £0 (BSD-2) | £0 (MIT + BSD-3) |
| **Offline / low-bandwidth** | Requires self-hosted raster tile fallback | Prohibited by ToS (no tile caching) | Works with self-hosted PMTiles via `pmtiles` plugin | Same as MapLibre — self-hosted PMTiles |
| **Bundle size** | ~300 kB gzip | ~130 kB gzip + dynamic loading | ~40 kB gzip + plugins | ~150 kB gzip |

---

## Recommendation

### Primary: deck.gl + MapLibre GL (self-hosted PMTiles)

**Why deck.gl wins across all axes for this use case:**

1. **WebGL rendering** — 10k hexbins and 10k+ event points are rendered on the GPU. Leaflet would drop to 15 fps at that count; Google Maps needs a custom canvas overlay that duplicates state. deck.gl handles 1M points without breaking stride.

2. **Choropleth is a first-class citizen** — `GeoJsonLayer` with `getFillColor` accessor — no paint expression DSLs, just a JavaScript function that receives the feature and returns an RGBA array. This aligns with our existing Recharts/chart pattern of "data → accessor → render".

3. **Zero per-MAU licensing** — Self-hosted MapLibre GL (BSD-3) replaces Mapbox GL JS (proprietary, paid past 50k MAU). Our tile pipeline already writes PMTiles — MapLibre natively reads them via `pmtiles://` protocol.

4. **Offline mode** — A PMTiles archive + `maplibregl` + deck.gl can be bundled into a PWA or Electron shell. Rural caseworkers sync the tile pack before leaving the office.

5. **Real-time** — deck.gl layers accept new data arrays on every render cycle. A WebSocket handler pushes updated hexbin GeoJSON; deck.gl diffs the buffer and only re-uploads changed vertices to the GPU.

### Fallback: Leaflet.js + Leaflet.glify

If the team has no WebGL support (old browser in a county courthouse), Leaflet with the `leaflet-glify` plugin (canvas/WebGL hybrid) renders choropleths via an off-screen canvas. Slower but universal. No additional licensing.

---

## Choropleth Code Pattern — Foster Home Density

```typescript
import { Map as MapLibreMap } from 'maplibre-gl'
import { GeoJsonLayer, MapView } from 'deck.gl'
import { MAPBOX_TOKEN } from '@/config'

interface HexbinFeature {
  type: 'Feature'
  properties: {
    hex_id: string
    homes_per_sqmi: number
    capacity_util_pct: number
    total_homes: number
    total_capacity: number
    filled_capacity: number
  }
  geometry: {
    type: 'Polygon'
    coordinates: number[][][]
  }
}

// ── Colour scale ──────────────────────────────────────────────────────────
function densityColor(utilPct: number, homesPerSqmi: number): [number, number, number, number] {
  if (homesPerSqmi < 0.5) return [200, 200, 210, 120] // grey — no data

  // Utilisation: 0% → teal, 50% → amber, >85% → red + hatch
  if (utilPct > 85) return [220, 50, 50, 200]         // critical
  if (utilPct > 60) return [245, 180, 40, 200]         // amber
  if (utilPct > 30) return [60, 190, 180, 200]          // teal
  return [40, 160, 120, 200]                             // dark teal — underutilised
}

function hatchOverlay(utilPct: number): boolean {
  return utilPct > 85
}

// ── Layer ─────────────────────────────────────────────────────────────────
const fosterDensityLayer = new GeoJsonLayer<HexbinFeature>({
  id: 'foster-density-hex',
  data: '/api/geo/layer/foster-density',           // GeoJSON FeatureCollection
  pickable: true,
  stroked: true,
  filled: true,
  extruded: false,
  lineWidthMinPixels: 0.5,
  lineWidthMaxPixels: 1,
  getLineColor: [100, 100, 110, 160],
  getFillColor: (f) => densityColor(
    f.properties.capacity_util_pct,
    f.properties.homes_per_sqmi,
  ),
  // Cross-hatch pattern for critical utilisation
  getLineDashArray: (f) => hatchOverlay(f.properties.capacity_util_pct)
    ? [4, 4] as [number, number]
    : [0, 0] as [number, number],
  lineDashJustified: true,
  // Click-to-inspect tooltip
  onHover: ({ object, x, y }) => {
    if (!object) return tooltip.setVisible(false)
    const p = object.properties
    tooltip.show(
      `${p.total_homes} homes · ${p.filled_capacity}/${p.total_capacity} filled · ${p.homes_per_sqmi} /mi²`,
      { x, y },
    )
  },
  updateTriggers: {
    getFillColor: [fosterDensityData],
    getLineDashArray: [fosterDensityData],
  },
  transitions: {
    getFillColor: { duration: 500 },
  },
})

// ── Composable deck.gl instance ──────────────────────────────────────────
const mapLayers = [fosterDensityLayer, demandLayer, gapLayer, travelLayer, outcomeLayer]

<DeckGL
  initialViewState={{
    longitude: -89.5,
    latitude: 40.0,
    zoom: 7,
    minZoom: 5,
    maxZoom: 14,
  }}
  controller
  layers={mapLayers}
>
  <MapView id="basemap">
    <MapLibreMap
      mapStyle="/tiles/style.json"     // self-hosted PMTiles style
      transformRequest={(url) => url.startsWith('pmtiles://')
        ? { url: url.replace('pmtiles://', '/tiles/') }
        : { url }
      }
    />
  </MapView>
</DeckGL>
```

### Key design decisions in the pattern:

1. **`getFillColor` as a function** — reads `capacity_util_pct` directly from the GeoJSON property. No Mapbox expression strings to debug; standard TypeScript.

2. **Cross-hatch dashes** — `getLineDashArray` conditionally applies a dash pattern when utilisation >85 %. The `lineDashJustified` flag ensures the dashes span the entire polygon edge.

3. **`updateTriggers`** — When `fosterDensityData` reference changes (e.g., after a WebSocket push), deck.gl invalidates only the colour and dash GPU buffers — not the vertex positions. Minimal re-upload.

4. **Tooltip via `onHover`** — Same pattern as every other component in Artifex (`onHover` → `tooltip.show`). No vendor-specific popup API.

5. **PMTiles URL rewriting** — The `transformRequest` function rewrites `pmtiles://` protocol URLs to serve from `/tiles/` on the same origin, avoiding CORS issues in production.

### Fallback Leaflet implementation:

```typescript
import L from 'leaflet'
import 'leaflet-glify'   // canvas/WebGL hybrid

const map = L.map('map').setView([40, -89.5], 7)
L.tileLayer('/tiles/{z}/{x}/{y}.pbf').addTo(map)

const hexLayer = L.glify.geoJson({
  data: geoJsonData,
  style: (f) => ({
    fillColor: densityColor(f.properties.capacity_util_pct, f.properties.homes_per_sqmi),
    fillOpacity: 0.7,
    weight: 0.5,
  }),
  onEachFeature: (f, layer) => {
    layer.bindTooltip(`${f.properties.total_homes} homes`)
  },
}).addTo(map)
```

Leaflet.glify renders GeoJSON on an off-screen canvas, keeping the DOM light. It lacks transitions and line dash patterns — acceptable in the fallback path.

---

## Real-Time Update Path

```
NATS subject "geo.layer.foster-density"
    │
    ▼
asyncpg LISTEN geo_layer_update
    │  (Postgres NOTIFY on families INSERT/UPDATE/DELETE)
    ▼
Python service (scripts/build_geo_layers.py)
    │  recomputes affected hexes
    ▼
WebSocket broadcast to dashboard clients
    │  {"layer": "foster-density", "action": "patch", "features": [...]}
    ▼
Client: setState(...) → deck.gl updateTriggers fires
```

The service patches only changed hexes instead of rebuilding the full GeoJSON. This keeps the update under 200 ms for any single family change.
