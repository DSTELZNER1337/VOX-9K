from flask import Flask, request, send_file, send_from_directory, jsonify
from pykokoro import GenerationConfig, KokoroSynthesizer, SynthesisConfig

from importlib.metadata import PackageNotFoundError, version
from io import BytesIO
from pathlib import Path

import atexit
import uuid

from local_security import MAX_REQUEST_BYTES, permitted_request
from audio_export import ExportJobs, MAX_TEXT, qwen_frames
from chunk_cache import ChunkCache
from backgrounds import BackgroundStore, user_data_dir, MAX_UPLOAD
import json
import os
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request


# --------------------------------------------------
# APP SETUP
# --------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent

CACHE_DIR = BASE_DIR / "cache"
KOKORO_CACHE_DIR = CACHE_DIR / "pykokoro"
QWEN_CACHE_DIR = CACHE_DIR / "huggingface"
TEMP_DIR = BASE_DIR / "temp"

for directory in (
    KOKORO_CACHE_DIR,
    QWEN_CACHE_DIR,
    TEMP_DIR,
):
    directory.mkdir(
        parents=True,
        exist_ok=True,
    )

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_REQUEST_BYTES


@app.before_request
def guard_local_requests():
    if request.path == "/background-image" and request.method == "POST":
        request.max_content_length = MAX_UPLOAD
    if not permitted_request(request.headers, 5000):
        return jsonify({"error": "Local application requests only."}), 403


@app.errorhandler(413)
def oversized_request(error):
    return jsonify({"error": "Request body is too large."}), 413


# --------------------------------------------------
# OPTIONAL RUNTIME DISCOVERY
# --------------------------------------------------

try:
    import onnxruntime as ort
except ImportError:
    ort = None


def package_version(package_name):
    try:
        return version(package_name)
    except PackageNotFoundError:
        return "unknown"


# --------------------------------------------------
# ENGINE CONSTANTS
# --------------------------------------------------

VALID_ENGINES = {
    "kokoro",
    "qwen",
}

VALID_COMPUTE_MODES = {
    "auto",
    "cpu",
    "cuda",
}

VALID_KOKORO_VOICES = {
    "af_sarah", "af_heart", "af_bella", "af_nicole", "af_nova", "af_sky",
    "am_michael", "am_fenrir", "am_puck", "am_onyx", "am_liam",
    "bf_emma", "bf_isabella", "bf_lily", "bm_george", "bm_fable",
    "bm_lewis", "bm_daniel",
}

QWEN_MODEL_ID = "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice"
QWEN_FAST_URL = "http://127.0.0.1:5001"
QWEN_FAST_PYTHON = BASE_DIR / ".venv-fast" / "Scripts" / "python.exe"
QWEN_FAST_SERVER = BASE_DIR / "qwen_fast_server.py"


# --------------------------------------------------
# KOKORO COMPUTE / ENGINE SETUP
# --------------------------------------------------

kokoro_synthesizers = {}
kokoro_cuda_failed = False
engine_lock = threading.RLock()


def available_onnx_providers():
    if ort is None:
        return []

    try:
        return ort.get_available_providers()
    except Exception:
        return []


def kokoro_compute_available(mode):
    providers = available_onnx_providers()

    if mode == "auto":
        return kokoro_auto_preference() != "unknown"

    if mode == "cpu":
        return "CPUExecutionProvider" in providers

    if mode == "cuda":
        return "CUDAExecutionProvider" in providers and not kokoro_cuda_failed

    return False


def kokoro_auto_preference():
    providers = available_onnx_providers()

    if "CUDAExecutionProvider" in providers and not kokoro_cuda_failed:
        return "cuda"

    if "CPUExecutionProvider" in providers:
        return "cpu"

    return "unknown"


