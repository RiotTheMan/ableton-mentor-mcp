"""
psycho_features.py — Psychoacoustic feature extractor for mentor feedback.

Entry point:
    analyze(audio: np.ndarray, sr: int) -> dict[str, float | str]

Dependencies: pyloudnorm, librosa, numpy
No hardware access; pure offline analysis.
"""

import numpy as np

try:
    import pyloudnorm as pyln
    _HAS_PYLN = True
except ImportError:
    _HAS_PYLN = False

try:
    import librosa
    _HAS_LIBROSA = True
except ImportError:
    _HAS_LIBROSA = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_mono(audio: np.ndarray) -> np.ndarray:
    """Collapse stereo/multi-channel to mono."""
    if audio.ndim == 1:
        return audio
    return audio.mean(axis=0)


def _safe(fn, fallback=None):
    try:
        return fn()
    except Exception:
        return fallback


def _r(v, n=2):
    """Round a scalar to n decimal places, returning a plain Python float."""
    if v is None:
        return None
    return round(float(v), n)


# ---------------------------------------------------------------------------
# Feature groups
# ---------------------------------------------------------------------------

def _loudness_dynamics(audio: np.ndarray, sr: int) -> dict:
    mono = _to_mono(audio)
    out = {}

    if _HAS_PYLN:
        meter = pyln.Meter(sr)
        # BS.1770-4 integrated loudness
        lufs = _safe(lambda: meter.integrated_loudness(mono))
        out["lufs_integrated"] = _r(lufs) if lufs is not None and np.isfinite(lufs) else None

        # Loudness Range
        lra = _safe(lambda: pyln.loudness_range(mono, sr))
        out["lra"] = _r(lra) if lra is not None and np.isfinite(lra) else None

        # True peak (dBTP)
        true_peak_linear = _safe(lambda: np.max(np.abs(mono)))
        if true_peak_linear is not None and true_peak_linear > 0:
            out["true_peak_dbtp"] = _r(20 * np.log10(true_peak_linear))
        else:
            out["true_peak_dbtp"] = None

    # RMS level
    rms = _safe(lambda: np.sqrt(np.mean(mono ** 2)))
    if rms is not None and rms > 0:
        out["rms_db"] = _r(20 * np.log10(rms))
    else:
        out["rms_db"] = None

    # Crest factor: peak / RMS
    peak = _safe(lambda: np.max(np.abs(mono)))
    if rms is not None and rms > 0 and peak is not None:
        out["crest_factor_db"] = _r(20 * np.log10(peak / rms))
    else:
        out["crest_factor_db"] = None

    return out


def _spectral_features(audio: np.ndarray, sr: int) -> dict:
    if not _HAS_LIBROSA:
        return {}

    mono = _to_mono(audio)
    out = {}

    S = _safe(lambda: np.abs(librosa.stft(mono)))
    if S is None:
        return out

    # Spectral centroid (brightness)
    sc = _safe(lambda: np.mean(librosa.feature.spectral_centroid(S=S, sr=sr)))
    out["spectral_centroid_hz"] = _r(sc, 1) if sc is not None else None

    # Spectral bandwidth
    bw = _safe(lambda: np.mean(librosa.feature.spectral_bandwidth(S=S, sr=sr)))
    out["spectral_bandwidth_hz"] = _r(bw, 1) if bw is not None else None

    # Spectral rolloff (85%)
    rolloff = _safe(lambda: np.mean(librosa.feature.spectral_rolloff(S=S, sr=sr, roll_percent=0.85)))
    out["spectral_rolloff_hz"] = _r(rolloff, 1) if rolloff is not None else None

    # Spectral flatness (0 = tonal, 1 = noise-like)
    flatness = _safe(lambda: np.mean(librosa.feature.spectral_flatness(S=S)))
    out["spectral_flatness"] = _r(flatness, 4) if flatness is not None else None

    # Zero crossing rate (percussiveness proxy)
    zcr = _safe(lambda: np.mean(librosa.feature.zero_crossing_rate(mono)))
    out["zero_crossing_rate"] = _r(zcr, 4) if zcr is not None else None

    return out


def _energy_bands(audio: np.ndarray, sr: int) -> dict:
    """Relative energy in four broad bands (sub, low-mid, high-mid, air)."""
    if not _HAS_LIBROSA:
        return {}

    mono = _to_mono(audio)
    bands = {
        "energy_sub_60hz": (20, 60),
        "energy_low_250hz": (60, 250),
        "energy_mid_4khz": (250, 4000),
        "energy_hi_20khz": (4000, 20000),
    }

    fft = np.fft.rfft(mono)
    freqs = np.fft.rfftfreq(len(mono), d=1.0 / sr)
    power = np.abs(fft) ** 2
    total_power = np.sum(power)

    out = {}
    if total_power == 0:
        for k in bands:
            out[k] = None
        return out

    for name, (lo, hi) in bands.items():
        mask = (freqs >= lo) & (freqs < hi)
        band_energy = np.sum(power[mask]) / total_power
        out[name] = _r(band_energy, 4)

    return out


