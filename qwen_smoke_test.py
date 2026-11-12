from pathlib import Path
import os

BASE_DIR = Path(__file__).resolve().parent
HF_HOME_DIR = BASE_DIR / "cache" / "huggingface"
HF_HUB_DIR = HF_HOME_DIR / "hub"

HF_HUB_DIR.mkdir(
    parents=True,
    exist_ok=True
)

# Keep every Hugging Face / Transformers cache consumer
# pointed at the same canonical snapshot store.
os.environ["HF_HOME"] = str(HF_HOME_DIR)
os.environ["HF_HUB_CACHE"] = str(HF_HUB_DIR)
os.environ["TRANSFORMERS_CACHE"] = str(HF_HUB_DIR)

import torch
import soundfile as sf
from qwen_tts import Qwen3TTSModel

MODEL_ID = (
    "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice"
)

print("CUDA available:", torch.cuda.is_available())

device = (
    "cuda:0"
    if torch.cuda.is_available()
    else "cpu"
)

dtype = (
    torch.bfloat16
    if device.startswith("cuda")
    else torch.float32
)

print("Loading:", MODEL_ID)
print("Device:", device)
print("HF home:", HF_HOME_DIR)
print("HF hub cache:", HF_HUB_DIR)

model = Qwen3TTSModel.from_pretrained(
    MODEL_ID,
    device_map=device,
    dtype=dtype,
    attn_implementation="sdpa",
    cache_dir=HF_HUB_DIR,
)

print("Generating test speech...")

wavs, sr = model.generate_custom_voice(
    text=(
        "VOX-9K is now testing Qwen three TTS. "
        "This voice should sound natural, relaxed, "
        "and conversational."
    ),
    language="English",
    speaker="Ryan",
)

output = BASE_DIR / "qwen_test.wav"

sf.write(
    str(output),
    wavs[0],
    sr,
)

print("Created:", output)