def installed_kokoro_assets():
    """Resolve the existing default model locally before any catalog acquisition."""
    try:
        from onnxvoice import OnnxVoice
        from onnxvoice.errors import NotInstalledError
    except ImportError:
        return {}
    try:
        installation = OnnxVoice(cache_dir=KOKORO_CACHE_DIR, offline=True).resolve(
            "kokoro:v1.0", quality="fp32",
            distribution="github-model-files-v1.0-timestamped-r4",
        )
    except NotInstalledError:
        # Preserve first-run PyKokoro acquisition when no installation exists.
        return {}
    return {
        "model_path": installation.artifact_path("model"),
        "voices_path": installation.artifact_path("voices"),
        "model_config_path": installation.artifact_path("vocab"),
    }


def build_kokoro_config(compute_mode="auto"):
    return SynthesisConfig(
        **installed_kokoro_assets(),
        provider=kokoro_auto_preference() if compute_mode == "auto" else compute_mode,
        voice="af_sarah",
        cache_dir=KOKORO_CACHE_DIR,
        long_text_split="sentence",
        long_text_use_spacy=False,
        generation=GenerationConfig(
            lang="en-us",
        ),
    )


def kokoro_active_providers(synthesizer):
    """Read OnnxVoice session diagnostics through the installed PyKokoro adapter.

    The adapter nesting is version-specific; missing diagnostics means unknown,
    never evidence of successful CUDA execution.
    """
    renderer = getattr(synthesizer, "_renderer", None)
    backend = getattr(renderer, "_backend", None)
    runtime = getattr(backend, "_runtime", None)
    adapter = getattr(runtime, "_runtime", None)
    owned_sessions = getattr(adapter, "_owned_sessions", None)
    if not callable(owned_sessions):
        return None
    sessions = owned_sessions()
    if not isinstance(sessions, (list, tuple)) or not sessions:
        return None
    # OnnxVoice 0.2.5 diagnostics label the requested selection "active".
    # Ask each actual ORT session instead: failed CUDA can silently fall back.
    return sorted({provider for session in sessions for provider in session.session.get_providers()})



def create_kokoro_synthesizer(compute_mode):
    global kokoro_cuda_failed
    if compute_mode not in VALID_COMPUTE_MODES:
        raise ValueError(
            f"Unsupported compute mode: {compute_mode}"
        )

    if not kokoro_compute_available(compute_mode):
        raise RuntimeError(
            f"Kokoro compute mode '{compute_mode}' is unavailable. "
            f"Available ONNX Runtime providers: {available_onnx_providers()}"
        )

    print(
        f"Loading Kokoro engine: {compute_mode.upper()}..."
    )

    requested_provider = kokoro_auto_preference() if compute_mode == "auto" else compute_mode
    synthesizer = KokoroSynthesizer(build_kokoro_config(compute_mode))
    try:
        synthesizer.synthesize_text(
            "Voice system ready.", language="en-us", voice="af_sarah",
        )
        active = kokoro_active_providers(synthesizer)
        if requested_provider == "cuda" and active is not None and "CUDAExecutionProvider" not in active:
            kokoro_cuda_failed = True
            if compute_mode == "cuda":
                raise RuntimeError("Kokoro CUDA initialization failed; the runtime fell back to CPU. Select CPU or correct the ONNX Runtime CUDA DLL dependencies.")
            print("Kokoro CUDA initialization failed; Auto is using CPU.")
    except Exception:
        close_method = getattr(synthesizer, "close", None)
        if callable(close_method):
            close_method()
        raise

    print(
        f"Kokoro {compute_mode.upper()} engine ready."
    )

    return synthesizer


def get_kokoro_synthesizer(compute_mode):
    with engine_lock:
        existing = kokoro_synthesizers.get(
            compute_mode
        )

        if existing is not None:
            return existing

        synthesizer = create_kokoro_synthesizer(
            compute_mode
        )

        kokoro_synthesizers[
            compute_mode
        ] = synthesizer

        return synthesizer


# --------------------------------------------------
# QWEN FAST SIDECAR
# --------------------------------------------------

qwen_sidecar_process = None
qwen_sidecar_owned = False


