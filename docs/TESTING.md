# Testing VOX-9K

The normal suite is graphical-session-free and does not load neural models or download weights. Run from the repository root:

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -p 'test_*.py' -v
node --test tests\frontend.test.cjs
```

Current local paste/security-follow-up results: **126 Python tests plus 62 frontend tests = 188 passed, 0 failed, 0 skipped**. The preceding WAV/background baseline had 172 passing tests. This pass adds 10 native-menu policy tests, 4 background error-path checks and 2 frontend failure/retry checks. All existing tests remain. Python 3.12.10 and Node 24.19.0 were used.

## Suite boundaries

| Suite | Count | Evidence |
| --- | ---: | --- |
| `test_features.py` | 30 | Synthetic WAV headers/order/rate/duration, job failure/cancellation/leases/limits/cleanup, cache reuse and Qwen ownership; raster content/size/dimensions/persistence/restore/security. |
| `test_desktop_editing.py` | 10 | Native editing-menu policy, allowed page/targets, command filtering, disabled clipboard actions, debug/accelerator settings and UI-thread installation/failure/idempotence. |
| `test_backend.py` | 48 | Existing framework-client validation, cancellation, frames, locks, engine caching, error and cleanup checks with mocked models. Installed-asset discovery is mocked to keep tests model-free. |
| `frontend.test.cjs` | 62 | Actual JavaScript/PCM parser in a Node VM, including UI/read-view lifecycle, synthetic DSP seams/duration/range/pitch and scheduled playback/control regressions. |
| `test_integration.py` | 9 | Existing real loopback HTTP, synthetic streams/cancellation/disconnect, ownership EOF and browser CLI smoke checks. |
| `test_runtime_config.py` | 8 | Installed-only model resolution, bootstrap/corruption behavior, actual ORT provider checks, Auto fallback and explicit CUDA rejection. |
| `test_process_lifecycle.py` | 1 | A real child imports native NumPy while an ownership pipe remains open, then exits after parent EOF. This catches the reproduced Windows blocking-reader startup regression without neural inference. |
| `test_desktop.py` | 18 | Headless readiness, identity, port conflicts, external reuse, close/reap escalation, mock-window errors and optional-dependency handling. |
| `test_desktop_integration.py` | 2 | Real owned Flask process termination and external-service preservation, with neural startup disabled. |

The port-5000 integration checks skip if an existing service occupies the port; no service is terminated to force a pass. There were no occupied-port skips in the final run. Framework test-client checks are component tests, not real-network or hardware proof. The installed Starlette emits an `httpx` deprecation warning; it does not fail the tests and no unrelated framework upgrade was made.

To create a separate model-free test environment, install `requirements-test.txt` into a new `.venv-test` and substitute that interpreter. This recipe has not been freshly rehearsed. PyKokoro, ONNX Runtime, PyTorch, model weights and pywebview are not required by the normal suite; it does require the listed lightweight framework/NumPy dependencies. `unittest` and Node's runner are built in.

## Explicit hardware and native-window acceptance

These checks run outside the 188-test count and require the existing installed environments/models.

```powershell
# Short cached Kokoro probe; network is blocked inside this process:
.\.venv\Scripts\python.exe -B tools\hardware_probe.py --mode cpu

