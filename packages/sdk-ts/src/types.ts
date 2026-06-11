/* eslint-disable */
/* Generated from ../../contracts/schema/dataset.schema.json. Do not edit by hand. */

export type Channels = string[];
export type NChannels = number | null;
export type SegmentDurationSec = number | null;
export type SamplingRateAnalysisHz = number | null;
export type WelchWindowSec = number | null;
export type WelchOverlapFraction = number | null;
export type SlidingWindowSec = number | null;
export type SlidingStepSec = number | null;
export type Source = string | null;
export type AnalysisBy = string | null;
export type Frequencies = number[];
export type Psd = number[][];
export type TimeRelative = number[];
export type Values = number[][];
export type Time = number[];
export type Centroid1 = number[][] | null;
export type Spread = number[][] | null;
export type Entropy = number[][] | null;
export type Flatness = number[][] | null;
export type Edge95 = number[][] | null;
export type AlphaRelativePower = number[][] | null;
export type ChannelSummary = ChannelSummary1[] | null;
export type Channel = string;
export type Hemisphere = ("L" | "R" | "M" | "") | null;
export type Region = string | null;
export type HasClearAlphaPeak = boolean | null;
export type AlphaRelativePower1 = number | null;
export type SpectralCentroidHz = number | null;
export type SpectralSpreadHz = number | null;
export type SpectralEntropy = number | null;
export type SpectralFlatness = number | null;
export type Edge95Hz = number | null;
export type AlphaPeakFrequencyHz = number | null;
export type SlidingAlphaRelativeMean = number | null;

export interface Dataset {
  meta: Meta;
  welch_psd: WelchPsd;
  centroid: Centroid;
  geometry: Geometry;
  channel_summary?: ChannelSummary;
  [k: string]: unknown;
}
export interface Meta {
  channels: Channels;
  n_channels?: NChannels;
  segment_duration_sec?: SegmentDurationSec;
  sampling_rate_analysis_hz?: SamplingRateAnalysisHz;
  welch_window_sec?: WelchWindowSec;
  welch_overlap_fraction?: WelchOverlapFraction;
  sliding_window_sec?: SlidingWindowSec;
  sliding_step_sec?: SlidingStepSec;
  source?: Source;
  analysis_by?: AnalysisBy;
  [k: string]: unknown;
}
export interface WelchPsd {
  frequencies: Frequencies;
  psd: Psd;
  [k: string]: unknown;
}
export interface Centroid {
  time_relative: TimeRelative;
  values: Values;
  [k: string]: unknown;
}
export interface Geometry {
  time: Time;
  centroid?: Centroid1;
  spread?: Spread;
  entropy?: Entropy;
  flatness?: Flatness;
  edge95?: Edge95;
  alpha_relative_power?: AlphaRelativePower;
  area_normalized_psd?: WelchPsd | null;
  [k: string]: unknown;
}
export interface ChannelSummary1 {
  channel: Channel;
  hemisphere?: Hemisphere;
  region?: Region;
  has_clear_alpha_peak?: HasClearAlphaPeak;
  alpha_relative_power?: AlphaRelativePower1;
  spectral_centroid_hz?: SpectralCentroidHz;
  spectral_spread_hz?: SpectralSpreadHz;
  spectral_entropy?: SpectralEntropy;
  spectral_flatness?: SpectralFlatness;
  edge95_hz?: Edge95Hz;
  alpha_peak_frequency_hz?: AlphaPeakFrequencyHz;
  sliding_alpha_relative_mean?: SlidingAlphaRelativeMean;
  [k: string]: unknown;
}
