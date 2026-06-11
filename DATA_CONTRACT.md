# NeuroMouse Data Contract

This is the interface between the **Python analysis/backend** (produces data) and the
**browser viewer** (renders it). The viewer owns this contract; a backend that emits
data in these shapes renders without any viewer changes.

There are three entry points:

1. **Canonical dataset** — a `data.json` object, for saved/offline analysis.
2. **Import archives** — ZIP exports the viewer converts into the canonical dataset.
3. **Live WebSocket** — raw signal frames the viewer analyses in-browser.

The viewer is montage-agnostic: **any channel count and any channel names** are
accepted. Channel names are data, not constants. The 10-20 head map is used only when
most channel names match the 10-20 system; otherwise the channel grid falls back to a
generic layout.

---

## 1. Canonical dataset (`data.json`)

This is the authoritative shape. It is what `js/sources/static-source.js → validateData`
enforces and what every import path produces. All per-channel arrays are **channel-major**:
the outer array has one row per channel, in the same order as `meta.channels`.

```jsonc
{
  "meta": {
    "channels": ["Fp1", "Fpz", "..."],   // REQUIRED, non-empty. Order defines channel index.
    "n_channels": 32,                      // optional; if present, MUST equal channels.length
    "segment_duration_sec": 60.0,          // optional
    "sampling_rate_analysis_hz": 256,      // optional
    "welch_window_sec": 4,                 // optional
    "welch_overlap_fraction": 0.5,         // optional
    "sliding_window_sec": 2,               // optional
    "sliding_step_sec": 0.5,               // optional
    "source": "free-text provenance string",
    "analysis_by": "free-text tool/version string"
  },

  "welch_psd": {
    "frequencies": [f0, f1, ...],          // REQUIRED, non-empty, finite values, length F
    "psd": [ [p, ...], ... ]               // REQUIRED, shape [n_channels][F]
  },

  "centroid": {
    "time_relative": [t0, t1, ...],        // REQUIRED, non-empty, length Tc
    "values": [ [c, ...], ... ]            // REQUIRED, finite values, shape [n_channels][Tc]
  },

  "geometry": {
    "time": [t0, t1, ...],                 // REQUIRED, non-empty, finite values, length Tg
    "centroid":              [ [..], ... ], // [n_channels][Tg]
    "spread":                [ [..], ... ],
    "entropy":               [ [..], ... ],
    "flatness":              [ [..], ... ],
    "edge95":                [ [..], ... ],
    "alpha_relative_power":  [ [..], ... ],
    "area_normalized_psd": {                // optional
      "frequencies": [f0, ...],
      "psd": [ [p, ...], ... ]             // [n_channels][F2]
    }
  },

  "channel_summary": [                      // one entry per channel, in channels order
    {
      "channel": "Fp1",
      "hemisphere": "L",                    // "L" | "R" | "M" | ""
      "region": "frontal",                  // free text; used by region filters
      "has_clear_alpha_peak": true,
      "alpha_relative_power": 0.31,
      "spectral_centroid_hz": 11.2,
      "spectral_spread_hz": 3.4,
      "spectral_entropy": 0.78,
      "spectral_flatness": 0.12,
      "edge95_hz": 24.0,
      "alpha_peak_frequency_hz": 10.5,
      "sliding_alpha_relative_mean": 0.29
    }
  ]
}
```

### Hard validation rules (the dataset is rejected if any fail)

- `meta.channels` is a **non-empty array**. Its length `N` is the channel count.
- `meta.channels.length <= 4096` by default. This is a configurable denial-of-service
  ceiling, not a montage limit; HD-MEA datasets with hundreds or thousands of electrodes
  are valid below the configured ceiling.
- `meta.n_channels`, when present, is a positive integer and equals `meta.channels.length`.
- `welch_psd.frequencies` is a **non-empty array** of finite numbers.
- `welch_psd.psd` is an array with `welch_psd.psd.length === N`; every row is an array
  with `row.length === welch_psd.frequencies.length`, and every value is finite.
- `centroid.time_relative` is a **non-empty array**.
- `centroid.values` is an array with `centroid.values.length === N`; every row is an
  array with `row.length === centroid.time_relative.length`, and every value is finite.
- `geometry.time` is a **non-empty array** of finite numbers.

Finite means no `NaN`, `+Infinity`, or `-Infinity`.

