# VOX-9K Desktop V1

Desktop V1 opens the existing VOX-9K interface in a native Windows window using pywebview and Microsoft Edge WebView2. It uses the same Flask application, Kokoro engine and optional Qwen Fast sidecar as browser mode. No standalone executable or installer is available.

## Installation and launch

The tested setup is Windows 10 build 19045, Python 3.12.10, pywebview 6.2.1 and WebView2 157.0.4341.46. The optional desktop stack has been installed in this checkout's `.venv`. The following command is for an environment that does not yet have it:

```powershell
Set-Location A:\VOX-9K
.\.venv\Scripts\python.exe -m pip install -r requirements-desktop.txt
```

The desktop requirements pin the tested pywebview, Bottle, proxy_tools, pythonnet and clr_loader versions. No inference packages were upgraded or replaced. Microsoft Edge **WebView2 Runtime**, rather than the ordinary Edge browser alone, must be present. A compatible .NET/Windows Forms runtime is also needed. Refer to the [pywebview installation guide](https://pywebview.flowrl.com/guide/installation) and [Microsoft runtime distribution guide](https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/distribution).

Browser mode remains:

```powershell
Set-Location A:\VOX-9K
.\.venv\Scripts\python.exe server.py
```

Open [VOX-9K in a browser](http://127.0.0.1:5000).

Desktop mode is:

```powershell
Set-Location A:\VOX-9K
.\.venv\Scripts\python.exe desktop.py
```

The native window is titled `VOX-9K`, starts at 1280×960, is resizable, and has a 960×720 minimum. The existing page, background and controls are served from loopback. The launcher shows a startup page while the service prepares, then navigates to the existing application. No address bar, tabs, custom menu or new artwork is added. No custom icon is included. The owner supplied the background/screenshot provenance and redistribution permission; see THIRD_PARTY_NOTICES.md.

## Startup and ownership

`desktop.py` imports pywebview only in desktop mode and starts its GUI loop on the main thread. A background callback checks `/health` for VOX-9K's service name, protocol version and instance identity. A recognized existing service is reused; an unrelated, unresponsive or busy service on port 5000 produces a useful error without terminating it.

If the port is free, the desktop process launches `server.py` with the same interpreter, an instance ID and an ownership pipe. Flask startup and model policy remain in `server.py`. The parent retains the persistent Qwen sidecar policy; model loading and graph capture occur once per sidecar lifetime, not per normal Read. Readiness waits for the actual matching Flask instance, not merely an occupied port. The native renderer is explicitly `edgechromium`; legacy MSHTML fallback is not used.

Closing an owning desktop window closes the Flask ownership pipe. Flask stops its owned Qwen sidecar and exits; the desktop launcher waits and has bounded terminate/kill/reap fallbacks. The same pipe also signals parent death. On Windows, ownership monitoring polls the dedicated pipe handle instead of making a blocking stdin read, which reproduced a native-library import stall during acceptance.

An attached desktop window owns neither an existing Flask service nor its sidecar. Closing that window preserves them. Closing the original owning window ends the backend and disconnects any attached windows; there is no ownership handoff system. A compatible externally started Qwen sidecar is preserved. Fixed ports 5000/5001 remain part of the current application contract.

Startup failures close owned services and show an escaped error message. GUI/renderer initialization failures produce an actionable console message. Per-launch service logs are in ignored `audit/desktop-<instance-id>.log`. The launcher does not install runtimes or download models on its own.

## Accepted functionality and limitations

Real native-window checks passed twice with WebView2: existing controls rendered; Kokoro CPU audio played with Sarah and Michael; Qwen CUDA PCM played with Ryan and Aiden; pause/resume and Stop worked; a new Qwen voice played after cancellation; switching back to Kokoro succeeded. Speed 1.2× and volume 40% were applied, with the Kokoro pitch-preservation flag enabled. The owner reported: “Speech sounded correct.” This is listening acceptance, not a controlled perceptual or spectral benchmark.

`fetch`, streaming responses, Web Audio, AudioContext, AudioBufferSourceNode, `Intl.Segmenter` and `crypto.randomUUID` were checked in the actual native engine. Qwen real PCM playback exercised streaming responses. The application still uses classic scripts; it does not require a module conversion. WebView2 is Chromium-based and supports modern web capabilities, but arbitrary module dependency/loading scenarios were not separately tested. A browser Read completed in the available in-app Chromium browser; default Brave was not directly controlled by the browser connector.

Kokoro CPU and Qwen CUDA are verified on this machine. Kokoro's installed ONNX Runtime GPU build requires CUDA 13/cuDNN 9 DLLs; `cublasLt64_13.dll` is missing. It previously fell back to CPU while retaining a GPU label. Auto now detects the actual ORT session's provider, reports CPU and disables the failed Kokoro CUDA mode. Explicit Kokoro CUDA raises a clear error. Qwen's separate torch CUDA 12.6 stack works. No runtime packages were changed to repair the Kokoro GPU mismatch.

Cancellation remains cooperative between native generation steps. Long-form Qwen playback and prolonged pauses can accumulate queued PCM; per-buffer WSOLA may have boundary artifacts on passages not covered by listening acceptance. Extended stress, formal pitch measurements and exhaustive browser/device testing were not performed. Modern browser APIs are required. macOS desktop mode and CoreML were not tested; the Mac checkout was not modified.

The existing cached Kokoro installation is now verified and resolved locally before catalog acquisition. Missing installations retain the previous first-run setup behavior, which may download large model assets. Cached Qwen acceptance used `HF_HUB_OFFLINE=1`. No large model assets were downloaded during this work. Models, dependencies, native runtimes and visual assets retain their own licenses; see [third-party notices](THIRD_PARTY_NOTICES.md).

## Packaging feasibility for a later phase

A Windows PyInstaller **one-folder** pilot is the appropriate first packaging experiment. pywebview documents PyInstaller support, and one-folder bundles expose missing files more clearly during debugging. No packaging tool was installed or run here. [pywebview freezing guidance](https://pywebview.flowrl.com/guide/freezing), [PyInstaller operating modes](https://pyinstaller.org/en/stable/operating-mode.html).

Before building, address these concrete requirements:

- Bundle the UI HTML, `vox_helpers.js`, background asset, service modules, ownership helper and required notices. Retain the included visual asset provenance and permission record.
- Define frozen backend entry points. The current `sys.executable server.py` invocation assumes a Python source checkout; in a frozen desktop executable it would launch the executable itself. Likewise, the Qwen sidecar currently assumes `.venv-fast\Scripts\python.exe`. Use explicit packaged backend/sidecar entry points rather than shipping those source-only assumptions unchanged.
- Keep the original Kokoro and optimized Qwen dependency stacks isolated. Include required ONNX/PyTorch, phonemizer and other native DLLs only after compatibility and redistribution review. Resolve the Kokoro CUDA 13 mismatch in a separate approved environment change.
- Separate read-only installed assets from writable model caches and logs. A future installer should use a per-user data location, such as `%LOCALAPPDATA%\VOX-9K`, rather than writing caches into Program Files. Current source-mode paths have not been changed for packaging.
- Detect or provision the WebView2 Runtime according to Microsoft's distribution guidance. Evergreen avoids bundling a fixed browser image but still needs runtime availability and upgrade compatibility testing.
- Choose optional model acquisition or a separately licensed model payload. CUDA PyTorch, dual Python stacks and weights can make distribution multiple gigabytes; measure a pilot bundle before quoting an installer size. Avoid one-file extraction overhead during initial validation.
- Add shortcuts that launch the desktop entry point with the correct working/data paths. Test uninstall behavior without deleting the user's separately retained models or audio.
- Plan code signing and clean-machine acceptance. Unsigned Windows executables may trigger SmartScreen or antivirus warnings; signing does not guarantee warning-free reputation. Review third-party notices before shipping.
- Build a future macOS Kokoro-only package on macOS, test its native web engine/phonemizer dependencies, then handle signing and notarization. Do not include the Windows CUDA Qwen path as Mac support.

The current native-window source launch is accepted. Frozen executable and installer distribution remain a separate engineering phase.
