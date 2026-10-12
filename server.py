from flask import Flask, request, send_file, send_from_directory, jsonify
from pykokoro import GenerationConfig, KokoroSynthesizer, SynthesisConfig

from importlib.metadata import PackageNotFoundError, version
from io import BytesIO
from pathlib import Path

import atexit
import os
import tempfile
import threading

try:
    import onnxruntime as ort
except ImportError:
    ort = None


# --------------------------------------------------
# APP SETUP
# --------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
CACHE_DIR = BASE_DIR / "cache" / "pykokoro"
TEMP_DIR = BASE_DIR / "temp"

CACHE_DIR.mkdir(
    parents=True,
    exist_ok=True
)

TEMP_DIR.mkdir(
    parents=True,
    exist_ok=True
)

app = Flask(__name__)


# --------------------------------------------------
# COMPUTE / ENGINE SETUP
# --------------------------------------------------

VALID_COMPUTE_MODES = {
    "auto",
    "cpu",
    "cuda",
}

# Each mode gets its own synthesizer.
# Engines are created only when first requested,
# then reused for the rest of the server session.
synthesizers = {}

# Environment variables are process-global, so protect
# engine creation even if Flask is made threaded later.
engine_lock = threading.RLock()


def package_version(package_name):
    try:
        return version(package_name)
    except PackageNotFoundError:
        return "unknown"


def available_onnx_providers():
    if ort is None:
        return []

    try:
        return ort.get_available_providers()
    except Exception:
        return []


def compute_mode_available(mode):
    providers = available_onnx_providers()

    if mode == "auto":
        return bool(providers)

    if mode == "cpu":
        return "CPUExecutionProvider" in providers

    if mode == "cuda":
        return "CUDAExecutionProvider" in providers

    return False


def build_kokoro_config():
    return SynthesisConfig(
        voice="af_sarah",

        cache_dir=CACHE_DIR,

        long_text_split="sentence",

        long_text_use_spacy=False,

        generation=GenerationConfig(
            lang="en-us"
        ),
    )


def create_synthesizer(compute_mode):
    """
    Create and warm one Kokoro synthesizer for a compute mode.

    PyKokoro 0.10.x uses OnnxVoice underneath. OnnxVoice supports
    provider selection through ONNXVOICE_PROVIDER.

    The warmup call forces the ONNX session to be created while the
    requested provider policy is active. After warmup, that synthesizer
    is cached and reused.
    """

    if compute_mode not in VALID_COMPUTE_MODES:
        raise ValueError(
            f"Unsupported compute mode: {compute_mode}"
        )

    if not compute_mode_available(compute_mode):
        providers = available_onnx_providers()

        raise RuntimeError(
            f"Compute mode '{compute_mode}' is unavailable. "
            f"Available ONNX Runtime providers: {providers}"
        )

    print(
        f"Loading VOX-9K engine: {compute_mode.upper()}..."
    )

    old_provider = os.environ.get(
        "ONNXVOICE_PROVIDER"
    )

    old_providers = os.environ.get(
        "ONNXVOICE_PROVIDERS"
    )

    try:
        # Use the singular provider setting so each cached
        # synthesizer is pinned to the requested mode.
        os.environ[
            "ONNXVOICE_PROVIDER"
        ] = compute_mode

        # Avoid a plural provider policy overriding it.
        os.environ.pop(
            "ONNXVOICE_PROVIDERS",
            None
        )

        synthesizer = KokoroSynthesizer(
            build_kokoro_config()
        )

        # Force model/session creation now while the provider
        # environment is set.
        synthesizer.synthesize_text(
            "Voice system ready.",
            language="en-us",
            voice="af_sarah",
        )

    finally:
        if old_provider is None:
            os.environ.pop(
                "ONNXVOICE_PROVIDER",
                None
            )
        else:
            os.environ[
                "ONNXVOICE_PROVIDER"
            ] = old_provider

        if old_providers is None:
            os.environ.pop(
                "ONNXVOICE_PROVIDERS",
                None
            )
        else:
            os.environ[
                "ONNXVOICE_PROVIDERS"
            ] = old_providers

    print(
        f"VOX-9K {compute_mode.upper()} engine ready."
    )

    return synthesizer


