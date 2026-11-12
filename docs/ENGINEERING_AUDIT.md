# VOX-9K engineering audit and portfolio readiness

Date: 2026-11-11, America/New_York. Scope: the actual Windows checkout at `A:\VOX-9K`, including unpublished code. No commits, pushes, releases, deployment, model downloads, dependency upgrades or Mac checkout changes were made.

## 1. Executive assessment

**Recommendation: Not yet ready for a verified portfolio demonstration.** The application's small Flask plus browser architecture is appropriate for a local speech tool. Its visual design and existing engine choices were retained. The audit added meaningful automated tests and corrected demonstrated validation, cancellation, request ownership, stream parsing and cleanup defects. All 83 final model-free automated and localhost integration tests pass.

The remaining acceptance gap is consequential: no real speech generation succeeded during this audit. A short network-blocked Kokoro probe failed while the installed library attempted catalog retrieval, against both the original and corrected source. Qwen model inference, real audio playback and audible pitch quality were not validated. Asset provenance and a clean installation rehearsal also remain open. The project can be positioned truthfully as an existing AI-assisted local TTS application undergoing stabilization, but it should not yet be presented as independently verified production software or advertised with latency claims.

## 2. Baseline

| Item | Recorded starting state |
| --- | --- |
| Primary repository | `A:\VOX-9K` |
| Supplied task workspace | `E:\Documents\ChatGPT\VOX-9K`, initially empty and not a Git checkout; used only for local audit preparation |
| Starting branch | `main`, tracking `origin/main` |
| HEAD | `733268d2e31a65de5f58ba96a4f91bd0ef71c824` |
| Remote | `https://github.com/DSTELZNER1337/VOX-9K.git` |
| Staged changes | None |
| Modified tracked files | `index.html`, `server.py` |
| Untracked starting paths | `.venv-fast/`, `backups/`, `qwen_fast_server.py`, `qwen_smoke_test.py`, `requirements-fast.txt` |
| Tracked files | `.gitignore`, `LICENSE`, `README.md`, `background.png`, `index.html`, `requirements-gpu.txt`, `requirements.txt`, `screenshot.png`, `server.py` |