def qwen_fast_installation_available():
    return (
        QWEN_FAST_PYTHON.is_file()
        and
        QWEN_FAST_SERVER.is_file()
    )


def qwen_sidecar_health(timeout=0.35):
    try:
        with urllib.request.urlopen(
            QWEN_FAST_URL + "/health",
            timeout=timeout,
        ) as response:
            health = json.loads(response.read(65536).decode("utf-8"))
            if (isinstance(health, dict)
                    and health.get("service") == "vox-9k-qwen"
                    and health.get("model") == QWEN_MODEL_ID
                    and health.get("status") in {"starting", "loading", "warming", "ready", "error"}):
                return health
            return None

    except (
        urllib.error.URLError,
        TimeoutError,
        json.JSONDecodeError,
        UnicodeError,
        OSError,
    ):
        return None


def start_qwen_sidecar():
    global qwen_sidecar_process
    global qwen_sidecar_owned

    if qwen_sidecar_health() is not None:
        print(
            "Qwen fast sidecar already running on port 5001."
        )
        return True

    if not qwen_fast_installation_available():
        print(
            "Qwen fast sidecar unavailable. "
            "Expected .venv-fast and qwen_fast_server.py."
        )
        return False

    env = os.environ.copy()
    env["HF_HOME"] = str(QWEN_CACHE_DIR)
    env["HF_HUB_CACHE"] = str(QWEN_CACHE_DIR / "hub")
    env["PYTHONUNBUFFERED"] = "1"
    env["VOX_PARENT_PIPE"] = "1"

    print(
        "Starting Qwen fast sidecar in .venv-fast..."
    )

    qwen_sidecar_process = subprocess.Popen(
        [
            str(QWEN_FAST_PYTHON),
            str(QWEN_FAST_SERVER),
        ],
        cwd=str(BASE_DIR),
        env=env,
        stdin=subprocess.PIPE,
    )

    qwen_sidecar_owned = True

    # Wait only for the local HTTP service to appear.
    # Model loading and CUDA graph capture continue in the background.
    deadline = time.time() + 5.0

    while time.time() < deadline:
        if qwen_sidecar_process.poll() is not None:
            print(
                "Qwen fast sidecar exited during startup."
            )
            return False

        health = qwen_sidecar_health(
            timeout=0.2
        )

        if health is not None:
            print(
                "Qwen fast sidecar connected. "
                f"Status: {health.get('status', 'unknown')}"
            )
            return True

        time.sleep(0.1)

    print(
        "Qwen fast sidecar is still starting in the background."
    )
    return True


def stop_qwen_sidecar():
    global qwen_sidecar_process

    if (
        not qwen_sidecar_owned
        or
        qwen_sidecar_process is None
    ):
        return

    try:
        # Closing the ownership pipe also reaches the actual Python child
        # behind the Windows venv launcher. Parent death closes it as well.
        if qwen_sidecar_process.stdin is not None:
            qwen_sidecar_process.stdin.close()
        qwen_sidecar_process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        qwen_sidecar_process.terminate()
        try:
            qwen_sidecar_process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            qwen_sidecar_process.kill()
            qwen_sidecar_process.wait(timeout=3)
    except OSError as error:
        print("Qwen sidecar shutdown error:", error)



# --------------------------------------------------
# ENGINE CLEANUP
# --------------------------------------------------


def close_engines():
    for synthesizer in kokoro_synthesizers.values():
        close_method = getattr(
            synthesizer,
            "close",
            None,
        )

        if callable(close_method):
            try:
                close_method()
            except Exception:
                pass

    stop_qwen_sidecar()


atexit.register(close_engines)


# --------------------------------------------------
# SERVE VOX-9K
# --------------------------------------------------

MAIN_INSTANCE_ID = os.environ.get("VOX_INSTANCE_ID") or uuid.uuid4().hex


@app.route("/health")
def application_health():
    return jsonify({"service": "vox-9k", "api_version": 1, "instance_id": MAIN_INSTANCE_ID})


@app.route("/")
def index():
    return send_from_directory(
        BASE_DIR,
        "index.html",
    )