Everything else is best-effort: missing optional fields degrade a panel, they do not
break the dashboard. Keep channel-major rows aligned to `meta.channels` order — index `i`
in every per-channel array is the same physical channel as `meta.channels[i]`.

---

## 2. Import archives (ZIP)

The viewer accepts three drop types. File names are matched by **suffix**, so nested
folders inside the ZIP are fine.

| Drop | Detected by | Becomes |
|---|---|---|
| `data.json` (raw or zipped) | a `data.json` member | used directly |
| Combined CSV export ZIP | both Welch **and** geometry member sets present | converted |
| Welch ZIP **+** geometry ZIP (paired) | one ZIP with each set | converted as a pair |

**Welch member set:**
- `eeg_welch_centroid_export.json` — carries `metadata.channel_names`
- `welch_psd_wide.csv` — column `frequency_hz` + one column per channel
- `spectral_centroid_wide.csv` — column `time_relative_sec` + one column per channel

**Geometry member set:**
- `spectral_centroid_geometry_metadata.json` — `segment_start_sec`, `segment_end_sec`,
  `analysis_sample_rate_hz`, `welch_window_sec`, `welch_overlap`, `sliding_window_sec`,
  `sliding_step_sec`
- `spectral_centroid_channel_summary.csv` — keyed by column `channel`
- `mean_psd_area_normalized_wide.csv` — column `frequency_hz` + per-channel columns
- six sliding wide CSVs, each `time_relative_sec` + per-channel columns:
  `sliding_spectral_centroid_wide.csv`, `sliding_spectral_spread_wide.csv`,
  `sliding_spectral_entropy_wide.csv`, `sliding_spectral_flatness_wide.csv`,
  `sliding_spectral_edge95_wide.csv`, `sliding_alpha_relative_power_wide.csv`

Wide CSVs are channel-per-column with a single leading axis column (`frequency_hz` or
`time_relative_sec`). All sliding files must share the same time axis. Channel columns are
taken from `metadata.channel_names` when present.

> Recommended target for new backends: **emit `data.json` directly** (Section 1). The CSV
> archive path exists for the existing soulsyrup1 notebook exports; it is more fragile
> (exact filenames, matching axes) than emitting the canonical object.

---

## 3. Live WebSocket contract

Default endpoint: `ws://127.0.0.1:8766`. The backend streams **raw signal samples**; the
viewer windows them and computes Welch PSD + spectral metrics in a Web Worker
(`js/workers/dsp-worker.js`), then renders the same shapes as the saved dataset.

Defaults until overridden by handshake metadata: **32 channels, 256 Hz**, 4 s window,
50% overlap, recompute every 250 ms.

### Accepted raw payloads (any one of)

- **Binary** `ArrayBuffer` of `Float32`, sample-major interleaved by channel:
  `[s0c0, s0c1, ..., s0cN-1, s1c0, ...]`. Length must be a multiple of `N`.
- **JSON one sample**: `[c0, c1, ..., cN-1]`
- **JSON sample-major chunk**: `{ "samples": [[c0,...cN-1], [c0,...], ...] }`
  (also accepted under `data`, `values`, `frame`, `frames`, `raw`, `eeg`, `eeg_data`)
- **JSON channel-major chunk**: `{ "samples_by_channel": { "Cz": [...], ... } }`
  or a 2-D array with one row per channel (also under `data_by_channel`)

### Optional handshake / per-message metadata (preferred when present)

The viewer reads these from the top level or a nested `meta` object and reconfigures live:

- channel names: `channel_names` or `channels`
- channel count: `n_channels` / `channel_count`
- sample rate: `sampling_rate_hz` / `sample_rate_hz` / `sampling_rate` / `sample_rate` / `sr` / `fs`

Sending channel names once at connect is the cleanest way to drive a non-default montage.

### What the viewer derives per live frame

Per channel, every recompute: `centroid`, `spread`, `entropy` (normalized), `flatness`,
`edge95`, `alpha_relative_power`, plus the Welch PSD. These populate the same
`welch_psd` / `centroid` / `geometry` / `channel_summary` structures as Section 1, so live
and replay render through identical code paths.

---

## Versioning

Treat this document as the contract version of record. When a field is added, keep it
**optional** so older backends keep working; only promote a field to a hard validation
rule (Section 1) in a coordinated change, because that rejects datasets that lack it.