# Interactive native-window acceptance, including actual audible playback:
.\.venv\Scripts\python.exe -B tools\desktop_acceptance.py
```

The hardware probe uses SoundFile because Kokoro returns IEEE float WAV; Python's standard `wave` reader rejects that valid format. The probe writes its actual outcome to ignored `audit/hardware-kokoro-<mode>.json`. CUDA mode must validate the actual ORT provider; a CPU fallback is not a GPU success. Its `--baseline` option is a historical probe requiring the prior ignored audit snapshot and reproduces the original catalog issue; it is not a normal regression test.

The native acceptance tool uses the real pywebview window and current source backend. It exercises actual Kokoro/Qwen playback state, pause/resume, Stop, voices, engine switching, speed/volume and owned service shutdown. It uses `HF_HUB_OFFLINE=1`, requires an interactive Windows session, plays audio and keeps the window briefly available for inspection. Its results are in `audit/runtime-v1-2026-11-11/desktop-native-acceptance.json`. Do not run it in ordinary headless CI. It needs the already installed runtime environment, including SoundFile/psutil through the existing development setup.

Real acceptance passed: three Kokoro CPU reads with Sarah/Michael, Qwen CUDA startup/capture and five requests including cancellation/recovery, two full native-window runs with no remaining owned service processes, and a browser Read reaching Finished. The owner reported that speech sounded correct. See [the completion report](DESKTOP_V1_REPORT.md) for exact measurements and scope. These are short acceptance runs, not extended stress or formal perceptual tests.

Never discover or execute `qwen_smoke_test.py` as a unit test: it loads a large model and can download assets. `tools/capture_environment.py <name>` records installed package/license metadata, freeze and pip diagnostics under ignored `audit/` without importing models.

## Manual acceptance before distribution

- Launch browser mode and desktop mode from a fresh PowerShell session.
- Verify the native title, resizing, minimum dimensions, minimize/maximize, and the physical close button on the target display/DPI settings.
- Read with Kokoro CPU; pause, resume, Stop, change voice and Read again.
- Read with Qwen Ryan/Aiden; Stop during generation and immediately start a different voice; switch back to Kokoro.
- Exercise speed and volume while listening, including across streamed PCM boundaries. General short-run listening passed; controlled pitch/latency measurements remain separate.
- Try a representative long document and a prolonged pause; watch memory and listen for queue gaps, clipping or transition artifacts. No extended stress run was performed here.
- Close the owning window during active generation and confirm owned Python/GPU resources exit. Close an attached window and confirm its external backend remains alive.
- Repeat launch/close cycles and check that no owned Python process accumulates.
- Check default Brave or another target browser explicitly; the available browser connector exercised in-app Chromium.
- Rehearse installation on a clean Windows machine with documented WebView2/native DLL requirements before distributing a package.

For performance work, record exact passage/length, voice, engine, compute mode, versions, hardware, warm/cold/cache conditions and method. Distinguish server generation, client-received first chunk, complete WAV/stream response and actual audible onset. Do not report cached waveform retrieval as fresh neural-generation throughput.

## UI polish follow-up

The current display highlights entire current/completed speech chunks rather than individual words. It preserves original text and restores editing on Stop/completion/error. See [the UI polish report](UI_POLISH_REPORT.md) for method, limitations and graphical verification.

## Qwen accelerated-audio follow-up

The 2026-11-12 investigation captured one cached Qwen passage per voice and compared exactly the same PCM at 1.0/1.2/1.5/1.8x. Tests now cover the reproduced WSOLA tail-truncation discontinuity and callback-scheduling gaps, using sine, speech-like harmonics, silence, amplitude steps, short/uneven buffers and playback-state transitions. See [QWEN_AUDIO_REPORT.md](QWEN_AUDIO_REPORT.md) for measurements and local evidence.

Native scheduling probes and live desktop/browser checks run separately from the 135 headless tests. The owner accepted the corrected Aiden 1.5x comparison as free of popping and natural. Other voices/speeds have objective/playback checks without separate owner listening acceptance. Buffers below 2048 samples retain the existing passthrough policy. Genuine generation starvation can still cause gaps.

## WAV/background follow-up

The new deterministic checks use synthetic PCM, mocked inference and temporary image/job directories. Actual cached-model desktop exports, a fresh browser Qwen export, real backend restart persistence and native attachment saving were checked separately. The native attachment test stubbed destination selection while using the real WebView2 downloader; it is not manual Save dialog acceptance. The browser connector could not complete attachment saving. The owner accepted the two-chunk Ryan export as complete and natural. See [FEATURE_REPORT.md](FEATURE_REPORT.md) and [the feature guide](EXPORT_AND_BACKGROUNDS.md).

## Native paste / Windows Security follow-up

The owner physically verified the corrected native menu, right-click Paste, selected-text replacement and Ctrl+V. A passive native observer recorded four actual menu requests containing only the intended editing commands. A separate browser run verified insertion/replacement and a 16,500-character clipboard paste, plus recorded-audio playback/export/background regressions. These checks are separate from headless counts. No new neural inference was needed. The supplied security screenshot and relevant event 1123 confirm a Controlled Folder Access block against WebView2/Favorites; the trigger is not currently reproducible and no security setting or background runtime code was changed. See [PASTE_SECURITY_REPORT.md](PASTE_SECURITY_REPORT.md).
