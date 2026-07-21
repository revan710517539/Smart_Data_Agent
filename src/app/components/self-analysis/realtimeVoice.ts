// Fun-ASR realtime does not return speaker diarization labels. Enrol the first
// contiguous voiced frames locally and gate PCM before it reaches the ASR
// socket, so rejected speakers cannot become transcript text.
export const voiceprintEnrollmentFrames = 6;

export type RealtimeVoiceTrigger = "realtime_voice_silence" | "realtime_voice_keyword";
export type SpeakerDecision = "unknown" | "calibrating" | "accepted" | "rejected";

export type VoiceprintProfile = {
  centroid: number[];
  spread: number[];
  samples: number;
};

export type RealtimeSpeakerGateState = {
  profile: VoiceprintProfile | null;
  decision: SpeakerDecision;
  silenceFrames: number;
  mismatchFrames: number;
};

export type SpeakerGateFrame = {
  state: RealtimeSpeakerGateState;
  accepted: boolean;
  voiced: boolean;
  justLocked: boolean;
  rejectedSpeakerStarted: boolean;
  distance: number | null;
};

export function createRealtimeSpeakerGateState(): RealtimeSpeakerGateState {
  return { profile: null, decision: "unknown", silenceFrames: 0, mismatchFrames: 0 };
}

export function gateRealtimeSpeakerFrame(
  current: RealtimeSpeakerGateState,
  channel: Float32Array,
  sampleRate: number,
): SpeakerGateFrame {
  const features = voiceprintFeatures(channel, sampleRate);
  if (features.rms < 0.012) {
    const silenceFrames = current.silenceFrames + 1;
    return {
      state: {
        ...current,
        silenceFrames,
        decision: silenceFrames >= 2 && current.profile?.samples === voiceprintEnrollmentFrames
          ? "unknown"
          : current.decision,
        mismatchFrames: silenceFrames >= 2 ? 0 : current.mismatchFrames,
      },
      accepted: true,
      voiced: false,
      justLocked: false,
      rejectedSpeakerStarted: false,
      distance: null,
    };
  }

  if (!current.profile || current.profile.samples < voiceprintEnrollmentFrames) {
    const profile = enrollVoiceprint(current.profile, features.vector);
    return {
      state: {
        profile,
        decision: profile.samples === voiceprintEnrollmentFrames ? "accepted" : "calibrating",
        silenceFrames: 0,
        mismatchFrames: 0,
      },
      accepted: true,
      voiced: true,
      justLocked: profile.samples === voiceprintEnrollmentFrames,
      rejectedSpeakerStarted: false,
      distance: 0,
    };
  }

  const distance = voiceprintDistance(current.profile, features.vector);
  const utteranceStart = current.decision === "unknown" || current.silenceFrames >= 2;
  let decision = current.decision;
  let mismatchFrames = current.mismatchFrames;
  if (utteranceStart) {
    decision = distance <= 0.6 ? "accepted" : "rejected";
    mismatchFrames = 0;
  } else if (decision === "accepted") {
    mismatchFrames = distance > 0.95 ? mismatchFrames + 1 : 0;
    if (mismatchFrames >= 2) decision = "rejected";
  }
  const accepted = decision !== "rejected";
  const profile = accepted && distance <= 0.6
    ? enrollVoiceprint(current.profile, features.vector, voiceprintEnrollmentFrames)
    : current.profile;
  return {
    state: { profile, decision, silenceFrames: 0, mismatchFrames },
    accepted,
    voiced: true,
    justLocked: false,
    rejectedSpeakerStarted: decision === "rejected" && current.decision !== "rejected",
    distance,
  };
}

export function extractRealtimeVoiceAnalysisCommand(text: string) {
  const triggered = /开始\s*分析/u.test(text);
  if (!triggered) return { triggered: false, query: text.trim() };
  const query = text
    .replace(/(?:请|现在|那就)?\s*开始\s*分析(?:一下|吧)?[，,。.!！]?/gu, " ")
    .replace(/\s+/g, " ")
    .replace(/^[，,。.!！;；:：\s]+|[，,。.!！;；:：\s]+$/gu, "")
    .trim();
  return { triggered: true, query };
}

export function isRealtimeVoiceTrigger(value: string): value is RealtimeVoiceTrigger {
  return value === "realtime_voice_silence" || value === "realtime_voice_keyword";
}

function enrollVoiceprint(profile: VoiceprintProfile | null, vector: number[], maxSamples = Number.POSITIVE_INFINITY) {
  if (!profile) return { centroid: [...vector], spread: vector.map(() => 0), samples: 1 };
  const samples = Math.min(profile.samples + 1, maxSamples);
  const weight = samples >= maxSamples ? 0.05 : 1 / samples;
  const centroid = profile.centroid.map((value, index) => value + ((vector[index] || 0) - value) * weight);
  const spread = profile.spread.map((value, index) => value + (Math.abs((vector[index] || 0) - centroid[index]) - value) * weight);
  return { centroid, spread, samples };
}

function voiceprintDistance(profile: VoiceprintProfile, vector: number[]) {
  const baseScales = [0.14, 0.1, 0.16, 0.12, 0.12, ...Array(Math.max(0, vector.length - 5)).fill(0.055)];
  const weights = [1.5, 4, 1, 1.5, 1.2, ...Array(Math.max(0, vector.length - 5)).fill(2)];
  let totalWeight = 0;
  const weighted = profile.centroid.map((value, index) => {
    const adaptiveScale = Math.max(baseScales[index] || 0.055, (profile.spread[index] || 0) * 3.5);
    const weight = weights[index] || 1;
    totalWeight += weight;
    return Math.min(3, Math.abs((vector[index] || 0) - value) / adaptiveScale) * weight;
  });
  return weighted.reduce((sum, value) => sum + value, 0) / Math.max(1, totalWeight);
}

