from contextlib import asynccontextmanager
from pathlib import Path

import os
import sys

from chunk_cache import ChunkCache

import anyio
from starlette.concurrency import run_in_threadpool
from local_security import LocalOnlyMiddleware
import struct
import threading
import time

import numpy as np
import torch
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field


BASE_DIR = Path(__file__).resolve().parent
CACHE_DIR = BASE_DIR / "cache" / "huggingface"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

os.environ["HF_HOME"] = str(CACHE_DIR)
os.environ["HF_HUB_CACHE"] = str(CACHE_DIR / "hub")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

MODEL_ID = "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice"
HOST = "127.0.0.1"
PORT = 5001
DEFAULT_CHUNK_SIZE = 8
pcm_cache = ChunkCache(BASE_DIR / "temp" / "qwen-audio-cache")

VALID_SPEAKERS = {
    "Vivian",
    "Serena",
    "Uncle_Fu",
    "Dylan",
    "Eric",
    "Ryan",
    "Aiden",
    "Ono_Anna",
    "Sohee",
}

_model = None
_model_lock = threading.Lock()

# Generation state is separate from the model lock.
# This lets a new request cancel an older generation even
# while the older request currently owns the GPU/model lock.
_generation_lock = threading.Lock()
# Bounded tombstones handle Stop arriving before its stream is registered.
_cancelled_requests = {}
_client_sequences = {}


def remember(mapping, key, value):
    mapping[key] = value
    while len(mapping) > 256:
        mapping.pop(next(iter(mapping)))


def request_sequence(request_id):
    try:
        client, session, chunk = request_id.rsplit(":", 2)
        return client, (int(session), int(chunk))
    except ValueError:
        return None, None

_current_generation = {
    "request_id": None,
    "cancel_event": None,
}

_state_lock = threading.Lock()
_state = {
    "status": "starting",
    "error": None,
    "started_at": time.time(),
    "ready_at": None,
}


class StreamRequest(BaseModel):
    export: bool = False
    text: str
    speaker: str = "Ryan"
    language: str = "English"
    chunk_size: int = DEFAULT_CHUNK_SIZE
    request_id: str = Field(default="", max_length=128)


class CancelRequest(BaseModel):
    request_id: str = Field(min_length=1, max_length=128)


def update_state(**changes):
    with _state_lock:
        _state.update(changes)


def begin_generation(request_id, only_if_idle=False):
    """
    Register a new Qwen generation.

    A new request cancels any older generation immediately.
    The older generator notices the event at the next streamed
    audio chunk, exits, and releases the model lock.
    """
    cancel_event = threading.Event()

    with _generation_lock:
        if only_if_idle and _current_generation.get("cancel_event") is not None:
            raise HTTPException(status_code=409, detail="Qwen is busy. Stop reading before exporting.")
        now = time.monotonic()
        for key, expires in list(_cancelled_requests.items()):
            if expires < now:
                del _cancelled_requests[key]
        client, sequence = request_sequence(request_id)
        stale = client is not None and sequence <= _client_sequences.get(client, (-1, -1))
        if request_id in _cancelled_requests or stale:
            cancel_event.set()
            return cancel_event
        if client is not None:
            remember(_client_sequences, client, sequence)
        previous_event = _current_generation.get(
            "cancel_event"
        )

        if previous_event is not None:
            previous_event.set()

        _current_generation["request_id"] = request_id
        _current_generation["cancel_event"] = cancel_event

    return cancel_event


def finish_generation(request_id, cancel_event):
    with _generation_lock:
        if (
            _current_generation.get("request_id") == request_id
            and
            _current_generation.get("cancel_event") is cancel_event
        ):
            _current_generation["request_id"] = None
            _current_generation["cancel_event"] = None


def cancel_generation(request_id=None):
    with _generation_lock:
        if request_id:
            remember(_cancelled_requests, request_id, time.monotonic() + 300)
        current_id = _current_generation.get(
            "request_id"
        )

        cancel_event = _current_generation.get(
            "cancel_event"
        )

        if cancel_event is None:
            return False

        if (
            request_id is not None
            and request_id != current_id
        ):
            return False

        cancel_event.set()
        return True


