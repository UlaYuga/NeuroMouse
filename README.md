# SpeedMouse

SpeedMouse is a zero-build browser dashboard for static EEG spectral analysis exports. It translates exported Welch PSD, spectral centroid, sliding spectral geometry, and channel summary arrays into interactive canvas/SVG views.

The v1 dashboard is intentionally static: no Python in the browser, no framework, no CDN, and no live runtime dependency.

## Views

- PSD Heatmap: Welch PSD by frequency and channel, plus a selected-channel overlay.
- Centroid Over Time: 32 channel lines with synchronized channel selection.
- Geometry Stack: six sliding spectral metrics for the selected channel.
- Channel Grid: 10-20 layout colored by alpha relative power.

Click a channel row, line, or electrode to update every view.

## Run Locally

```bash
python3 tools/convert_data.py
python3 -m http.server 8000
```

Open `http://localhost:8000/`.

## Data Conversion

The converter expects two local source archives in the ignored source data folder:

- `eeg_welch_export.zip`
- `spectral_centroid_export.zip`

It writes `data/data.json`, which is committed for static hosting.

## Roadmap

- v2: live WebSocket source (port 8766) using the same viewer-side data contract.

## Attribution

See [ATTRIBUTION.md](./ATTRIBUTION.md).