The GitHub connector verified that public `main` points to the same HEAD. Shell `git ls-remote` could not connect through the configured proxy; this was resolved with read-only connector access, not by changing Git/network configuration. [Public baseline commit](https://github.com/DSTELZNER1337/VOX-9K/commit/733268d2e31a65de5f58ba96a4f91bd0ef71c824).

The unpublished delta is substantial: the starting tracked diff had 2,304 insertions and 363 deletions across the two modified files. Locally added capabilities include Qwen selection and voices, a persistent optimized CUDA sidecar, framed float32 PCM streaming, server cancellation/session handling, Web Audio playback and WSOLA-style speed adjustment. The public baseline remains Kokoro-focused; it does not include this local Qwen implementation.

Before source changes, top-level original files were copied byte-for-byte to ignored `audit/baseline-2026-11-11/`, with SHA-256 hashes, starting tracked/untracked inventory, staged patch, working patch, HEAD and remotes. The `.venv` and `.venv-fast` directories were inventoried rather than copied or moved. Existing backup files and generated WAVs were preserved. The audit branch `audit/portfolio-readiness-2026-11-11` was created without stashing, cleaning, resetting, staging or committing.

There was no established automated suite. The first added regression suite ran against the starting source: 34 backend tests yielded 21 passes, 12 failures and 1 error; 17 frontend tests yielded 9 passes and 8 failures. The suite included acceptance cases for the forthcoming stricter parser; its baseline counts are not a coverage or audio-quality score. Initial test-harness import isolation was corrected before those baseline results were recorded.

## 3. Architecture findings

The browser owns text cleanup, English sentence segmentation, chunk preparation, session state and playback. Kokoro requests go to Flask `POST /tts`, returning WAV bytes. The Flask process caches synthesizers by requested compute mode, creates temporary output in a context manager and serves explicit static files. It remains single-threaded, avoiding parallel Kokoro inference inside the service but allowing a long synthesis to block its other HTTP work.

Qwen browser requests go directly to the FastAPI/Uvicorn sidecar on port 5001. A background loader constructs the optimized model once, warms/captures graphs once, and retains the model. Startup, graph warmup and ready states are now distinct. A model lock serializes generation; a separate state lock allows cancellation to be registered while inference holds the model lock. Audio uses a 16-byte little-endian header: payload length, sample rate, frame index and flags (0 data, 1 end, 2 error). Data payloads are mono float32 at 24 kHz.

The corrected response owns the synchronous model generator through an async wrapper. Disconnect cleanup signals cancellation, closes the generator in a shielded worker-thread operation and preserves lock ordering. Generator cleanup occurs before model-lock release. A cancelled waiter checks its event while acquiring the lock; a cancelled active generator avoids beginning another step after cancellation is observed. This is cooperative cancellation at native-step boundaries, not instantaneous GPU interruption.

The parent owns only sidecars it starts. An inherited stdin pipe provides a small ownership signal: closing the pipe or parent death produces EOF in the owned child watcher. A compatible externally started sidecar is reused without being terminated. Health identity is verified by service and model, rather than treating any JSON at port 5001 as Qwen. Ports remain fixed; no process-manager framework was introduced.

Frontend engine/voice/compute values are intentionally locked per Read session. Changing a selector affects the next Read, preserving prefetch consistency. Kokoro uses HTML Audio with pitch preservation requested from the browser. Qwen plays queued Web Audio buffers at rate 1 after per-buffer time stretching. No framework, engine, model architecture, visual layout, image or stylesheet was replaced.

Technical debt remains concentrated in the large inline script and handwritten playback lifecycle. Pure helpers can be tested without extracting the entire UI; only the framed parser was extracted. `Intl.Segmenter` and `crypto.randomUUID` require a modern browser. Qwen's UI forces English even for voices categorized by other native languages; the endpoint accepts supported languages but multilingual UI behavior is not established. Kokoro requests explicitly use `en-us` even for British voices; the pronunciation effect needs listening before changing it.

## 4. Security and reliability findings

No Critical issue was identified within this local-app review. The findings below distinguish corrections from remaining limitations.

| Severity | Finding and practical impact | Resolution / status |
| --- | --- | --- |
| High | Cancellation sent without a request ID could cancel a newer Qwen session when delivery was delayed. Browser IDs also repeated across tabs/page loads. | Fixed: unique browser client prefix and scoped cancel IDs; unscoped HTTP cancellation rejected. |
| High | Cancellation and stream arrival could race; an older delayed Read could supersede a newer one. | Fixed: bounded cancellation tombstones and per-client session/chunk ordering under the generation-state lock. Tombstones last five minutes; bookkeeping is bounded to 256 entries. This is local session coordination, not authentication. |
| High | Stream disconnect and generator cleanup were fragile; generator cleanup could run after the model lock was released. | Fixed: explicit response ownership, shielded close, cleanup while locked, cancellation-aware waiting, no unnecessary next model step. Real HTTP synthetic disconnect and cancellation tests pass. |
| Medium | CORS alone did not reject every browser-triggered side effect; main and sidecar lacked explicit Host/Origin validation. | Fixed: allowlisted loopback hosts/UI origins and cross-site fetch-metadata rejection on both services. Sidecar CORS remains restricted to the two UI origins. Local CLI clients may omit Origin. |
| Medium | Missing HTTP body bounds, non-object JSON and coerced non-string inputs could cause errors or unnecessary work; unsupported Kokoro voices reached the engine. | Fixed: 64 KiB body bounds, object/string checks, voice allowlist and existing 3,000-character text limit. Sidecar bounds apply before JSON parsing, including streamed request bodies. |
| Medium | Long unpunctuated sentences bypassed frontend target chunk sizes and exceeded the backend limit. | Fixed: split sentences exceeding 3,000 UTF-16 units, preserving normal sentence grouping and avoiding surrogate-pair splitting. |
| Medium | Older failed requests could remove new controllers/cache entries or stop/update a new playback session. Late pause and health responses could overwrite new UI state. | Fixed: identity-checked cleanup and session guards; every new Read resets state and scopes cancellation, including empty replacement text. |
| Medium | PCM parser accepted missing end markers, unchecked lengths/rates/indexes and invalid samples, allowing silent truncation or excessive pending frames. | Fixed: parser validates 24 kHz, sequence, flags, finite PCM, payload alignment and a 4 MiB frame ceiling; incomplete streams are errors and reader locks are released. |
| Medium | Model errors thrown during readiness polling were caught as transport errors, hiding a known failure until the two-minute deadline. Polling requests had no individual timeout. | Fixed: terminal errors surface immediately; each poll times out after two seconds; Stop aborts pending polls. |
| Medium | Raw synthesis/startup exceptions were exposed to the browser. | Fixed for synthesis responses, error frames and health startup errors: generic browser messages with console details retained locally. |
| Medium | Kokoro provider choice depended on environment variables bypassed by the installed PyKokoro adapter's default provider path. Provider labels could disagree with requested configuration. | Fixed: explicit `SynthesisConfig.provider`; Auto resolves CUDA then CPU. Actual ONNX CUDA execution remains unverified. |
| Medium | Only `atexit`/direct child termination protected sidecar shutdown, leaving abnormal parent death and Windows launcher behavior insufficiently covered. | Improved: EOF ownership watcher plus wait/terminate/kill/reap fallback. Non-neural child EOF verified; GPU child/process-tree behavior remains a hardware acceptance item. |
| Medium | Cached Kokoro startup still attempted network catalog access and failed in the offline probe. | Open and reproduced in both starting and corrected code; do not claim guaranteed offline restart after the first download. Determine the intended installed-library cache/catalog behavior. |
| Medium | `.venv` has a declared Qwen/ONNX distribution conflict; requirements are not a fresh validated lock. | Open: preserve working versions; validate a clean Kokoro-only setup and the existing isolated fast stack before publication. |
| Medium | Long Qwen playback or a prolonged pause can accumulate decoded PCM without a bounded playback queue; buffer sources start from `onended`, which can leave scheduling gaps. | Open: measure real memory growth and underruns. A bounded queue or scheduled overlap would change playback flow and needs evidence before implementation. |
| Medium | WSOLA operates independently per PCM buffer, passes short buffers through and carries no alignment history across network buffers. | Open audio-quality risk: synthetic numeric bounds pass, but clicks, speed accuracy, phase discontinuities and audible pitch quality need listening and measurement. No replacement algorithm was introduced. |
| Low | `.venv-fast` and manual backups were not ignored, risking accidental publication of thousands of environment files. | Fixed: ignore fast environment, backups, outputs and raw audit evidence. Existing files remain present. |
| Informational | A same-user local program can call loopback endpoints without Origin. Fixed ports may conflict; adopted sidecars have independent ownership. | Intentional local trust boundary; no accounts or authentication system added. This is not a hosted or multi-user service. |

Model download/bootstrap errors, CUDA OOM and model correctness were tested only through simulated failures, not by provoking hardware exhaustion. The existing recoverable policy is a clear browser error plus local diagnostics; a failed Qwen loader requires correcting the cause and restarting the owning application. No automatic model reload or graph recapture is added between reads.

## 5. Corrections implemented

| File | Reason and resulting behavior |
| --- | --- |
| `.gitignore` | Excludes local fast/test environments, backups, outputs and raw audit evidence; no files deleted. |
| `server.py` | Adds body/local-request guards, strict input/voice validation, explicit Kokoro provider configuration and failed-warmup close; redacts client errors; serves parser asset; validates sidecar identity; owns/reaps child through a pipe; adds opt-out diagnostic startup flags. |
| `qwen_fast_server.py` | Preserves optimized persistent model; separates warming state; scopes/orders cancellation, remembers early cancellation, closes generators under lock, manages disconnect cleanup, bounds/guards HTTP requests, validates generated sample format, redacts errors, disables default HF Hub telemetry and watches owned-parent EOF. |
| `index.html` | Preserves CSS/layout and voices; limits exceptionally long sentences, validates streamed frames, releases readers, scopes cancellation, protects new sessions from stale controllers/errors/health/pause completions and reports startup failure promptly. |
| `local_security.py` | Small shared Host/Origin/fetch-metadata rules and bounded ASGI request-body guard. |
| `vox_helpers.js` | Extracted model-independent framed PCM parser, used by the real UI and synthetic tests. |
| `tests/test_backend.py` | 48 model-free route, lifecycle, resource, validation and reuse checks. |
| `tests/frontend.test.cjs` | 26 tests of actual frontend functions and parser in a fake browser environment. |
| `tests/test_integration.py` | 9 real local HTTP/process/CLI checks with synthetic inference. |
| `requirements-test.txt` | Optional isolated lightweight test dependencies matching the observed environment; production requirements unchanged. |
| `tools/capture_environment.py` | Reproducible installed-version/license metadata inventory and pip diagnostics. |
| `tools/hardware_probe.py` | Small explicit cached Kokoro probe with network disabled and structured real outcomes. |
| `README.md` | Identifies unpublished local Qwen work, narrows provider/privacy/performance claims and links current run/test/license notes. |
| `docs/RUNNING.md` | Separates tested service startup from unverified neural/platform installation recipes. |
| `docs/TESTING.md` | Documents suites, integrity boundaries, opt-in hardware checks and manual acceptance. |
| `docs/THIRD_PARTY_NOTICES.md` | Attributes engines/libraries/models and records outstanding visual/native-binary provenance work. |
| `docs/ENGINEERING_AUDIT.md` | This completion report, findings, evidence, remaining work and portfolio plan. |

Raw baseline files, logs, installed manifests, integrity checks and a baseline-to-final patch remain under ignored `audit/` for local review. Original `LICENSE`, assets, production requirement files, smoke script, manual backups and generated audio were preserved. No inference library or model architecture was changed.

## 6. Testing results

| Category | Passed | Failed | Skipped | Interpretation |
| --- | ---: | ---: | ---: | --- |
| Backend automated unit/component tests | 48 | 0 | 0 | Mocked models, actual framework test clients; no network inference. |
| Frontend automated tests | 26 | 0 | 0 | Actual source under Node VM, synthetic data and fake DOM/audio interfaces. |
| Localhost integration tests | 9 | 0 | 0 | Actual HTTP services, synthetic PCM, real child ownership EOF and service CLI startup. |
| Total above | 83 | 0 | 0 | No claim about real speech, perceptual quality or neural performance. |

Separate hardware probes: one small CUDA arithmetic check passed; one corrected-source Kokoro cached CPU probe failed before producing audio; the preserved-source comparison failed for the same catalog/network reason. These probes are not included in the 83 tests. Kokoro CUDA inference, Qwen load/warmup/inference, GPU OOM, audio-device playback and macOS are **not run**, rather than silently counted as passed or skipped suite tests.

Final checks include Python syntax parsing, Git whitespace validation, unchanged CSS/page structure and original asset/license hash verification. Exact suite logs are local at `audit/backend-tests.txt`, `audit/frontend-tests.txt` and `audit/integration-tests.txt`. Test instructions are in [TESTING.md](TESTING.md).

## 7. Performance results

Hardware evidence: Windows 10 build 19045, Python 3.12.10, NVIDIA GeForce RTX 3060 with 12 GiB, torch 2.11.0+cu126 and CUDA runtime 12.6. The provider list includes TensorRT, CUDA and CPU; this is detection, not successful ONNX inference.

The CUDA arithmetic probe used a 32×32 tensor of ones and matrix multiplication on CUDA, synchronized and checked every result equals 32. It passed; the measured approximately 0.403 seconds includes CUDA context initialization. This is a runtime sanity check, not a TTS benchmark, and cannot support a Qwen speed claim.

Kokoro methodology: new process, existing cache, network sockets blocked, CPU, `af_sarah`, passage `VOX nine K is a local speech application.` (41 characters). Intended runs were one cache-cold process generation followed by a second warm generation, recording complete-WAV wall time, audio duration and throughput. Both starting-source and corrected-source attempts failed in catalog retrieval before inference; there are no WAV, throughput or audio latency results. Corrected-source failure took about 11.09 seconds overall and starting-source comparison about 8.99 seconds; their difference is not an inference performance regression measurement.

CLI startup and synthetic test durations are not speech benchmarks. The UI's displayed Qwen TTFA is measured near Web Audio source start in the browser, and includes startup/network/queue work; it is neither server first-generated-chunk time nor a microphone measurement of audible onset. No universal sub-second or quality claim is supported. Cold Qwen initialization, graph capture, warm first chunk, sustained throughput, cancellation latency during native GPU work, CPU/GPU memory during synthesis and browser underruns remain unmeasured. [TESTING.md](TESTING.md) defines a reproducible follow-up method.

## 8. Dependencies and licensing

Installed versions were inspected rather than inferred from historical requirements. `.venv-fast` passes `pip check`; `.venv` reports `qwen-tts 0.1.1 requires onnxruntime, which is not installed` while ONNX Runtime GPU 1.31.0 supplies the import namespace. The original Qwen stack uses Transformers 4.57.3; optimized Qwen uses the separate `qwen-tts-hf` compatibility package and Transformers 5.15.1. No package versions were changed. The existence of CUDA wheels and passing CUDA arithmetic do not establish ONNX provider DLL loading or Qwen graph capture.

The original MIT license remains intact. The [Kokoro model card](https://huggingface.co/hexgrad/Kokoro-82M) and [Qwen checkpoint](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice) state Apache-2.0; [faster-qwen3-tts](https://github.com/andimarafioti/faster-qwen3-tts/blob/main/LICENSE) is MIT. PyKokoro/OnnxVoice and the two Qwen Python distributions declare Apache licensing in installed metadata. These licenses are distinct from VOX-9K's MIT code license.

Both full installed metadata inventories are retained locally, including transitive packages and missing/ambiguous license fields. `docs/THIRD_PARTY_NOTICES.md` identifies major libraries, system fonts and outstanding model/voice/visual provenance. No font download, CDN dependency or remote script is present in the page. The provenance of `background.png` and its appearance in `screenshot.png` was not established. Native eSpeak NG, if packaged, has separate terms from its Python wrapper. Do not call a future bundled installer license-cleared on the strength of Python package metadata alone.

Model/cache/catalog retrieval can use the network during setup and later catalog refreshes. Inference calls remain in the local engine paths; there is no cloud TTS API or new analytics service. HF Hub telemetry is disabled by default in the sidecar. No claim of completely network-free startup has been validated.

## 9. Remaining limitations

Before a verified portfolio demonstration, complete a real short speech acceptance run, resolve cached Kokoro catalog access, verify the exact background/screenshot rights, and rehearse installation in a separate environment. If presenting Qwen, additionally verify model/graph warmup once, multiple warm reads, Stop/Read voice and engine changes, audible buffer transitions and parent shutdown/GPU memory release. None of these requires a rewrite; a Kokoro-only demonstration is acceptable if honestly scoped and verified.

Before publishing source, review the baseline-to-final patch and deliberately select new application/test/documentation files. The public repo will otherwise continue to lack the local Qwen feature and tests. Any later publish/commit is an owner action, not part of this audit.

Optional future work requiring measurements includes bounded Qwen audio buffering, scheduling to reduce gaps, per-buffer WSOLA continuity and smaller frontend modules. Broad framework migration, inference replacement, new models, Mac Qwen, cloud services and database infrastructure were not justified or implemented. CoreML and macOS operation remain unverified; the current Auto policy is CUDA then CPU. The single-threaded Kokoro server does not cancel a native call when browser playback stops.

## 10. Portfolio readiness recommendation

**Not yet ready.** Engineering reliability and reviewability have improved, and the deterministic regression suite is useful evidence of stabilization work. The audit cannot certify that the actual TTS experience currently works on the target machine. Treat real playback acceptance, setup rehearsal and asset rights as the final demonstration gates. Once those are resolved, the application is a reasonable practical-software portfolio candidate without expanding its architecture.

## 11. Demonstration and Upwork recommendations

Suggested project title: **VOX-9K Local Neural Speech Reader**.

Suggested description, after real playback acceptance: “Built an AI-assisted local text-to-speech reader with a Python service and browser controls, integrating third-party Kokoro and optional Qwen engines. The application prepares long text, manages prefetched or streamed audio, and provides voice, pause, speed and volume controls. Stabilization work added request validation, cancellation ownership, resource cleanup and 83 passing model-free automated and localhost integration checks.”

Technologies to list: Python, Flask, HTML, CSS, JavaScript, ONNX Runtime, PyKokoro; add FastAPI, PyTorch, CUDA, Web Audio and faster-qwen3-tts only when showcasing the local Qwen implementation with its experimental status clear. Suggested skill tags: Python, Flask, JavaScript, HTML5, CSS3, API Integration, Automated Testing, Debugging, Audio Processing and Machine Learning Integration, subject to available Upwork tags. Third-party neural engines and AI-assisted application development should be acknowledged. Do not imply independent model training, original inference algorithms or independently authored third-party code.

After the acceptance gates, record a 55-second demonstration:

| Time | Action and truthful narration |
| --- | --- |
| 0–6 s | Show the local project and launch command. If model startup is edited out, label the subsequent engine “already warmed.” |
| 6–14 s | Show the browser at loopback, choose the verified engine/voice and paste a short non-sensitive passage. |
| 14–28 s | Read and let real speech play. Show streaming only if actual Qwen behavior has been checked. |
| 28–37 s | Pause/resume, adjust speed and volume, allow enough speech to hear the result. |
| 37–46 s | Stop; select a different voice and press Read. Avoid claiming a selector changes already buffered speech mid-session. |
| 46–55 s | Show local server/engine diagnostics and the passing test commands; identify third-party engines. |

Defensible measurable claims now: 48 backend, 26 frontend and 9 localhost integration tests passing; real HTTP synthetic cancellation/disconnect verified; bounded requests and framed PCM validation implemented. “Persistent model and warmup reused” is demonstrated with mocks and source inspection, with real-model acceptance still pending. Do not claim measured neural latency, zero underruns, distortion-free stretching, verified Mac acceleration or complete offline independence.

## 12. Exact launch instructions

The tested Windows service-only command is:

```powershell
Set-Location A:\VOX-9K
$env:VOX_SKIP_WARMUP = '1'
$env:VOX_DISABLE_QWEN = '1'
.\.venv\Scripts\python.exe server.py
```

This served `http://127.0.0.1:5000` successfully with neural startup disabled. For Kokoro speech, remove `VOX_SKIP_WARMUP`; for automatic Qwen sidecar startup, also remove `VOX_DISABLE_QWEN`. Those actual inference launch paths were not successfully validated during this audit. The full PowerShell commands, current environment evidence, CUDA prerequisites, recovery steps and unverified macOS Kokoro recipe are in [RUNNING.md](RUNNING.md). No tested macOS or Qwen inference command is claimed.

## 13. Git review

Final branch: `audit/portfolio-readiness-2026-11-11`. HEAD remains `733268d2e31a65de5f58ba96a4f91bd0ef71c824`; the index remains unchanged and nothing is committed.

Modified tracked files: `.gitignore`, `README.md`, `index.html`, `server.py`.

New audit files awaiting owner review: `local_security.py`, `vox_helpers.js`, `requirements-test.txt`, three files in `tests/`, two in `tools/`, and four files in `docs/` (this report, RUNNING, TESTING, THIRD_PARTY_NOTICES). Starting untracked application files remain untracked: `qwen_fast_server.py` (corrected), `qwen_smoke_test.py` and `requirements-fast.txt` (unchanged). No files were staged or deleted.

Starting untracked `.venv-fast/` and `backups/` remain in place and are now ignored. Keep `.venv/`, `.venv-fast/`, `.venv-test/`, `cache/`, `temp/`, `outputs/`, `backups/`, generated WAV/MP3 files, raw `audit/` evidence and secrets excluded. Original license/images/production requirements/smoke-script hashes and unchanged design were checked against the preserved baseline. No unrelated files, public release history or Mac files were altered.