def load_model():
    global _model

    try:
        update_state(status="loading", error=None)

        print("[QWEN-FAST] Loading Qwen3-TTS 0.6B on CUDA...")

        from faster_qwen3_tts import FasterQwen3TTS

        load_started = time.perf_counter()
        model = FasterQwen3TTS.from_pretrained(
            MODEL_ID,
            device="cuda",
            dtype=torch.bfloat16,
            attn_implementation="sdpa",
        )

        print("[QWEN-FAST] Capturing CUDA graphs...")
        update_state(status="warming", model_load_seconds=time.perf_counter() - load_started)
        warmup_started = time.perf_counter()
        model.warmup(prefill_len=100)

        _model = model

        update_state(
            status="ready",
            ready_at=time.time(),
            graph_warmup_seconds=time.perf_counter() - warmup_started,
        )

        print("[QWEN-FAST] Ready on http://127.0.0.1:5001")

    except Exception as error:
        update_state(
            status="error",
            error=str(error),
        )

        print("[QWEN-FAST] Startup error:", error)


def state_snapshot():
    with _state_lock:
        snapshot = dict(_state)
        if snapshot.get("error"):
            snapshot["error"] = "Qwen startup failed. Check the local sidecar console."

    with _generation_lock:
        active_request_id = _current_generation.get(
            "request_id"
        )

    snapshot.update({
        "service": "vox-9k-qwen",
        "model": MODEL_ID,
        "active_request_id": active_request_id,
        "cuda_available": bool(torch.cuda.is_available()),
        "gpu": (
            torch.cuda.get_device_name(0)
            if torch.cuda.is_available()
            else None
        ),
        "torch_version": torch.__version__,
        "sample_rate": 24000,
        "chunk_size": DEFAULT_CHUNK_SIZE,
    })

    return snapshot


def watch_parent_pipe():
    # EOF means the owning Flask process closed the pipe or died.
    # Process exit releases CUDA resources without depending on atexit.
    from process_lifecycle import wait_for_parent_eof
    wait_for_parent_eof()
    os._exit(0)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if os.environ.get("VOX_PARENT_PIPE") == "1":
        threading.Thread(target=watch_parent_pipe, name="vox-parent-watch", daemon=True).start()
    loader = threading.Thread(
        target=load_model,
        name="qwen-fast-loader",
        daemon=True,
    )
    loader.start()

    yield


app = FastAPI(
    title="VOX-9K Qwen Fast Sidecar",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5000",
        "http://localhost:5000",
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
    expose_headers=["X-VOX-PCM-Protocol"],
)
app.add_middleware(LocalOnlyMiddleware, port=PORT)


@app.get("/health")
def health():
    return state_snapshot()


@app.post("/cancel")
def cancel(request_data: CancelRequest):
    request_id = request_data.request_id

    cancelled = cancel_generation(
        request_id=request_id
    )

    return {
        "cancelled": cancelled,
        "request_id": request_id,
    }