@app.route("/vox_helpers.js")
def helpers():
    return send_from_directory(BASE_DIR, "vox_helpers.js")


@app.route("/features.js")
def feature_script():
    return send_from_directory(BASE_DIR, "features.js")


@app.route("/background.png")
def background():
    return send_from_directory(
        BASE_DIR,
        "background.png",
    )


# --------------------------------------------------
# SYSTEM / ENGINE INFO
# --------------------------------------------------

@app.route("/system-info")
def system_info():
    kokoro_cuda = kokoro_compute_available(
        "cuda"
    )

    kokoro_cpu = kokoro_compute_available(
        "cpu"
    )

    qwen_installed = qwen_fast_installation_available()
    qwen_health = qwen_sidecar_health()

    qwen_status = (
        qwen_health.get("status")
        if qwen_health
        else (
            "starting"
            if qwen_installed
            else "not-installed"
        )
    )

    return jsonify({
        "pykokoro_version":
            package_version("pykokoro"),

        "onnxruntime_version":
            package_version("onnxruntime-gpu")
            if kokoro_cuda
            else package_version("onnxruntime"),

        "available_providers":
            available_onnx_providers(),

        "modes": {
            "auto":
                kokoro_auto_preference()
                != "unknown",

            "cpu":
                kokoro_cpu,

            "cuda":
                kokoro_cuda,
        },

        "auto_preference":
            kokoro_auto_preference(),

        "engines": {
            "kokoro": {
                "installed": True,

                "auto_preference":
                    kokoro_auto_preference(),

                "modes": {
                    "auto":
                        kokoro_auto_preference()
                        != "unknown",

                    "cpu":
                        kokoro_cpu,

                    "cuda":
                        kokoro_cuda,
                },

                "loaded":
                    sorted(
                        kokoro_synthesizers.keys()
                    ),
            },

            "qwen": {
                "installed":
                    qwen_installed,

                "model":
                    QWEN_MODEL_ID,

                "backend":
                    "faster-qwen3-tts",

                "status":
                    qwen_status,

                "gpu":
                    qwen_health.get("gpu")
                    if qwen_health
                    else None,

                "torch_version":
                    qwen_health.get("torch_version")
                    if qwen_health
                    else None,

                "auto_preference":
                    "cuda"
                    if qwen_installed
                    else "unknown",

                "modes": {
                    "auto":
                        qwen_installed,

                    "cpu":
                        False,

                    "cuda":
                        qwen_installed,
                },

                "stream_url":
                    QWEN_FAST_URL + "/stream",
            },
        },
    })


# --------------------------------------------------
# KOKORO SYNTHESIS
# --------------------------------------------------


def synthesize_kokoro(
    text,
    voice,
    compute_mode,
):
    synthesizer = get_kokoro_synthesizer(
        compute_mode
    )

    with engine_lock:
        rendered = synthesizer.synthesize_text(
            text, language="en-us", voice=voice,
        )

    with tempfile.TemporaryDirectory(
        dir=TEMP_DIR
    ) as temp_dir:
        wav_path = (
            Path(temp_dir)
            / "vox_output.wav"
        )

        rendered.save_wav(
            str(wav_path)
        )

        return wav_path.read_bytes()


# --------------------------------------------------
# TEXT TO SPEECH
# --------------------------------------------------

