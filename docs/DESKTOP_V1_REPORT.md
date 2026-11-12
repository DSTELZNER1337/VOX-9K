# VOX-9K Runtime Acceptance and Desktop V1 Completion Report

Date: 2026-11-11, America/New_York. **Desktop V1 is accepted on the tested Windows machine using Kokoro CPU and Qwen CUDA.** The existing browser application remains available. Real native playback and lifecycle checks passed; the owner reported that speech sounded correct. Standalone executable/installer distribution is not implemented.

## 1. Starting Git state and preservation

Work remained in `A:\VOX-9K`, on `audit/portfolio-readiness-2026-11-11`, at HEAD `733268d2e31a65de5f58ba96a4f91bd0ef71c824`. At the start, `.gitignore`, `README.md`, `index.html` and `server.py` were already modified. Existing untracked work comprised `docs/`, `local_security.py`, `qwen_fast_server.py`, `qwen_smoke_test.py`, `requirements-fast.txt`, `requirements-test.txt`, `tests/`, `tools/` and `vox_helpers.js`; environments, backups and runtime evidence were ignored.

Before changes, original source/document/test/tool files, hashes, status, HEAD, index patch and working patch were recorded in ignored `audit/runtime-v1-2026-11-11/`. The original 83 tests passed at this baseline. No stash, reset, clean, checkout, commit or publication was performed. Work stayed inside the primary project; the Mac checkout was untouched.

## 2. Real Kokoro acceptance

Kokoro generated valid mono 24 kHz float WAV using Sarah (`af_sarah`) and Michael (`am_michael`) on CPU, followed by a repeated Sarah read. Files were decoded with SoundFile and checked for finite, non-silent samples. The initial diagnostic mistakenly used Python's standard `wave` reader, which rejects IEEE float WAV format 3; that was a probe-format issue, not broken synthesis. The probe was corrected.

The catalog failure had two causes: the installed library's acquisition path refreshes catalog metadata after a one-day TTL, and the earlier offline probe disabled that retrieval even though all assets existed. The exact cached fp32 v1.0 installation includes the ONNX model, voices and vocabulary. VOX-9K now resolves and verifies that installed selection through OnnxVoice's local-only API before passing explicit paths to PyKokoro. No catalog/weight download was needed for accepted CPU reads. Missing installations retain the previous first-run acquisition path; corrupt existing artifacts raise an error rather than silently triggering a download.

| CPU read | Complete-WAV wall time | Audio duration | Interpretation |
| --- | ---: | ---: | --- |
| Sarah, first process read | 12.785 s | 3.35 s | Includes engine creation and warmup. |
| Michael, different voice | 0.938 s | 3.40 s | Warm engine, newly requested voice/output. |
| Sarah, identical repeat | 0.012 s | 3.35 s | Cached waveform retrieval; not a fresh neural throughput benchmark. |

Passage: `VOX nine K is testing local speech.` (35 characters), CPU, existing cache, socket connections blocked in the probe. Native-window playback also passed with both voices.

Kokoro CUDA is not functional in the installed stack. ONNX Runtime GPU 1.31.0 requests CUDA 13/cuDNN 9 and reports missing `cublasLt64_13.dll`, whereas Qwen's working torch stack is CUDA 12.6. A CUDA request initially produced CPU audio through silent ORT fallback. Even OnnxVoice's `providers_active` diagnostic reflected the selected request rather than the actual ORT session. The correction queries the actual session: Auto falls back to CPU and reports it; explicit CUDA fails clearly. The final native run showed `Auto → CPU` with Kokoro CUDA disabled. No inference dependencies were replaced to repair the DLL mismatch.

## 3. Real Qwen acceptance and performance

The optimized 0.6B CustomVoice model loaded from the existing cache on the RTX 3060, captured predictor/talker CUDA graphs and generated valid 24 kHz float PCM with Ryan and Aiden. Five requests covered three normal reads, cancellation of a longer Ryan request and a successful Aiden request immediately afterward. Both generation and native playback succeeded; no indefinite Preparing state remained.

A critical startup regression was identified in the audit's ownership watcher: an open blocking stdin reader reproduced a stall while native scientific extensions imported. Stack traces repeatedly stopped in NumPy/SciPy native module initialization before model inference. Import-only tests without the watcher completed. A blocking Win32 `ReadFile` variant also stalled; non-consuming pipe polling passed the isolated reproducer and full Qwen startup. Windows ownership monitoring now polls the dedicated pipe using PeekNamedPipe; no other code reads that ownership pipe. The existing background loader/model architecture was retained. [Microsoft pipe API reference](https://learn.microsoft.com/en-us/windows/win32/api/namedpipeapi/nf-namedpipeapi-peeknamedpipe).

Hardware: Windows 10 build 19045, Python 3.12.10, NVIDIA RTX 3060 with 12 GiB, torch 2.11.0+cu126, faster-qwen3-tts 0.5.4. Models/tokenizer were cached and `HF_HUB_OFFLINE=1` prevented model retrieval.

- Time from owned process launch to observed ready: **23.030 s**.
- `from_pretrained` phase, including its deferred imports: **17.040 s**.
- Graph warmup/capture: **2.348 s**.