@app.post("/stream")
def stream(request_data: StreamRequest):
    text = request_data.text.strip()
    speaker = request_data.speaker.strip()
    language = request_data.language.strip() or "English"
    chunk_size = int(request_data.chunk_size)

    request_id = (
        request_data.request_id.strip()
        or f"request-{time.time_ns()}"
    )

    if not text:
        raise HTTPException(
            status_code=400,
            detail="No text provided.",
        )

    if len(text) > 3000:
        raise HTTPException(
            status_code=400,
            detail="Text chunk is too long.",
        )

    if speaker not in VALID_SPEAKERS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported Qwen speaker: {speaker}",
        )

    if language not in {"Auto", "English", "Chinese", "Japanese", "Korean", "German", "French", "Russian", "Portuguese", "Spanish", "Italian"}:
        raise HTTPException(status_code=400, detail="Unsupported Qwen language.")

    if chunk_size < 2 or chunk_size > 24:
        raise HTTPException(
            status_code=400,
            detail="chunk_size must be between 2 and 24.",
        )

    if _state.get("status") != "ready" or _model is None:
        detail = "Qwen fast engine is still warming up."

        if _state.get("status") == "error":
            detail = "Qwen fast engine failed to start. Check the local sidecar console."

        raise HTTPException(
            status_code=503,
            detail=detail,
        )

    cancel_event = begin_generation(
        request_id, only_if_idle=request_data.export
    )

    def framed_audio():
        frame_index = 0
        sample_rate = 24000
        model_generator = None
        cache_context = pcm_cache.record(text, speaker)
        cache_record = None
        try:
            cache_record = cache_context.__enter__()
        except OSError:
            pass

        try:
            while not _model_lock.acquire(timeout=0.1):
                if cancel_event.is_set():
                    return
            try:
                try:

                    # This request may have been superseded while
                    # waiting for the previous generation to release
                    # the model lock.
                    if cancel_event.is_set():
                        return

                    model_generator = (
                        _model.generate_custom_voice_streaming(
                            text=text,
                            speaker=speaker,
                            language=language,
                            chunk_size=chunk_size,
                        )
                    )

                    while not cancel_event.is_set():
                        try:
                            audio_chunk, sample_rate, timing = next(model_generator)
                        except StopIteration:
                            break

                        if cancel_event.is_set():
                            print(
                                "[QWEN-FAST] Cancelled:",
                                request_id,
                            )
                            break

                        pcm = np.asarray(
                            audio_chunk,
                            dtype="<f4",
                        ).reshape(-1)

                        if int(sample_rate) != 24000 or not pcm.size or not np.isfinite(pcm).all():
                            raise ValueError("Invalid generated PCM format")
                        payload = pcm.tobytes()
                        if cache_record is not None:
                            cache_record.write(payload)

                        # Frame format, little endian:
                        # uint32 payload_bytes
                        # uint32 sample_rate
                        # uint32 frame_index
                        # uint32 flags, 0=data, 1=end
                        header = struct.pack(
                            "<IIII",
                            len(payload),
                            int(sample_rate),
                            frame_index,
                            0,
                        )

                        yield header + payload
                        frame_index += 1

                    # Only send a normal end frame when the request
                    # was not cancelled.
                    if not cancel_event.is_set():
                        if cache_record is not None:
                            cache_record.complete = True
                        yield struct.pack(
                            "<IIII",
                            0,
                            int(sample_rate),
                            frame_index,
                            1,
                        )
                finally:
                    if model_generator is not None:
                        close_method = getattr(model_generator, "close", None)
                        if callable(close_method):
                            close_method()
            finally:
                finish_generation(request_id, cancel_event)
                _model_lock.release()

        except GeneratorExit:
            cancel_event.set()
            return

        except Exception as error:
            print(
                "[QWEN-FAST] Stream error:",
                error
            )

            if not cancel_event.is_set():
                message = "Qwen generation failed. Check the local sidecar console.".encode(
                    "utf-8",
                    errors="replace",
                )

                yield struct.pack(
                    "<IIII",
                    len(message),
                    int(sample_rate),
                    frame_index,
                    2,
                ) + message

        finally:
            if cache_record is not None:
                try:cache_context.__exit__(None, None, None)
                except OSError:pass
            cancel_event.set()

            finish_generation(
                request_id,
                cancel_event
            )

    async def managed_audio():
        iterator = framed_audio()
        sentinel = object()
        try:
            while True:
                part = await run_in_threadpool(next, iterator, sentinel)
                if part is sentinel:
                    break
                yield part
        finally:
            cancel_event.set()
            # Wait for a synchronous inference step before closing its generator.
            with anyio.CancelScope(shield=True):
                await run_in_threadpool(iterator.close)
            finish_generation(request_id, cancel_event)

    return StreamingResponse(
        managed_audio(),
        media_type="application/octet-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "X-VOX-PCM-Protocol": "f32le-framed-v1",
        },
    )


if __name__ == "__main__":
    print()
    print("==============================")
    print("   VOX-9K QWEN FAST SIDECAR")
    print("==============================")
    print()

    uvicorn.run(
        app,
        host=HOST,
        port=PORT,
        log_level="warning",
    )
