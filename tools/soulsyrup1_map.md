# soulsyrup1 Repository Map

Source: `https://github.com/soulsyrup1/Complete-Neural-Signal-Analysis`  
Local inspection clone: `/tmp/soulsyrup1-repo`  
Inspected commit: `7be1bc1`  
Scan scope: all checked-in `.ipynb` and `.py` files found within three directory levels; 33 source files total.

## Snapshot notes

The current repository snapshot is source-first. The requested folders `Visualization/`, `Kuramoto Model_files/`, `Phase Syncronization Analysis_files/`, `EEG Channel Network_files/`, `Phase Space_files/`, `2dembedding_data/`, and `extracted_features/` are not present as checked-in top-level folders in this clone. The available analysis sources are split notebook folders plus the shared `Library/neural_signal_analysis/` package. Generated result caches are mostly referenced in notebooks as local `results/`, `embedding_data/`, `plots/`, `.csv`, `.npy`, `.npz`, or `.pt` outputs, but are not checked in.

| Folder | Input data expected by sources | Produced arrays / artifacts | Shape / dtype hints | Precomputed outputs in clone | Can compute from current SpeedMouse data? |
|---|---|---|---|---|---|
| `Data_Loading_and_Variable_Assigning_files/` | GX `EEG_DS_Struct_0101.mat`, `stim_data.xlsx`, MATLAB `DSamp` structure | `eeg_data_with_channels.npy`, `eeg_df.csv`, `merged_stim_df.csv`, `merged_eeg_stim_df.csv`, `rnn_X_data_combined.npy` | Raw EEG is sample x channel; current GX file uses `DSamp/EEGdata` `(3183253, 35)` float64 | Source notebook only | No. Requires raw MAT and stimulus workbook; not derivable from `data.json` alone |
| `Spectral Analysis/` | `eeg_data_with_channels.npy` or raw EEG arrays, sampling rate, channel labels | Welch PSD, spectral centroid, spread, entropy, flatness, edge frequency, channel summaries | SpeedMouse already stores `welch_psd.psd` `32 x 217` and `geometry.*` `32 x 420` numeric arrays | Source notebooks only | Mostly yes. Current `data.json` already contains the core spectral outputs |
| `Dynamical_Systems/` | `eeg_data_with_channels.npy`, delay-embedding settings, downstream embedding/result caches | Recurrence/RQA/CCM CSVs, Lyapunov summaries, delay embedding plots, rankings, zip bundles | Lyapunov is channel-level scalar or dimension-aware summaries; embeddings are time x dimension arrays | No checked-in `embedding_data/` or `results/` cache | Raw GX required for faithful regeneration. Current Phase 3 adds per-channel `lyapunov_exponent` |
| `Entropy/` | `eeg_data_with_channels.npy`, optional intermediate `_data.npy` / `_trimmed.npy` arrays | Approximate entropy, permutation entropy, spectral entropy, transfer entropy CSV/NPZ outputs and heatmaps | Channel-level or pairwise channel matrices depending on method | Source notebooks only | Partial. `data.json.geometry.entropy` is present, but transfer/permutation/approximate entropy need raw EEG |
| `Fractal/` | `eeg_data_with_channels.npy`, band/residual intermediates, q-range/window settings | Higuchi FD, Hurst/MFDFA/Petrosian/Hall-Wood/Sevcik/Madogram/Variogram outputs | Higuchi FD can be per-channel or sliding channel x time | Source notebooks only | Partial. Current Phase 3 adds `geometry.higuchi_fd` as `32 x 420`; other fractal families need raw recomputation |
| `Geometry/` | `eeg_data_with_channels.npy`, embedding and Riemannian intermediate caches, spectral feature CSVs | Manifold, curvature, geodesic, bundle atlas CSV/NPZ/PNG outputs | Current SpeedMouse geometry metrics are channel x time; notebook geometry may use embedding point clouds | No checked-in embedding/Riemannian caches | Partial. `data.json.geometry.*` supports lightweight geometry views; full notebook geometry needs raw/intermediate caches |
| `Topology/` | `eeg_data_with_channels.npy`, 2D/3D embeddings, UMAP/t-SNE/PCA/graph intermediates | Persistence diagrams, landscapes, Betti heatmaps, topology rankings, CSV/PNG/NPZ outputs | TDA diagrams are birth/death pairs; SpeedMouse exports finite `h0`, `h1`, and `32 x 6` point cloud | Source notebook plus `Topology.ipynb`; no generated topology cache | Partial. Current Phase 3 adds a compact `tda` section, not the full persistence-landscape pipeline |
| `Quantum Analysis/` | `eeg_data_with_channels.npy`, 2D/3D embeddings, density/codebook caches | `quantum_like_analysis/`, `quantum_like_codebook_analysis/`, operator CSV/NPZ/plots | Density/operator matrices and codebook embeddings are referenced as generated artifacts | Source notebooks only | Partial at best. Raw EEG and embedding caches are needed |
| `Neural Net_files/` | Aggregated result registry, embeddings, prediction/logit tensors | Patient-level predictions, embeddings, logits, diagnostics | Notebook output references `.pt`, `.csv`, and model output paths | Source notebook only | No. This is downstream ML over many generated outputs, not a direct SpeedMouse view source |
| `Library/neural_signal_analysis/` | Python arrays plus method parameters | Utility functions for FFT, Welch PSD, spectral centroid/edge/entropy, phase-space embedding, Higuchi FD, transfer entropy | Function-level helpers; shapes depend on caller | Source package only | Yes for selected helpers, but the current SpeedMouse scripts use local focused implementations for reproducibility |

## SpeedMouse reuse decision

The current SpeedMouse expansion uses the parts that are computable and compact:

- `polar_chronomap`: derived entirely from `data.geometry.alpha_relative_power` and `channel_summary`.
- `channel_network`: derived from correlations across existing `geometry.*` metric arrays.
- `kuramoto`, `phase_synchrony`, `geometry.higuchi_fd`, and `channel_summary.lyapunov_exponent`: computed from the downloaded GX `.mat` file.
- `tda`: computed from the current six channel-level geometry feature means as a compact point cloud.

Full notebook-equivalent outputs for transfer entropy, quantum analysis, Riemannian geometry, topology landscapes, and neural-net outputs still require raw/intermediate pipeline regeneration beyond the current UI expansion scope.
