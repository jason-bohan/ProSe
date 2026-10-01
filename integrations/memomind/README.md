# MemoMind One display relay

This PhoneSDK Web plugin takes ProSe's compact cue stream and uses the official
`gm.display` API to show one short suggestion. It coalesces display updates,
clears on a null cue, and expires cues locally if the service disconnects. It
contains no AI keys and sends no case documents to the glasses.

The SDK methods and manifest follow the public MemoMind contract checked on
2026-10-01. This is source for a device integration, **not a hardware-verified
or installed application**. The SDK, matching MemoMind App/firmware, Developer
Workspace access and physical glasses are required for device validation.
Building the Web package and trying Browser Studio do not require glasses.

## Local toolkit and simulator

The complete toolkit is checked out at `.tools/memomind-sdk` (ignored by Git),
including `GlassSDK`, `PhoneSDK`, `Studio`, root `build.py`, and prebuilt examples.
The checked revision is `5a1f34ae2430821e30ada9d46bda84acf8fa4fba`.

- Desktop: open `.tools/memomind-sdk/Studio/windows/gm-plugin-studio-desktop.exe`.
  This release prompts for a **MemoMind account email and password**. After
  signing in, import `.tools/memomind-sdk` as the workspace. Start with the
  supplied GM Breakout example before selecting ProSe and the bridge.
- Browser: from `.tools/memomind-sdk/PhoneSDK`, run
  `node tools/run-browser-studio.mjs --plugin examples/prose-live-coach --port 4173`.
  Open `http://127.0.0.1:4173`; no account is required. Select the required
  `display` and `network` permissions and start the plugin.
  Click **Show sample cue** in the ProSe panel to send an explicitly labeled
  example to the green display. It clears after 15 seconds and makes no AI call.
  If the panel is empty, click Studio's **Reload** and approve the permissions.
- Debate without glasses: open ProSe's `/practice` for an AI opponent and coach.

The upstream Browser Studio permission dialog has hard-coded Chinese labels.
This local checkout has English translations. The reproducible changes are in
`browser-studio-english.patch`; apply with `git apply <absolute-patch-path>` from
the toolkit root in another checkout of the same revision. No permission checks
are bypassed or automatically accepted. Refresh the browser after applying.

Desktop Studio runtime and physical-device checks remain pending sign-in and
hardware. A package build and Browser Studio checks do not establish those results.

The native GM Breakout example also rebuilt successfully on this computer.
The Microsoft Store Python cache path was too long for the compiler headers;
the checked xPack RISC-V compiler is available under `.tools/riscv` instead.
From the ProSe repository root, use this for further native builds:

```powershell
$env:GM_RISCV_TOOLCHAIN = (Resolve-Path .tools/riscv/xpack-riscv-none-elf-gcc-15.2.0-1/bin).Path
python .tools/memomind-sdk/GlassSDK/build.py build --example game/breakout
```

## Build and try

1. Obtain the complete [MemoMind toolkit](https://github.com/memomind-open/plugin-open-platform)
   and run a supplied example first (GM Breakout in Desktop Studio, or
   `examples/app-counter` in Browser Studio).
2. Copy this directory into `PhoneSDK/examples/prose-live-coach` in that toolkit.
3. From the toolkit root, run `node PhoneSDK/tools/sync-example-sdk.mjs`. Copy
   `PhoneSDK/examples/permission-debug/vendor/gm-plugin-web-sdk.esm.js` into this
   plugin's `vendor/` directory. Use the matching SDK; do not recreate its handshake.
4. Run `py build.py web`. Select **ProSe Live Coach** and **GM Web Bridge** in
   Studio. Use the toolkit's glass build step if its bridge GMP is not built.
5. Open ProSe's `/copilot`, choose the litigation/debate brief, and start a session.
   Copy the **MemoMind stream link** into this plugin and connect. Studio can use
   loopback. A real phone requires an HTTPS service reachable from the phone;
   `127.0.0.1` on the phone does not refer to your computer. Production hosting,
   access control, and deployment are separate from this local development app.
6. Send a transcript turn in ProSe. Verify the suggestion, a subsequent clearing
   frame, disconnect, expiration, and stop. Scan the generated package through
   Memo Lab only after the Studio path works. Test the same cases on the glasses.

The stream URL contains a random session identifier and grants read access to
that session. It expires when the session stops or times out. Do not share it.
The relay leaves session creation and audio input in the ProSe companion; it
does not request audio permission or pretend to transcribe the glasses mic.

## Audio path still to integrate on the actual device

MemoMind's native microphone API uses `gm.audio.openCapture()`. Its chunks contain
framed Opus, not the PCM16 expected by ProSe's Vosk transcriber. Connecting that
path requires a streaming Opus decoder or an ASR service that accepts that
encoding, then posting finalized transcript turns to ProSe. Carry through dropped
frame/discontinuity information, bound the audio queue, and stop capture when the
session ends. Verify background/phone-lock behavior on the target OS and firmware.
The browser companion and the Vosk CLI already provide alternative transcript
inputs for developing the reasoning and display pipeline.

## References

- [Phone Web plugin and display setup](https://open-platform.memo-mind.com/docs/get-started/quickstart/first-web-app/?lang=en)
- [SDK API and lifecycle](https://open-platform.memo-mind.com/docs/build/web-sdk/?lang=en)
- [Native audio contract](https://open-platform.memo-mind.com/docs/build/web-audio/?lang=en)
- [Installation and hardware requirements](https://open-platform.memo-mind.com/docs/get-started/quickstart/hardware/?lang=en)
