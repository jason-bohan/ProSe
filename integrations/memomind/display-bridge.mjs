// PhoneSDK display adapter. The caller owns the SDK instance and its lifecycle.
export class MemoMindDisplay {
  constructor(gm, onError = () => {}) {
    this.gm = gm;
    this.onError = onError;
    this.latest = null;
    this.running = null;
    this.pageOpen = false;
    this.stopped = false;
    this.lastSeq = -1;
    this.expiry = null;
  }

  push(frame) {
    if (this.stopped) return Promise.resolve();
    if (!Number.isInteger(frame.seq) || frame.seq <= this.lastSeq) return Promise.resolve();
    if (frame.prompt != null && typeof frame.prompt !== 'string') {
      return Promise.reject(new TypeError('HUD prompt must be text or null'));
    }
    this.lastSeq = frame.seq;
    clearTimeout(this.expiry);
    const ttl = Number.isFinite(frame.expires_at) ? frame.expires_at * 1000 - Date.now() : 0;
    const prompt = ttl > 0 && frame.status === 'ready' ? (frame.prompt || '').slice(0, 140) : '';
    this.latest = prompt;
    if (prompt) {
      this.expiry = setTimeout(() => { this.latest = ''; this.drain(); }, Math.min(ttl, 15000));
    }
    return this.drain();
  }

  clear() {
    clearTimeout(this.expiry);
    this.latest = '';
    return this.drain();
  }

  drain() {
    if (this.running) return this.running;
    this.running = (async () => {
      try {
        while (this.latest !== null) {
          const text = this.latest;
          this.latest = null;
          if (!text) {
            if (this.pageOpen) await this.gm.display.closePage();
            this.pageOpen = false;
            continue;
          }
          if (!this.pageOpen) {
            await this.gm.display.createPage();
            this.pageOpen = true;
          }
          // Another frame may have arrived while the hardware page was opening.
          if (this.latest !== null) continue;
          await this.gm.display.updateText({
            id: 1, text, x: 20, y: 30, width: 560, height: 240, border: 0, radius: 0,
          });
        }
      } catch (error) {
        this.latest = null;
        this.pageOpen = false;
        this.onError(error);
        // Best effort: never leave a previous suggestion up after an update fails.
        await this.gm.display.closePage().catch(() => {});
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
