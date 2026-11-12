# Running VOX-9K

The current Windows checkout supports browser mode and optional Desktop V1. Real Kokoro CPU and Qwen CUDA generation and native playback passed the runtime follow-up. The earlier engineering audit is a historical baseline; current evidence and remaining limitations are in [the Desktop V1 report](DESKTOP_V1_REPORT.md).

## Exact Windows commands

Browser mode:

```powershell
Set-Location A:\VOX-9K
.\.venv\Scripts\python.exe server.py
```

Then open [VOX-9K](http://127.0.0.1:5000) or [localhost](http://localhost:5000). Keep the terminal running.

Desktop mode:

```powershell
Set-Location A:\VOX-9K
.\.venv\Scripts\python.exe desktop.py
```

This opens the same application in its own native window. It does not open Brave. The installed optional dependency is pywebview 6.2.1. To install the tested optional desktop stack elsewhere, use:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-desktop.txt
```

Microsoft WebView2 Runtime and a compatible .NET/Windows Forms runtime are required. The tested machine already has WebView2 157.0.4341.46. Desktop startup/error presentation, ownership and packaging notes are in [DESKTOP.md](DESKTOP.md). No standalone executable or installer has been produced.

## Environment and hardware evidence

Both Windows environments use Python 3.12.10. `.venv` contains Flask 3.1.3, PyKokoro 0.10.4, OnnxVoice 0.2.5 and ONNX Runtime GPU 1.31.0. The optional desktop installation added five packages and changed no previously installed package versions.

`.venv-fast` remains isolated: faster-qwen3-tts 0.5.4, qwen-tts-hf 0.1.1.post1, Transformers 5.15.1, torch/torchaudio 2.11.0+cu126, FastAPI 0.143.0 and Uvicorn 0.54.0. Its `pip check` passes. The older original Qwen stack in `.venv` uses qwen-tts 0.1.1 and Transformers 4.57.3; its existing `pip check` warning about the `onnxruntime` distribution remains. Do not install CPU and GPU ONNX Runtime distributions together to silence it.

Accepted hardware: Windows 10 build 19045, RTX 3060 with 12 GiB. Kokoro runs on CPU. Qwen's CUDA 12.6 stack generated real speech, captured graphs once per sidecar launch, reused the model across reads and recovered after cancellation. No minimum VRAM guarantee or universal latency claim was established.

Kokoro CUDA is **not working in the installed environment**: its ONNX Runtime GPU build asks for CUDA 13/cuDNN 9 and reports missing `cublasLt64_13.dll`. Provider detection alone falsely suggested availability. Auto now checks actual ORT session providers after warmup, reports CPU fallback and disables the failed Kokoro CUDA choice for that process. Explicit CUDA fails clearly. Repair requires a separately approved compatible runtime/package decision; no inference packages were upgraded here. Refer to [ONNX Runtime CUDA requirements](https://onnxruntime.ai/docs/execution-providers/CUDA-ExecutionProvider.html#requirements).

## Model assets and startup

Kokoro's model, voice archive and vocabulary already exist in `cache/pykokoro`. The installed library's normal acquisition path tried to refresh a stale catalog even though the weights were present. VOX-9K now uses the public installed-only resolution API to verify the exact existing model selection and pass local paths into PyKokoro. A corrupt installation is not silently hidden by a download fallback. If no matching installation exists, the previous initial acquisition path remains; it can require network access and large downloads.

Qwen model/tokenizer assets remain under `cache/huggingface`. Acceptance ran with `HF_HUB_OFFLINE=1`; no weights were downloaded. In normal source mode, missing model assets can still require setup downloads. Do not infer that a machine with no model cache can run offline.

Normal startup warms Kokoro, starts or reuses the Qwen sidecar according to the existing policy and serves the interface on `127.0.0.1:5000`. The sidecar binds `127.0.0.1:5001`, reports loading/warming/ready, and retains its model and captured graphs between reads. Health now includes measured model-load and graph-warmup durations. The ownership watcher avoids blocking stdin reads on Windows because they reproduced native scientific-library import stalls.

Optional environment flags are preserved:

```powershell
# Service/UI diagnostics without startup neural warmup or Qwen launch:
$env:VOX_SKIP_WARMUP = '1'
$env:VOX_DISABLE_QWEN = '1'
.\.venv\Scripts\python.exe server.py
```

`VOX_SKIP_WARMUP` only skips startup warmup; a later Kokoro Read will still initialize. `VOX_DISABLE_QWEN` prevents automatic sidecar startup, not access to an already running external sidecar. To restore normal startup in that PowerShell session:

```powershell
Remove-Item Env:VOX_SKIP_WARMUP -ErrorAction SilentlyContinue
Remove-Item Env:VOX_DISABLE_QWEN -ErrorAction SilentlyContinue
```

## Shutdown and recovery

Use Stop to end playback. Browser playback aborts immediately; Qwen cancellation is scoped to its request and is observed between native generation steps. It cannot interrupt a running native CUDA operation instantly. Kokoro's single-threaded Flask service finishes an in-flight inference call even after browser playback stops.

Closing an owning desktop window signals Flask through its ownership pipe; Flask stops only its owned Qwen sidecar and exits. The launcher waits and escalates only its own child if needed. Reused external Flask/sidecar services are preserved. Closing the original owner disconnects attached windows. Browser mode remains terminal-owned; Ctrl+C shuts it down normally.

If a port is occupied, identify the process before taking action. The desktop wrapper reuses a recognized VOX-9K service and rejects an unrelated or unresponsive service. It never terminates an unidentified process. Logs for owned desktop launches are under ignored `audit/desktop-<instance-id>.log`.

A terminal Qwen startup error surfaces promptly; correct the cause and restart the owning application. There is no automatic model-reload endpoint. Health polling has a two-second request timeout and a two-minute readiness deadline. Do not manually start a second sidecar alongside the parent.

Local Host/Origin guards and restricted sidecar CORS remain intact. Use the loopback-served page, not `file://`. Local CLI requests can omit Origin; this is not authentication against other software running under your account. No cloud TTS service or application analytics were added.

## Installation portability

Existing `requirements.txt`, `requirements-gpu.txt` and `requirements-fast.txt` were preserved. The Kokoro production files remain unpinned recipes, not freshly validated lockfiles. Use distinct CPU/GPU environments and rehearse clean installation before distribution. ONNX Runtime DLL compatibility and CUDA-enabled PyTorch wheels are separate concerns.

The Mac checkout was not accessed or modified. This remains an **unverified** Kokoro browser-mode recipe:

```bash
cd ~/VOX-9K
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
VOX_DISABLE_QWEN=1 .venv/bin/python server.py
```

Start with Python 3.12 and ONNX Runtime CPU, then check native phonemizer requirements and real playback on the Mac. CoreML and Mac desktop mode were not tested. There is no MPS/Metal Qwen backend in this project.

## Local export and appearance features

See [WAV export and backgrounds](EXPORT_AND_BACKGROUNDS.md) for native-speed output, approximate versus measured metrics, limits, per-user image paths and restore-default. Launch commands above are unchanged. Windows native saving uses pywebview's enabled Save dialog; browser preferences determine browser saving. No standalone installer is provided.
