// Live microphone pitch detection: NSDF (McLeod) autocorrelation.
// Returns midi float or null per analyse() call.
'use strict';

class PitchDetector {
  constructor() {
    this.ctx = null;
    this.analyser = null;
    this.buf = null;
    this.sr = 48000;
    this.level = 0;
  }

  async start(echoCancellation = true, deviceId = null) {
    if (!this.ctx) this.ctx = new AudioContext();
    if (this.stream) this.stream.getTracks().forEach((t) => t.stop());
    if (this.src) this.src.disconnect();
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        ...(deviceId ? { deviceId: { exact: deviceId } } : {}),
        echoCancellation,
        noiseSuppression: false,
        autoGainControl: false,
      },
    });
    this.sr = this.ctx.sampleRate;
    this.src = this.ctx.createMediaStreamSource(stream);
    if (!this.analyser) {
      this.analyser = this.ctx.createAnalyser();
      this.analyser.fftSize = 2048;
      this.buf = new Float32Array(this.analyser.fftSize);
    }
    this.src.connect(this.analyser);
    this.stream = stream;
    // A context created before any user gesture starts suspended and the
    // analyser reads pure zeros. Once capture is granted we may resume.
    this.resume();
  }

  resume() {
    if (this.ctx && this.ctx.state !== 'running') this.ctx.resume().catch(() => {});
  }

  deviceLabel() {
    const tr = this.stream && this.stream.getAudioTracks()[0];
    return tr ? tr.label : '';
  }

  stop() {
    if (this.stream) this.stream.getTracks().forEach((t) => t.stop());
    if (this.ctx) this.ctx.close();
    this.ctx = null;
  }

  // NSDF over lag range for 75..800 Hz
  analyse() {
    if (!this.analyser) return null;
    this.analyser.getFloatTimeDomainData(this.buf);
    const x = this.buf;
    const n = x.length;
    let rms = 0;
    for (let i = 0; i < n; i++) rms += x[i] * x[i];
    rms = Math.sqrt(rms / n);
    this.level = rms;
    if (rms < 0.008) return null; // silence gate

    const minLag = Math.floor(this.sr / 800);
    const maxLag = Math.min(Math.floor(this.sr / 75), n - 2);
    const nsdf = new Float32Array(maxLag + 1);
    for (let lag = minLag; lag <= maxLag; lag++) {
      let ac = 0, m = 0;
      const lim = n - lag;
      for (let i = 0; i < lim; i++) {
        const a = x[i], b = x[i + lag];
        ac += a * b;
        m += a * a + b * b;
      }
      nsdf[lag] = m > 0 ? (2 * ac) / m : 0;
    }
    // pick first major peak above threshold (avoids octave-down errors)
    let best = -1, bestVal = 0;
    let maxVal = 0;
    for (let lag = minLag; lag <= maxLag; lag++) maxVal = Math.max(maxVal, nsdf[lag]);
    if (maxVal < 0.55) return null;
    const thr = Math.max(0.8 * maxVal, 0.5);
    for (let lag = minLag + 1; lag < maxLag; lag++) {
      if (nsdf[lag] > thr && nsdf[lag] >= nsdf[lag - 1] && nsdf[lag] >= nsdf[lag + 1]) {
        best = lag; bestVal = nsdf[lag];
        break;
      }
    }
    if (best < 0) return null;
    // parabolic interpolation
    const y0 = nsdf[best - 1], y1 = nsdf[best], y2 = nsdf[best + 1];
    const denom = y0 - 2 * y1 + y2;
    const shift = denom !== 0 ? 0.5 * (y0 - y2) / denom : 0;
    const period = best + shift;
    const f0 = this.sr / period;
    if (f0 < 60 || f0 > 900) return null;
    const midi = 69 + 12 * Math.log2(f0 / 440);
    return { midi, clarity: bestVal, rms };
  }
}

window.PitchDetector = PitchDetector;