export function voiceprintFeatures(channel: Float32Array, sampleRate: number) {
  let energy = 0;
  let zeroCrossings = 0;
  let previous = channel[0] || 0;
  for (let index = 0; index < channel.length; index += 1) {
    const value = channel[index] || 0;
    energy += value * value;
    if ((value >= 0) !== (previous >= 0)) zeroCrossings += 1;
    previous = value;
  }
  const rms = Math.sqrt(energy / Math.max(1, channel.length));
  const zeroCrossingRate = zeroCrossings / Math.max(1, channel.length);
  const spectrum = powerSpectrum(channel);
  const bandEdges = [60, 120, 180, 260, 380, 560, 820, 1200, 1800, 2800, 4500, 7500]
    .filter((frequency) => frequency < sampleRate / 2);
  if (bandEdges[bandEdges.length - 1] !== sampleRate / 2) bandEdges.push(sampleRate / 2);
  const rawBands = bandEdges.slice(0, -1).map((lower, index) => {
    const upper = bandEdges[index + 1] || sampleRate / 2;
    let energy = 0;
    for (let bin = 1; bin < spectrum.length; bin += 1) {
      const frequency = (bin * sampleRate) / (spectrum.length * 2);
      if (frequency >= lower && frequency < upper) energy += spectrum[bin] || 0;
    }
    return Math.log1p(energy);
  });
  const bandTotal = rawBands.reduce((sum, value) => sum + value, 0) || 1;
  const bands = rawBands.map((value) => value / bandTotal);
  const spectralTotal = spectrum.reduce((sum, value) => sum + value, 0) || 1;
  const centroid = spectrum.reduce((sum, value, index) => sum + value * ((index * sampleRate) / (spectrum.length * 2)), 0)
    / spectralTotal / Math.max(1, sampleRate / 2);
  let cumulative = 0;
  let rolloff = 0;
  for (let index = 0; index < spectrum.length; index += 1) {
    cumulative += (spectrum[index] || 0) / spectralTotal;
    if (cumulative >= 0.9) {
      rolloff = ((index * sampleRate) / (spectrum.length * 2)) / Math.max(1, sampleRate / 2);
      break;
    }
  }
  const pitch = estimatePitch(channel, sampleRate);
  return {
    rms,
    vector: [
      zeroCrossingRate * 4,
      pitch.frequency / 400,
      pitch.confidence,
      centroid,
      rolloff,
      ...bands,
    ],
  };
}

function powerSpectrum(channel: Float32Array) {
  const size = 1024;
  const real = new Float64Array(size);
  const imaginary = new Float64Array(size);
  const offset = Math.max(0, channel.length - size);
  for (let index = 0; index < size; index += 1) {
    const window = 0.5 - 0.5 * Math.cos((2 * Math.PI * index) / (size - 1));
    real[index] = (channel[offset + index] || 0) * window;
  }
  for (let index = 1, swap = 0; index < size; index += 1) {
    let bit = size >> 1;
    for (; swap & bit; bit >>= 1) swap ^= bit;
    swap ^= bit;
    if (index < swap) {
      [real[index], real[swap]] = [real[swap], real[index]];
    }
  }
  for (let length = 2; length <= size; length <<= 1) {
    const angle = (-2 * Math.PI) / length;
    for (let start = 0; start < size; start += length) {
      for (let index = 0; index < length / 2; index += 1) {
        const cosine = Math.cos(angle * index);
        const sine = Math.sin(angle * index);
        const even = start + index;
        const odd = even + length / 2;
        const oddReal = real[odd] * cosine - imaginary[odd] * sine;
        const oddImaginary = real[odd] * sine + imaginary[odd] * cosine;
        real[odd] = real[even] - oddReal;
        imaginary[odd] = imaginary[even] - oddImaginary;
        real[even] += oddReal;
        imaginary[even] += oddImaginary;
      }
    }
  }
  return Array.from({ length: size / 2 }, (_, index) => real[index] ** 2 + imaginary[index] ** 2);
}

function estimatePitch(channel: Float32Array, sampleRate: number) {
  const start = Math.max(0, channel.length - Math.min(channel.length, 2048));
  const minLag = Math.max(2, Math.floor(sampleRate / 350));
  const maxLag = Math.min(channel.length - start - 2, Math.ceil(sampleRate / 70));
  let bestLag = minLag;
  let bestCorrelation = 0;
  for (let lag = minLag; lag <= maxLag; lag += 1) {
    let correlation = 0;
    let normA = 0;
    let normB = 0;
    for (let index = start; index + lag < channel.length; index += 2) {
      const first = channel[index] || 0;
      const second = channel[index + lag] || 0;
      correlation += first * second;
      normA += first * first;
      normB += second * second;
    }
    const normalized = correlation / Math.sqrt(Math.max(1e-9, normA * normB));
    if (normalized > bestCorrelation) {
      bestCorrelation = normalized;
      bestLag = lag;
    }
  }
  return {
    frequency: bestCorrelation >= 0.2 ? sampleRate / bestLag : 0,
    confidence: Math.max(0, Math.min(1, bestCorrelation)),
  };
}
