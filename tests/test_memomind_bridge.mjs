import test from 'node:test';
import assert from 'node:assert/strict';
import { MemoMindDisplay } from '../integrations/memomind/display-bridge.mjs';

const MOOD_LABELS = ['calm', 'confident', 'tense', 'defensive', 'frustrated', 'neutral'];

// Mirrors integrations/memomind/glasses-hud/plugin.c's handle_hud_message
// parsing, so these tests verify the real wire contract, not just that
// *some* bytes were sent.
function decodeHudMessage(bytes) {
  const decoder = new TextDecoder();
  const moodIntensity = bytes[0];
  const moodLabelId = bytes[1];
  const momentumPct = bytes[2];
  const speakerLen = bytes[3];
  let offset = 4;
  const speaker = decoder.decode(bytes.slice(offset, offset + speakerLen));
  offset += speakerLen;
  const promptLen = bytes[offset] | (bytes[offset + 1] << 8);
  offset += 2;
  const prompt = decoder.decode(bytes.slice(offset, offset + promptLen));
  return {
    moodLabel: moodIntensity > 0 ? MOOD_LABELS[moodLabelId] : '',
    moodIntensity, momentumPct, speaker, prompt,
  };
}

function fakeDevice(overrides = {}) {
  const calls = [];
  const gm = {plugin: {
    sendMessage: async (channel, bytes) => { calls.push({channel, ...decodeHudMessage(bytes)}); },
    ...overrides,
  }};
  return {gm, calls};
}
const cue = (seq, prompt) => ({seq, prompt, status: 'ready', expires_at: Date.now() / 1000 + 10});

test('a ready frame sends its prompt over the HUD channel', async () => {
  const {gm, calls} = fakeDevice();
  const bridge = new MemoMindDisplay(gm);
  await bridge.push(cue(1, 'First suggestion'));
  assert.equal(calls.length, 1);
  assert.equal(calls[0].channel, 20560);
  assert.equal(calls[0].prompt, 'First suggestion');
  await bridge.close();
});

test('a ready frame with a null prompt sends a clear (empty prompt); old sequence cannot revive it', async () => {
  const {gm, calls} = fakeDevice();
  const bridge = new MemoMindDisplay(gm);
  await bridge.push(cue(1, 'First suggestion'));
  await bridge.push({seq: 2, status: 'ready', prompt: null});
  await bridge.push(cue(1, 'Stale'));
  assert.equal(calls.length, 2);
  assert.equal(calls[1].prompt, '');
  await bridge.close();
});

test('only a ready frame may change the display; thinking/listening/unavailable/expired are no-ops', async () => {
  const {gm, calls} = fakeDevice();
  const bridge = new MemoMindDisplay(gm);
  await bridge.push(cue(1, 'Keep this up'));
  await bridge.push({seq: 2, status: 'thinking', prompt: null});
  await bridge.push({seq: 3, status: 'listening', prompt: null});
  await bridge.push({seq: 4, status: 'unavailable', prompt: null, error: 'provider down'});
  await bridge.push({seq: 5, status: 'expired', prompt: null});
  assert.equal(calls.length, 1);
  assert.equal(calls[0].prompt, 'Keep this up');
  await bridge.close();
});

test('the bubble persists well past the old 15-second cap with no further frames', async () => {
  const {gm, calls} = fakeDevice();
  const bridge = new MemoMindDisplay(gm);
  await bridge.push({...cue(1, 'Still here'), expires_at: Date.now() / 1000 + 0.04});
  await new Promise(resolve => setTimeout(resolve, 80));
  assert.equal(calls.length, 1);
  assert.equal(calls[0].prompt, 'Still here');
  await bridge.close();
});

test('mood, speaker and momentum are encoded alongside the cue', async () => {
  const {gm, calls} = fakeDevice();
  const bridge = new MemoMindDisplay(gm);
  await bridge.push({
    ...cue(1, 'Clarify scope'), speaker: 'Jordan',
    mood_label: 'tense', mood_intensity: 4, momentum_pct: 72,
  });
  assert.deepEqual(calls[0], {
    channel: 20560, moodLabel: 'tense', moodIntensity: 4, momentumPct: 72,
    speaker: 'Jordan', prompt: 'Clarify scope',
  });
  await bridge.close();
});

test('a frame with no mood_label encodes zero mood intensity', async () => {
  const {gm, calls} = fakeDevice();
  const bridge = new MemoMindDisplay(gm);
  await bridge.push(cue(1, 'No mood data'));
  assert.equal(calls[0].moodIntensity, 0);
  await bridge.close();
});

test('bursts of pushes during a slow in-flight send coalesce to the in-flight one plus the latest', async () => {
  // Unlike the old two-step createPage/updateText flow, a single sendMessage
  // call already carries the full payload, so an in-flight send cannot be
  // cancelled once started. Pushes queued while it's in flight still
  // coalesce: only the most recent one is sent once the first completes.
  let release;
  const blocked = new Promise(resolve => { release = resolve; });
  let first = true;
  const {gm, calls} = fakeDevice({sendMessage: async (channel, bytes) => {
    if (first) { first = false; await blocked; }
    calls.push({channel, ...decodeHudMessage(bytes)});
  }});
  const bridge = new MemoMindDisplay(gm);
  const pushes = [
    bridge.push(cue(1, 'Old')),
    bridge.push(cue(2, 'Middle (should be skipped)')),
    bridge.push(cue(3, 'Current')),
  ];
  release();
  await Promise.all(pushes);
  assert.equal(calls.length, 2);
  assert.equal(calls[0].prompt, 'Old');
  assert.equal(calls[1].prompt, 'Current');
  await bridge.close();
});

test('send failures report an error', async () => {
  const errors = [];
  const {gm} = fakeDevice({sendMessage: async () => { throw new Error('disconnected'); }});
  const bridge = new MemoMindDisplay(gm, error => errors.push(error.message));
  await bridge.push(cue(1, 'Do not leave this up'));
  assert.deepEqual(errors, ['disconnected']);
  await bridge.close();
});