Passage: `VOX nine K is testing local speech on this computer.` (52 characters), English, chunk size 8. Times below are measured by the local HTTP client after model/graph readiness. They are client-received first-chunk times, not server-only generation timestamps or microphone-measured audible onset.

| Request | First received chunk | Complete response | Audio duration | Audio seconds per wall second |
| --- | ---: | ---: | ---: | ---: |
| First Ryan request after warmup | 1.333 s | 3.766 s | 5.36 s | 1.42 |
| Aiden | 0.431 s | 2.211 s | 4.48 s | 2.03 |
| Ryan repeat | 0.428 s | 2.638 s | 5.36 s | 2.03 |
| Aiden after cancellation | 0.437 s | 2.052 s | 4.00 s | 1.95 |

The cancellation request used a 260-character passage, received one 0.64-second audio frame, then cancelled. Cancellation-to-response-close measured about **0.292 s** in that run; this does not establish a universal bound. A subsequent Read succeeded. Model-load/warmup fields remained unchanged across normal requests, and successful sidecar logs contain one model-load phase and one graph-warmup phase per launch. The two weight-loading progress bars refer to distinct model/tokenizer components, not per-read model reloads.

The standalone acceptance owned-process tree exited completely after shutdown. No extended stress test or deliberate VRAM exhaustion was conducted.

## 4. Browser playback findings

The existing loopback page rendered its controls/design in the available in-app Chromium browser. A non-sensitive passage moved from Preparing to Finished through the real WAV playback path. The normal `server.py` entry point remains intact and passed its CLI regression smoke check. The available browser connector did not expose default Brave, so Brave-specific manual acceptance remains a checklist item.

## 5. Desktop implementation

`desktop.py` is an optional pywebview launcher. It displays a startup/error page in a native `VOX-9K` window, checks the actual Flask service identity/readiness and loads the existing `http://127.0.0.1:5000/` page. Window defaults are 1280×960, resizable, minimum 960×720. It forces WebView2/Edge Chromium, preserves ordinary window chrome and adds no custom icon, menus or artwork.

A recognized existing service is reused. Unrelated/unresponsive port occupants are rejected without being stopped. A newly started Flask process gets a unique identity and an ownership pipe; window close/parent death signals Flask, which stops only its owned Qwen sidecar before exiting. Bounded wait/terminate/kill/reap fallback applies only to the child owned by that launch. Existing external Flask and Qwen services are preserved. No authentication bypass, CORS widening, remote inference, framework migration or audio rewrite was introduced.

Actual WebView2 157 checked `fetch`, ReadableStream, AudioContext, AudioBufferSourceNode, Intl.Segmenter and crypto.randomUUID. Native real PCM playback exercised streaming. The frontend remains classic scripts; arbitrary ES module loading was not separately tested. No Mac desktop compatibility claim is made.

## 6. Exact changed and added files

Changed during this phase:

| File | Purpose |
| --- | --- |
| `server.py` | Installed-only Kokoro asset resolution, actual ORT provider/fallback verification, cheap main health identity and desktop-parent lifecycle hook. |
| `qwen_fast_server.py` | Uses corrected ownership monitor; records real model-load and graph-warmup durations. Persistent model/generation behavior retained. |
| `tests/test_backend.py` | Mocks installed-asset resolution so the original tests stay independent of neural files. |
| `tools/hardware_probe.py` | Reads Kokoro float WAV correctly using SoundFile. |
| `README.md` | Current acceptance status and browser/desktop entry points. |
| `docs/RUNNING.md` | Current launch, environment, cache, provider and recovery instructions. |
| `docs/TESTING.md` | Full 112-test suite and separate native/hardware acceptance instructions. |
| `docs/THIRD_PARTY_NOTICES.md` | Optional desktop dependency attribution. |

Added during this phase:

- `desktop.py` and `process_lifecycle.py`.
- `requirements-desktop.txt`.
- `tests/test_desktop.py`, `tests/test_desktop_integration.py`, `tests/test_runtime_config.py`, `tests/test_process_lifecycle.py`.
- `tools/desktop_acceptance.py`.
- `docs/DESKTOP.md` and `docs/DESKTOP_V1_REPORT.md`.

Ignored runtime evidence includes baseline copies, successful/failed diagnostic logs, JSON results and generated WAVs under `audit/runtime-v1-2026-11-11/`. Original `index.html`, CSS, JavaScript assets, images, MIT license, production inference requirement files and smoke script were preserved byte-for-byte relative to this phase's starting state.

## 7. Automated results

| Category | Passed | Failed | Skipped |
| --- | ---: | ---: | ---: |
| Original backend component tests | 48 | 0 | 0 |
| Original frontend tests | 26 | 0 | 0 |
| Original localhost integration tests | 9 | 0 | 0 |
| New runtime configuration/provider tests | 8 | 0 | 0 |
| New native-import/ownership-pipe process test | 1 | 0 | 0 |
| New headless desktop tests | 18 | 0 | 0 |
| New real Flask desktop ownership/reuse tests | 2 | 0 | 0 |
| **Total** | **112** | **0** | **0** |

