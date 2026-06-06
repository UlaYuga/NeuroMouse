# SpeedMouse

SpeedMouse is a zero-build browser dashboard for EEG spectral analysis exports and optional live spectral WebSocket frames. It translates exported Welch PSD, spectral centroid, sliding spectral geometry, and channel summary arrays into interactive canvas/SVG views.

The dashboard stays browser-native: no Python in the browser, no framework, no CDN, and no required runtime service for static replay.

## Views

- PSD Heatmap: Welch PSD by frequency and channel, plus a selected-channel overlay.
- Centroid Over Time: 32 channel lines with synchronized channel selection.
- Geometry Stack: six sliding spectral metrics for the selected channel.
- Channel Grid: 10-20 layout colored by alpha relative power.
- Live Source: optional `ws://127.0.0.1:8766` spectral frames from the soulsyrup1 backend contract.

Click a channel row, line, or electrode to update every view.

## Controls

- Frequency bands are highlighted on PSD views: delta, theta, alpha, beta, gamma.
- PSD overlay can switch between log and linear scale.
- Channel filters support region and hemisphere scopes.
- Heatmap rows can be sorted by 10-20 order, alpha power, or centroid.
- Centroid and geometry hover crosshairs are synchronized.
- Centroid hover shows top and bottom channel rankings at that timestamp.
- Channel grid marks channels with a clear alpha peak.

## Run Locally

```bash
python3 tools/convert_data.py
python3 -m http.server 8000
```

Open `http://localhost:8000/`.

## Live Mode

Run the spectral backend separately, then use the dashboard's Live Source controls:

```bash
python3 run_raw_and_spectral_backend_v4.py
```

The dashboard expects WebSocket frames on `ws://127.0.0.1:8766` with:

- `type: "spectral_analysis"`
- `channel_names`
- `metrics_by_channel[channel].spectral_centroid_hz`
- `metrics_by_channel[channel].spectral_spread_hz`
- `metrics_by_channel[channel].spectral_entropy_normalized`
- `metrics_by_channel[channel].spectral_flatness`
- `metrics_by_channel[channel].spectral_edge_95_hz`
- `metrics_by_channel[channel].alpha_relative_power`
- optional `frequency_hz` and `psd_by_channel` for live PSD overlay

## Data Conversion

The converter expects two local source archives in the ignored source data folder:

- `eeg_welch_export.zip`
- `spectral_centroid_export.zip`

It writes `data/data.json`, which is committed for static hosting.

## Roadmap

- Phase-space / attractor views once exported arrays are available.

## Attribution

See [ATTRIBUTION.md](./ATTRIBUTION.md).