@app.route("/tts", methods=["POST"])
def text_to_speech():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "A JSON object is required."}), 400
    defaults = {"text": "", "engine": "kokoro", "voice": "af_sarah", "compute": "auto"}
    if any(not isinstance(data.get(key, value), str) for key, value in defaults.items()):
        return jsonify({"error": "Text, engine, voice and compute must be strings."}), 400
    text = data.get("text", "").strip()
    engine = data.get("engine", "kokoro").strip().lower()
    voice = data.get("voice", "af_sarah").strip()
    compute_mode = data.get("compute", "auto").strip().lower()
    if engine == "kokoro" and voice not in VALID_KOKORO_VOICES:
        return jsonify({"error": "Unsupported Kokoro voice."}), 400

    if not text:
        return jsonify({
            "error": "No text provided."
        }), 400

    if engine not in VALID_ENGINES:
        return jsonify({
            "error":
                "Engine must be one of: kokoro, qwen."
        }), 400

    if compute_mode not in VALID_COMPUTE_MODES:
        return jsonify({
            "error":
                "Compute must be one of: auto, cpu, cuda."
        }), 400

    if len(text) > 3000:
        return jsonify({
            "error": "Text chunk is too long."
        }), 400

    if engine == "qwen":
        return jsonify({
            "error":
                "Qwen now uses the streaming fast sidecar endpoint."
        }), 400

    if not kokoro_compute_available(
        compute_mode
    ):
        return jsonify({
            "error":
                f"Kokoro compute mode '{compute_mode}' is unavailable.",

            "available_providers":
                available_onnx_providers(),
        }), 400

    try:
        audio_data = synthesize_kokoro(
            text,
            voice,
            compute_mode,
        )

        audio_bytes = BytesIO(
            audio_data
        )

        audio_bytes.seek(0)

        response = send_file(
            audio_bytes,
            mimetype="audio/wav",
            download_name="vox_output.wav",
        )

        response.headers[
            "X-VOX-Engine"
        ] = "kokoro"

        response.headers[
            "X-VOX-Compute"
        ] = compute_mode

        return response

    except Exception as error:
        print(
            "KOKORO TTS error:",
            error,
        )

        return jsonify({
            "error": "Kokoro synthesis failed. Check the local server console."
        }), 500


# --------------------------------------------------
# LOCAL EXPORT / BACKGROUND FEATURES
# --------------------------------------------------

pcm_cache = ChunkCache(TEMP_DIR / "qwen-audio-cache")
background_store = BackgroundStore(user_data_dir())
VALID_QWEN_VOICES = {"Vivian","Serena","Uncle_Fu","Dylan","Eric","Ryan","Aiden","Ono_Anna","Sohee"}


def export_frames(text, engine, voice, compute, request_id, cancel):
    import numpy as np
    if engine == "kokoro":
        import soundfile as sf
        data, rate = sf.read(BytesIO(synthesize_kokoro(text,voice,compute)),dtype="float32",always_2d=True)
        if data.shape[1] != 1:
            raise ValueError("Expected mono Kokoro audio.")
        yield data[:,0],rate
    else:
        path=pcm_cache.find(text,voice)
        if path is not None:
            try:
                handle=path.open("rb")
            except FileNotFoundError:
                handle=None
            if handle is not None:
                with handle:
                    while True:
                        data=handle.read(65536)
                        if not data:return
                        if len(data)%4:raise ValueError("Invalid cached PCM.")
                        yield np.frombuffer(data,dtype="<f4"),24000
                return
        yield from qwen_frames(text,voice,request_id,cancel,QWEN_FAST_URL)


export_jobs = ExportJobs(TEMP_DIR / "exports",export_frames)
atexit.register(export_jobs.close)


@app.route("/exports", methods=["POST"])
def create_export():
    data=request.get_json(silent=True)
    if not isinstance(data,dict):
        return jsonify(error="A JSON object is required."),400
    chunks=data.get("chunks")
    engine=data.get("engine")
    voice=data.get("voice")
    compute=data.get("compute")
    if (not isinstance(chunks,list) or not chunks or len(chunks)>256
        or any(not isinstance(x,str) or not x.strip() or len(x)>3000 for x in chunks)
        or sum(len(x) for x in chunks)>MAX_TEXT):
        return jsonify(error="Export needs nonempty chunks, at most 20,000 characters total."),400
    if not isinstance(engine,str) or engine not in VALID_ENGINES:
        return jsonify(error="Unsupported engine."),400
    voices=VALID_KOKORO_VOICES if engine=="kokoro" else VALID_QWEN_VOICES
    if not isinstance(voice,str) or voice not in voices or not isinstance(compute,str) or compute not in VALID_COMPUTE_MODES:
        return jsonify(error="Unsupported voice or compute mode."),400
    if engine=="kokoro" and not kokoro_compute_available(compute):
        return jsonify(error="Kokoro compute mode unavailable."),400
    if engine=="qwen" and compute=="cpu":
        return jsonify(error="Qwen export requires CUDA."),400
    try:
        key=export_jobs.create(chunks,engine,voice,compute)
        return jsonify(id=key),202
    except RuntimeError as error:
        return jsonify(error=str(error)),409


