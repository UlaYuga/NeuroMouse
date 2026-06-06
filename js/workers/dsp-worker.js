self.addEventListener("message", (event) => {
  const startedAt = performance.now();
  const data = event.data ?? {};
  if (data.type !== "compute") return;

  try {
    const samplingRate = Number(data.sampling_rate);
    const windowSec = Number(data.window_sec) || 4;
    const overlap = Number.isFinite(Number(data.overlap)) ? Number(data.overlap) : 0.5;
    if (!Number.isFinite(samplingRate) || samplingRate <= 0) {
      throw new Error("DSP worker requires a positive sampling_rate");
    }

    const channelResults = data.buffers.map((buffer) => {
      const signal = buffer instanceof Float32Array ? buffer : new Float32Array(buffer);
      const full = welchPSD(signal, samplingRate, windowSec, overlap);
      const trimmed = trimFrequencyBand(full.freqs, full.psd, 1, 55);
      return {
        frequencies: trimmed.freqs,
        psd: Array.from(trimmed.psd),
        metrics: spectralMetrics(trimmed.psd, trimmed.freqs),
      };
    });

    self.postMessage({
      type: "result",
      frequencies: channelResults[0]?.frequencies ?? [],
      psd: channelResults.map((result) => result.psd),
      metrics: channelResults.map((result) => result.metrics),
      compute_ms: performance.now() - startedAt,
    });
  } catch (error) {
    self.postMessage({
      type: "error",
      message: error.message,
    });
  }
});

function fft(re, im) {
  const n = re.length;
  for (let i = 1, j = 0; i < n; i += 1) {
    let bit = n >> 1;
    for (; j & bit; bit >>= 1) j ^= bit;
    j ^= bit;
    if (i < j) {
      [re[i], re[j]] = [re[j], re[i]];
      [im[i], im[j]] = [im[j], im[i]];
    }
  }

  for (let len = 2; len <= n; len <<= 1) {
    const angle = (-2 * Math.PI) / len;
    const wRe = Math.cos(angle);
    const wIm = Math.sin(angle);
    for (let i = 0; i < n; i += len) {
      let uRe = 1;
      let uIm = 0;
      for (let j = 0; j < len / 2; j += 1) {
        const even = i + j;
        const odd = even + len / 2;
        const vRe = re[odd] * uRe - im[odd] * uIm;
        const vIm = re[odd] * uIm + im[odd] * uRe;
        re[odd] = re[even] - vRe;
        im[odd] = im[even] - vIm;
        re[even] += vRe;
        im[even] += vIm;
        [uRe, uIm] = [uRe * wRe - uIm * wIm, uRe * wIm + uIm * wRe];
      }
    }
  }
}

function welchPSD(signal, samplingRate, windowSec = 4, overlapFrac = 0.5) {
  const winLen = Math.min(signal.length, nextPow2(Math.round(windowSec * samplingRate)));
  if (winLen < 8) {
    throw new Error("DSP worker needs at least 8 samples for Welch PSD");
  }
  const step = Math.max(1, Math.round(winLen * (1 - overlapFrac)));
  const hann = Array.from({ length: winLen }, (_, index) => (
    0.5 * (1 - Math.cos((2 * Math.PI * index) / (winLen - 1)))
  ));
  const hannPower = hann.reduce((sum, value) => sum + value * value, 0);
  const psd = new Float64Array(winLen / 2 + 1);
  let count = 0;

  for (let start = 0; start + winLen <= signal.length; start += step) {
    const re = new Float64Array(winLen);
    const im = new Float64Array(winLen);
    for (let index = 0; index < winLen; index += 1) {
      re[index] = signal[start + index] * hann[index];
    }
    fft(re, im);
    for (let index = 0; index <= winLen / 2; index += 1) {
      let value = (re[index] * re[index] + im[index] * im[index]) / (samplingRate * hannPower);
      if (index > 0 && index < winLen / 2) value *= 2;
      psd[index] += value;
    }
    count += 1;
  }

  for (let index = 0; index < psd.length; index += 1) {
    psd[index] /= Math.max(1, count);
  }

  const freqs = Array.from({ length: winLen / 2 + 1 }, (_, index) => (index * samplingRate) / winLen);
  return { psd, freqs };
}

function trimFrequencyBand(freqs, psd, minHz, maxHz) {
  const nextFreqs = [];
  const nextPsd = [];
  for (let index = 0; index < freqs.length; index += 1) {
    if (freqs[index] >= minHz && freqs[index] <= maxHz) {
      nextFreqs.push(freqs[index]);
      nextPsd.push(psd[index]);
    }
  }
  return {
    freqs: nextFreqs,
    psd: nextPsd,
  };
}

function spectralMetrics(psd, freqs) {
  const values = psd.map((value) => Math.max(Number(value) || 0, 1e-18));
  const sumPower = values.reduce((sum, value) => sum + value, 0) || 1e-18;
  const probabilities = values.map((value) => value / sumPower);
  const centroid = freqs.reduce((sum, frequency, index) => sum + frequency * probabilities[index], 0);
  const spread = Math.sqrt(freqs.reduce((sum, frequency, index) => (
    sum + ((frequency - centroid) ** 2) * probabilities[index]
  ), 0));
  const entropyBits = -probabilities.reduce((sum, probability) => (
    sum + (probability > 0 ? probability * Math.log2(probability) : 0)
  ), 0);
  const entropyNormalized = entropyBits / Math.max(1e-18, Math.log2(probabilities.length || 2));
  const geometricMean = Math.exp(values.reduce((sum, value) => sum + Math.log(value), 0) / values.length);
  const arithmeticMean = sumPower / values.length;
  const flatness = geometricMean / Math.max(1e-18, arithmeticMean);
  const edge95 = spectralEdge(values, freqs, sumPower, 0.95);
  const alphaPower = values.reduce((sum, value, index) => (
    freqs[index] >= 8 && freqs[index] <= 13 ? sum + value : sum
  ), 0);

  return {
    centroid,
    spread,
    entropy: entropyBits,
    entropy_normalized: entropyNormalized,
    flatness,
    edge95,
    alpha_relative_power: alphaPower / sumPower,
  };
}

function spectralEdge(values, freqs, sumPower, fraction) {
  let cumulative = 0;
  for (let index = 0; index < values.length; index += 1) {
    cumulative += values[index];
    if (cumulative >= fraction * sumPower) return freqs[index];
  }
  return freqs.at(-1) ?? 0;
}

function nextPow2(value) {
  return 2 ** Math.ceil(Math.log2(Math.max(2, value)));
}
