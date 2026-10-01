import test from 'node:test';
import assert from 'node:assert/strict';
import { MemoMindDisplay } from '../integrations/memomind/display-bridge.mjs';

function fakeDevice(overrides = {}) {
  const calls = [];
  const gm = {display: {
    createPage: async () => calls.push('open'),
    updateText: async options => calls.push(options.text),
    closePage: async () => calls.push('close'),
    ...overrides,
  }};
  return {gm, calls};
}
const cue = (seq, prompt) => ({seq, prompt, status:'ready', expires_at:Date.now()/1000 + 10});

test('null and expired cues clear the physical display; old sequence cannot revive them', async () => {
  const {gm, calls} = fakeDevice();
  const bridge = new MemoMindDisplay(gm);
  await bridge.push(cue(1, 'First suggestion'));
  await bridge.push({seq:2, status:'thinking', prompt:null});
  await bridge.push(cue(1, 'Stale'));
  await bridge.push({...cue(3, 'Expired'), expires_at:1});
  assert.deepEqual(calls, ['open', 'First suggestion', 'close']);
  await bridge.close();
});

test('a slow page open displays only the newest cue', async () => {
  let release;
  const blocked = new Promise(resolve => { release = resolve; });
  const {gm, calls} = fakeDevice({createPage: () => blocked});
  const bridge = new MemoMindDisplay(gm);
  const first = bridge.push(cue(1, 'Old'));
  const second = bridge.push(cue(2, 'Current'));
  release();
  await Promise.all([first, second]);
  assert.deepEqual(calls, ['Current']);
  await bridge.close();
});

test('local timeout clears a cue even with no further network frames', async () => {
  const {gm, calls} = fakeDevice();
  const bridge = new MemoMindDisplay(gm);
  await bridge.push({...cue(1, 'Brief'), expires_at:Date.now()/1000 + 0.04});
  await new Promise(resolve => setTimeout(resolve, 80));
  assert.deepEqual(calls, ['open', 'Brief', 'close']);
  await bridge.close();
});

test('display failures report an error and attempt a clear', async () => {
  const errors = [];
  const {gm, calls} = fakeDevice({updateText: async () => { throw new Error('disconnected'); }});
  const bridge = new MemoMindDisplay(gm, error => errors.push(error.message));
  await bridge.push(cue(1, 'Do not leave this up'));
  assert.deepEqual(errors, ['disconnected']);
  assert.deepEqual(calls, ['open', 'close']);
  await bridge.close();
});