def get_synthesizer(compute_mode):
    with engine_lock:

        existing = synthesizers.get(
            compute_mode
        )

        if existing is not None:
            return existing

        synthesizer = create_synthesizer(
            compute_mode
        )

        synthesizers[
            compute_mode
        ] = synthesizer

        return synthesizer


def close_synthesizers():
    for synthesizer in synthesizers.values():

        close_method = getattr(
            synthesizer,
            "close",
            None
        )

        if callable(close_method):
            try:
                close_method()
            except Exception:
                pass


atexit.register(
    close_synthesizers
)


# --------------------------------------------------
# SERVE VOX-9K
# --------------------------------------------------

@app.route("/")
def index():
    return send_from_directory(
        BASE_DIR,
        "index.html"
    )


@app.route("/background.png")
def background():
    return send_from_directory(
        BASE_DIR,
        "background.png"
    )


# --------------------------------------------------
# SYSTEM / COMPUTE INFO
# --------------------------------------------------

@app.route("/system-info")
def system_info():

    providers = available_onnx_providers()

    cuda_available = (
        "CUDAExecutionProvider"
        in providers
    )

    cpu_available = (
        "CPUExecutionProvider"
        in providers
    )

    if cuda_available:
        auto_choice = "cuda"
    elif cpu_available:
        auto_choice = "cpu"
    else:
        auto_choice = "unknown"

    return jsonify({
        "pykokoro_version":
            package_version("pykokoro"),

        "onnxruntime_version":
            package_version("onnxruntime-gpu")
            if cuda_available
            else package_version("onnxruntime"),

        "available_providers":
            providers,

        "modes": {
            "auto":
                bool(providers),

            "cpu":
                cpu_available,

            "cuda":
                cuda_available,
        },

        "auto_preference":
            auto_choice,

        "loaded_engines":
            sorted(
                synthesizers.keys()
            ),
    })


# --------------------------------------------------
# TEXT TO SPEECH
# --------------------------------------------------

@app.route("/tts", methods=["POST"])
def text_to_speech():

    data = (
        request.get_json(
            silent=True
        )
        or {}
    )

    text = str(
        data.get(
            "text",
            ""
        )
    ).strip()

    voice = str(
        data.get(
            "voice",
            "af_sarah"
        )
    ).strip()

    compute_mode = str(
        data.get(
            "compute",
            "auto"
        )
    ).strip().lower()


    if not text:
        return jsonify({
            "error":
                "No text provided."
        }), 400


    if compute_mode not in VALID_COMPUTE_MODES:
        return jsonify({
            "error":
                "Compute must be one of: "
                "auto, cpu, cuda."
        }), 400


    if not compute_mode_available(
        compute_mode
    ):
        return jsonify({
            "error":
                f"Compute mode "
                f"'{compute_mode}' "
                f"is unavailable.",

            "available_providers":
                available_onnx_providers(),
        }), 400


    if len(text) > 3000:
        return jsonify({
            "error":
                "Text chunk is too long."
        }), 400


    try:

        synthesizer = get_synthesizer(
            compute_mode
        )

        rendered = synthesizer.synthesize_text(
            text,
            language="en-us",
            voice=voice,
        )


        # Keep temporary WAV files inside the project
        # instead of Windows' default C: temp directory.
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

            audio_bytes = BytesIO(
                wav_path.read_bytes()
            )


        audio_bytes.seek(0)


        return send_file(
            audio_bytes,
            mimetype="audio/wav",
            download_name=
                "vox_output.wav"
        )


    except Exception as error:

        print(
            "Kokoro error:",
            error
        )

        return jsonify({
            "error":
                str(error)
        }), 500


# --------------------------------------------------
# START SERVER
# --------------------------------------------------

if __name__ == "__main__":

    print()
    print("==============================")
    print("       VOX-9K SERVER")
    print("==============================")
    print()

    providers = available_onnx_providers()

    print(
        "ONNX providers:",
        providers
    )

    print()

    # Warm Auto only.
    # CPU and CUDA engines are loaded lazily if the
    # user explicitly selects them.
    if compute_mode_available("auto"):

        try:
            get_synthesizer(
                "auto"
            )

        except Exception as error:
            print(
                "Auto warmup error:",
                error
            )

    print()
    print("Open:")
    print(
        "http://127.0.0.1:5000"
    )
    print()

    app.run(
        host="127.0.0.1",
        port=5000,
        debug=False,
        threaded=False
    )