@app.route("/exports/<key>", methods=["GET","DELETE"])
def export_status(key):
    if request.method=="DELETE":
        if not export_jobs.cancel(key):return jsonify(error="Export not found."),404
        return jsonify(cancelled=True)
    status=export_jobs.status(key)
    if status is None:return jsonify(error="Export not found or expired."),404
    return jsonify(status)


@app.route("/exports/<key>/file")
def export_file(key):
    with export_jobs.lock:
        status=export_jobs.status(key)
        if status is None:return jsonify(error="Export not found or expired."),404
        if status["state"]!="ready":return jsonify(error="Export is not ready."),409
        response=send_file(export_jobs.jobs[key]["path"],mimetype="audio/wav",
            as_attachment=True,download_name="VOX-9K-Recording.wav",conditional=False)
        response.headers["Cache-Control"]="no-store"
        return response


@app.route("/background-image", methods=["GET","POST","DELETE"])
def custom_background():
    if request.method=="POST":
        try:
            background_store.save(request.get_data())
        except ValueError as error:
            return jsonify(error=str(error)),400
        except OSError:
            return jsonify(error="Could not save the background in application data."),500
        return jsonify(custom=True)
    if request.method=="DELETE":
        try:background_store.restore()
        except OSError:return jsonify(error="Could not restore the default background."),500
        return jsonify(custom=False)
    with background_store.lock:
        path=background_store.path if background_store.path.is_file() else BASE_DIR/"background.png"
        response=send_file(path,mimetype="image/png")
        response.headers["Cache-Control"]="no-store"
        return response


def prune_exports():
    while not feature_shutdown.wait(30):
        try:export_jobs.prune()
        except OSError:pass


feature_shutdown=threading.Event()
threading.Thread(target=prune_exports,name="vox-export-cleanup",daemon=True).start()
atexit.register(feature_shutdown.set)


# --------------------------------------------------
# START SERVER
# --------------------------------------------------

def watch_desktop_parent():
    from process_lifecycle import wait_for_parent_eof
    wait_for_parent_eof()
    try:
        stop_qwen_sidecar()
    finally:
        os._exit(0)


if __name__ == "__main__":
    if os.environ.get("VOX_DESKTOP_PARENT_PIPE") == "1":
        threading.Thread(target=watch_desktop_parent, name="vox-desktop-owner", daemon=True).start()
    print()
    print("==============================")
    print("       VOX-9K SERVER")
    print("==============================")
    print()

    print(
        "Kokoro ONNX providers:",
        available_onnx_providers(),
    )

    print(
        "Qwen fast environment:",
        qwen_fast_installation_available(),
    )

    print()

    if os.environ.get("VOX_SKIP_WARMUP") != "1" and kokoro_compute_available("auto"):
        try:
            get_kokoro_synthesizer(
                "auto"
            )
        except Exception as error:
            print(
                "Kokoro Auto warmup error:",
                error,
            )

    if os.environ.get("VOX_DISABLE_QWEN") != "1":
        start_qwen_sidecar()

    print()
    print("Open:")
    print("http://127.0.0.1:5000")
    print()

    try:
        app.run(
            host="127.0.0.1",
            port=5000,
            debug=False,
            threaded=False,
        )
    finally:
        # Cancel before interpreter teardown. A non-daemon export worker finishes
        # its in-flight native step before atexit closes the cached synthesizer.
        feature_shutdown.set()
        export_jobs.close()
