// PhoneSDK display adapter. The caller owns the SDK instance and its lifecycle.
//
// The displayed bubble persists until explicitly replaced: only a frame with
// status "ready" may change what's shown (a null prompt on a ready frame means
// "explicitly nothing to say", which still clears the bubble). Every other
// status -- thinking, listening, unavailable, expired -- is a no-op, so a
// slow turn or an idle gap never blanks the lens on a timer.
//
// Rendering itself happens on-device: this sends a small binary payload over
// gm.plugin.sendMessage to the paired "ProSe Glasses HUD" native plugin
// (integrations/memomind/glasses-hud), which draws bordered boxes and a real
// momentum bar with LVGL. See that plugin's plugin.c header comment for the
// exact wire layout this encoder must match.
const PROSE_HUD_CHANNEL = 20560;
// Must match prose/copilot.py's MOOD_LABELS tuple order exactly.
const MOOD_LABELS = ['calm', 'confident', 'tense', 'defensive', 'frustrated', 'neutral'];

function encodeHudMessage({ moodLabel, moodIntensity, momentumPct, speaker, prompt }) {
  const encoder = new TextEncoder();
  const moodIndex = MOOD_LABELS.indexOf(moodLabel);
  const moodIntensityByte = moodLabel && moodIndex >= 0
    ? Math.max(1, Math.min(5, Math.round(moodIntensity) || 0)) : 0;
  const momentumByte = Number.isFinite(momentumPct)
    ? Math.max(0, Math.min(100, Math.round(momentumPct))) : 50;
  const speakerBytes = encoder.encode((speaker || '').slice(0, 40)).slice(0, 255);
  const promptBytes = encoder.encode(prompt || '').slice(0, 560);

  const buffer = new Uint8Array(4 + speakerBytes.length + 2 + promptBytes.length);
  buffer[0] = moodIntensityByte;
  buffer[1] = moodIndex >= 0 ? moodIndex : 0;
  buffer[2] = momentumByte;
  buffer[3] = speakerBytes.length;
  buffer.set(speakerBytes, 4);
  const promptLenOffset = 4 + speakerBytes.length;
  buffer[promptLenOffset] = promptBytes.length & 0xff;
  buffer[promptLenOffset + 1] = (promptBytes.length >> 8) & 0xff;
  buffer.set(promptBytes, promptLenOffset + 2);
  return buffer;
}

export class MemoMindDisplay {
  constructor(gm, onError = () => {}) {
    this.gm = gm;
    this.onError = onError;
    this.latest = null;
    this.running = null;
    this.stopped = false;
    this.lastSeq = -1;
  }

  push(frame) {
    if (this.stopped) return Promise.resolve();
    if (!Number.isInteger(frame.seq) || frame.seq <= this.lastSeq) return Promise.resolve();
    if (frame.prompt != null && typeof frame.prompt !== 'string') {
      return Promise.reject(new TypeError('HUD prompt must be text or null'));
    }
    this.lastSeq = frame.seq;
    if (frame.status !== 'ready') return Promise.resolve();
    this.latest = {
      moodLabel: frame.mood_label || '', moodIntensity: frame.mood_intensity,
      momentumPct: frame.momentum_pct, speaker: frame.speaker,
      prompt: (frame.prompt || '').slice(0, 140),
    };
    return this.drain();
  }

  clear() {
    this.latest = { moodLabel: '', moodIntensity: 0, momentumPct: 50, speaker: '', prompt: '' };
    return this.drain();
  }

  drain() {
    if (this.running) return this.running;
    this.running = (async () => {
      try {
        while (this.latest !== null) {
          const payload = this.latest;
          this.latest = null;
          await this.gm.plugin.sendMessage(PROSE_HUD_CHANNEL, encodeHudMessage(payload));
        }
      } catch (error) {
        this.latest = null;
        this.onError(error);
      }
    })().finally(() => {
      this.running = null;
      if (this.latest !== null) return this.drain();
    });
    return this.running;
  }

  async close() {
    this.stopped = true;
    await this.clear();
  }
}