def _temporal_features(audio: np.ndarray, sr: int) -> dict:
    if not _HAS_LIBROSA:
        return {}

    mono = _to_mono(audio)
    out = {}

    # Tempo estimate (BPM)
    tempo = _safe(lambda: librosa.beat.beat_track(y=mono, sr=sr)[0])
    if tempo is not None:
        # librosa >= 0.10 may return array
        t = float(tempo) if np.isscalar(tempo) else float(tempo.item())
        out["tempo_bpm"] = _r(t, 1)
    else:
        out["tempo_bpm"] = None

    # Duration
    out["duration_s"] = _r(len(mono) / sr, 3)

    return out


def _stereo_features(audio: np.ndarray, sr: int) -> dict:
    if audio.ndim < 2 or audio.shape[0] < 2:
        return {"stereo_width": None}

    L, R = audio[0], audio[1]
    mid = (L + R) / 2
    side = (L - R) / 2

    mid_rms = np.sqrt(np.mean(mid ** 2))
    side_rms = np.sqrt(np.mean(side ** 2))

    if mid_rms == 0:
        return {"stereo_width": None}

    width = side_rms / mid_rms
    return {"stereo_width": _r(width, 4)}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze(audio: np.ndarray, sr: int) -> dict:
    """
    Compute psychoacoustic features for a rendered audio file.

    Parameters
    ----------
    audio : np.ndarray
        Shape (samples,) for mono or (channels, samples) for multi-channel.
        Float32 or float64, range [-1, 1].
    sr : int
        Sample rate in Hz (e.g. 44100, 48000).

    Returns
    -------
    dict
        Flat dict of feature_name -> float (or None if unavailable).
        All values are JSON-serializable.
    """
    result = {}
    result.update(_loudness_dynamics(audio, sr))
    result.update(_spectral_features(audio, sr))
    result.update(_energy_bands(audio, sr))
    result.update(_temporal_features(audio, sr))
    result.update(_stereo_features(audio, sr))

    # Strip None values — absent keys are cheaper than null tokens
    return {k: v for k, v in result.items() if v is not None}


def compare(features_a: dict, features_b: dict) -> dict:
    """
    Compare two feature dicts and return per-feature deltas.

    Returns dict of {feature_name: {"a": val, "b": val, "delta": b - a}}.
    Only includes features present in both dicts.
    """
    result = {}
    for key in features_a:
        if key not in features_b:
            continue
        a_val = features_a[key]
        b_val = features_b[key]
        if isinstance(a_val, (int, float)) and isinstance(b_val, (int, float)):
            result[key] = {
                "a": _r(a_val, 2),
                "b": _r(b_val, 2),
                "delta": _r(b_val - a_val, 2),
            }
    return result


def masking_report(
    audio_tracks: list,
    sr: int,
) -> dict:
    """
    Detect frequency masking between pairs of tracks.

    Parameters
    ----------
    audio_tracks : list of (np.ndarray, str)
        Each element is (audio_array, track_name). Audio is mono or stereo.
    sr : int
        Sample rate.

    Returns
    -------
    dict with "conflicts" list — pairs of tracks that share significant
    energy in the same frequency band.
    """
    if not _HAS_LIBROSA:
        return {"error": "librosa not available", "conflicts": []}

    bands = {
        "sub": (20, 60),
        "low": (60, 250),
        "mid": (250, 4000),
        "high": (4000, 20000),
    }

    # Compute per-band energy for each track
    track_energies = []
    for audio, name in audio_tracks:
        mono = _to_mono(audio)
        fft = np.fft.rfft(mono)
        freqs = np.fft.rfftfreq(len(mono), d=1.0 / sr)
        power = np.abs(fft) ** 2
        total = np.sum(power)
        if total == 0:
            track_energies.append((name, {b: 0.0 for b in bands}))
            continue
        energies = {}
        for band_name, (lo, hi) in bands.items():
            mask = (freqs >= lo) & (freqs < hi)
            energies[band_name] = float(np.sum(power[mask]) / total)
        track_energies.append((name, energies))

    # Find pairs with significant overlap in the same band
    conflicts = []
    threshold = 0.10  # both tracks must have >= 10% energy in the band
    for i in range(len(track_energies)):
        for j in range(i + 1, len(track_energies)):
            name_a, en_a = track_energies[i]
            name_b, en_b = track_energies[j]
            for band_name in bands:
                a_pct = en_a[band_name]
                b_pct = en_b[band_name]
                if a_pct >= threshold and b_pct >= threshold:
                    overlap = min(a_pct, b_pct) / max(a_pct, b_pct) * 100
                    conflicts.append({
                        "tracks": [name_a, name_b],
                        "band": band_name,
                        "energy_a_pct": _r(a_pct * 100, 1),
                        "energy_b_pct": _r(b_pct * 100, 1),
                        "overlap_score": _r(overlap, 1),
                    })

    # Sort by overlap score descending
    conflicts.sort(key=lambda c: c["overlap_score"], reverse=True)

    return {"conflicts": conflicts}


# ---------------------------------------------------------------------------
# CLI smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    if not _HAS_LIBROSA:
        print("ERROR: librosa not installed. Run: pip install librosa pyloudnorm")
        sys.exit(1)

    # Generate 5s of white noise as a sanity check
    rng = np.random.default_rng(42)
    sr = 44100
    audio = rng.uniform(-0.5, 0.5, sr * 5).astype(np.float32)
    features = analyze(audio, sr)
    for k, v in sorted(features.items()):
        print(f"  {k:<30} {v}")