The increase from 83 is 29 new tests; none of the original tests was removed. Python's combined suite ran 86 tests; Node ran 26. Ordinary tests require no GUI or models. The two native-window acceptance runs and real neural checks are separate from these counts.

Native runs passed actual playback, pause/resume, Stop, voice switching after cancellation, return to Kokoro, 1.2× speed, 40% volume and close. Final actual-provider status was CPU for Kokoro. Both native launches exited with code 0 and **zero remaining owned service processes**. The native tool observed real playback state rather than simulating audio interfaces. The owner separately answered: **“Speech sounded correct.”**

## 8. Manual desktop acceptance checklist

Short native playback and owner listening passed. Before distribution, additionally rehearse:

- Fresh PowerShell browser and desktop launches on the target machine.
- Physical minimize/maximize/close controls, resizing and minimum size at representative display/DPI settings.
- Read, pause, resume and Stop on both engines; repeated voice changes followed by Read and engine switching.
- Speed/volume changes across PCM boundaries, with representative passages and listening for clicks, clipping and pitch inconsistency.
- Long-form playback and a prolonged pause while watching memory; this was not stress-tested.
- Close during active generation, repeat launch/close cycles, and attached-window close while an external backend stays alive.
- Clean-machine installation with WebView2, native phonemizer and DLL requirements, plus default Brave playback.

The automated/native short checks cover many of these paths, but do not replace display-specific, long-form or clean-installation acceptance.

## 9. Known runtime and audio limits

Kokoro CUDA remains unavailable due to the installed CUDA 13 DLL requirement; CPU is the accepted path. Qwen cancellation is cooperative between native steps. Kokoro inference is synchronous and not interrupted by a browser abort. The Qwen audio queue is not bounded for prolonged pauses, and per-buffer WSOLA can have continuity limitations on untested material. Formal pitch/underrun/CPU-memory/GPU-memory benchmarks remain open.

A late library upgrade may change the adapter nesting used to inspect actual ORT sessions; it must be retested before upgrading PyKokoro/OnnxVoice. If that diagnostic surface is unavailable, its result is unknown, not evidence of GPU inference. A source-mode first run without caches can still need large downloads. Closing the original owning desktop backend disconnects attached windows; no ownership transfer mechanism was added.

## 10. Dependencies and licensing

The reviewed official-PyPI install added only pywebview 6.2.1, Bottle 0.13.4, proxy_tools 0.1.0, pythonnet 3.2.1 and clr_loader 0.3.1 to `.venv`. All prior installed versions were compared and remained unchanged. `.venv-fast` was not modified. The existing `.venv` pip conflict remains; the fast environment passes pip check.

pywebview declares BSD-3-Clause. Bottle, proxy_tools and pythonnet declare MIT; clr_loader's installed license file is MIT even though its metadata license field is blank. Microsoft WebView2 has separate runtime distribution terms. Original model/dependency licenses and unresolved visual asset provenance remain as recorded in [third-party notices](THIRD_PARTY_NOTICES.md). The public MIT license was not altered, and no icon or branding asset was generated. No model weights were downloaded; no cloud TTS service or application telemetry was added.

## 11. Future executable packaging

A PyInstaller one-folder pilot is feasible after explicit frozen backend/sidecar entry points, writable per-user cache/log paths, native DLL collection and runtime checks are designed. Current `sys.executable server.py` and `.venv-fast\Scripts\python.exe` assumptions are source-mode paths, not a ready frozen layout. Keep Kokoro and Qwen stacks isolated and avoid collecting irrelevant frameworks. Packaging weights/CUDA can produce a multi-gigabyte distribution; measure rather than quote a size.

Include HTML/JS/images/notices, provision WebView2 according to Microsoft's guidance, add Windows shortcuts and plan signing/clean-machine acceptance. Unsigned builds can receive OS security warnings. A later Mac Kokoro-only build needs Mac-native dependency tests, signing and notarization; no Mac implementation was attempted. Full feasibility notes are in [DESKTOP.md](DESKTOP.md). No executable, spec, installer, release or deployment was built.

## 12. Exact launch commands

Browser:

```powershell
Set-Location A:\VOX-9K
.\.venv\Scripts\python.exe server.py
```

Desktop:

```powershell
Set-Location A:\VOX-9K
.\.venv\Scripts\python.exe desktop.py
```

Use [the current running instructions](RUNNING.md) for optional dependency installation, existing environment flags, missing runtime recovery and the unverified Mac browser recipe. The native launch does not require changing the established browser command.

## 13. Final Git state

Branch and HEAD are unchanged. The index remains unchanged, with nothing staged or committed. Relative to HEAD, `.gitignore`, `README.md`, `index.html` and `server.py` remain modified; the first and third were already modified and were not changed during this phase. Existing unpublished sidecar/application/test/documentation files remain untracked, along with the additions listed above. No files were deleted.

Keep virtual environments, model caches, generated audio, backups, temporary files, per-launch logs and raw audit evidence excluded from Git. No commit, push, publication or installer build was performed. The original engineering audit remains intact as the historical baseline; this report supplies the subsequent runtime/Desktop V1 acceptance.
