"""
loopback.py — On-demand loopback audio capture for mentor feedback.

Entry point:
    capture_and_analyze(seconds, device, sr) -> dict

Captures audio from a loopback device (e.g. BlackHole) while Ableton plays,
then runs psycho_features.analyze() on the buffer.

Dependencies: sounddevice, numpy, plus whatever psycho_features needs.
"""

import numpy as np
import sounddevice as sd

from .psycho_features import analyze as _analyze

DEFAULT_SR = 44100
DEFAULT_DEVICE_KEYWORD = "BlackHole"


def _find_device(keyword: str) -> int:
    """Return the device index whose name contains `keyword` (case-insensitive)."""
    devices = sd.query_devices()
    kw = keyword.lower()
    for i, d in enumerate(devices):
        if kw in d["name"].lower() and d["max_input_channels"] > 0:
            return i
    names = [d["name"] for d in devices if d["max_input_channels"] > 0]
    raise RuntimeError(
        f"No input device matching '{keyword}' found.\n"
        f"Available input devices: {names}"
    )


def list_input_devices() -> list[dict]:
    """Return all input devices as [{index, name, channels}]."""
    return [
        {"index": i, "name": d["name"], "channels": d["max_input_channels"]}
        for i, d in enumerate(sd.query_devices())
        if d["max_input_channels"] > 0
    ]


def capture_and_analyze(
    seconds: float = 8.0,
    device: str = DEFAULT_DEVICE_KEYWORD,
    sr: int = DEFAULT_SR,
) -> dict:
    """
    Capture `seconds` of audio from a loopback device and return features.

    Parameters
    ----------
    seconds : float
        How many seconds to record. 4 bars at 128 BPM ≈ 7.5s.
    device : str
        Substring of the input device name to use (default: "BlackHole").
    sr : int
        Sample rate (default: 44100).

    Returns
    -------
    dict with keys:
        "device"   : str — name of the device used
        "seconds"  : float — actual duration captured
        "features" : dict — psychoacoustic features
    """
    device_index = _find_device(device)
    device_name = sd.query_devices(device_index)["name"]
    channels = min(2, sd.query_devices(device_index)["max_input_channels"])

    # Blocking record — caller hits play in Ableton before/during this
    frames = int(seconds * sr)
    recording = sd.rec(
        frames,
        samplerate=sr,
        channels=channels,
        dtype="float32",
        device=device_index,
    )
    sd.wait()  # blocks until done

    # recording shape: (samples, channels) → transpose to (channels, samples)
    audio = recording.T
    if audio.shape[0] == 1:
        audio = audio[0]  # squeeze mono to 1D

    features = _analyze(audio, sr)

    return {
        "device": device_name,
        "seconds": round(seconds, 2),
        "features": features,
    }
