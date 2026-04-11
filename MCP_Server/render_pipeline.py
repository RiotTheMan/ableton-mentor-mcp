"""
render_pipeline.py — Trigger Ableton render and analyze the output.

Flow:
  1. trigger_render()        AppleScript: Cmd+Shift+R, optional Return to accept dialog
  2. wait_for_render()       Poll export folder for a new audio file (wav/aiff/mp3/flac)
  3. load_audio()            librosa.load() → (np.ndarray, sr)
  4. render_and_analyze()    1 + 2 + 3 + psycho_features.analyze()

Default export folder: ~/Music/Ableton/Exports
(matches Ableton's out-of-the-box default on macOS)
"""

import os
import subprocess
import time
from pathlib import Path
from typing import Optional

import numpy as np

from .psycho_features import analyze as _analyze_audio

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_EXPORT_FOLDER = Path.home() / "Music" / "Ableton" / "Exports"
AUDIO_EXTENSIONS = {".wav", ".aiff", ".aif", ".mp3", ".flac", ".ogg"}
POLL_INTERVAL = 0.5   # seconds between folder checks
MIN_FILE_AGE  = 1.0   # seconds file must be stable (not still being written)


# ---------------------------------------------------------------------------
# Step 1: Trigger Ableton export
# ---------------------------------------------------------------------------

_APPLESCRIPT_TRIGGER = """
tell application "System Events"
    -- Activate the first Ableton Live process found
    set ablProcs to (every process whose name starts with "Ableton Live")
    if length of ablProcs is 0 then
        error "Ableton Live is not running"
    end if
    set frontmost of item 1 of ablProcs to true
end tell
delay 0.4
tell application "System Events"
    -- Cmd+Shift+R  →  Export Audio/Video dialog
    key code 15 using {{command down, shift down}}
end tell
delay {dialog_delay}
tell application "System Events"
    -- Return  →  accept dialog with current settings
    key code 36
end tell
"""

_APPLESCRIPT_TRIGGER_NO_ACCEPT = """
tell application "System Events"
    set ablProcs to (every process whose name starts with "Ableton Live")
    if length of ablProcs is 0 then
        error "Ableton Live is not running"
    end if
    set frontmost of item 1 of ablProcs to true
end tell
delay 0.4
tell application "System Events"
    key code 15 using {{command down, shift down}}
end tell
"""


def trigger_render(accept_dialog: bool = True, dialog_delay: float = 2.0) -> None:
    """
    Send Cmd+Shift+R to Ableton to open the Export Audio/Video dialog.

    Parameters
    ----------
    accept_dialog : bool
        If True, press Return after `dialog_delay` seconds to accept with
        whatever settings are currently in the dialog (uses the last-used
        export path and format). If False, just open the dialog and let the
        user interact.
    dialog_delay : float
        Seconds to wait for the Export dialog to appear before pressing Return.
        Increase if Ableton is slow to open the dialog on your machine.

    Raises
    ------
    RuntimeError
        If the AppleScript fails (e.g. Ableton not running, accessibility
        permissions not granted).
    """
    if accept_dialog:
        script = _APPLESCRIPT_TRIGGER.format(dialog_delay=dialog_delay)
    else:
        script = _APPLESCRIPT_TRIGGER_NO_ACCEPT

    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"AppleScript failed (exit {result.returncode}): {result.stderr.strip()}"
        )


# ---------------------------------------------------------------------------
# Step 2: Watch for the rendered file
# ---------------------------------------------------------------------------

def _snapshot(folder: Path) -> dict[str, float]:
    """Return {filepath: mtime} for all audio files in folder (non-recursive)."""
    snap = {}
    try:
        for entry in folder.iterdir():
            if entry.suffix.lower() in AUDIO_EXTENSIONS:
                try:
                    snap[str(entry)] = entry.stat().st_mtime
                except OSError:
                    pass
    except OSError:
        pass
    return snap


def wait_for_render(
    folder: Path = DEFAULT_EXPORT_FOLDER,
    timeout: float = 120.0,
    min_age: float = MIN_FILE_AGE,
) -> Path:
    """
    Poll `folder` for a new or recently modified audio file.

    Returns the path of the first stable new file found.

    Parameters
    ----------
    folder : Path
        Folder to watch. Defaults to ~/Music/Ableton/Exports.
    timeout : float
        Maximum seconds to wait before raising TimeoutError.
    min_age : float
        A file must not have been modified within this many seconds to be
        considered "done writing". Prevents returning a half-written file.

    Raises
    ------
    TimeoutError
        If no new file appears within `timeout` seconds.
    FileNotFoundError
        If `folder` does not exist.
    """
    folder = Path(folder)
    if not folder.exists():
        raise FileNotFoundError(f"Export folder not found: {folder}")

    before = _snapshot(folder)
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        time.sleep(POLL_INTERVAL)
        after = _snapshot(folder)

        # Find files that are new or modified since we started watching
        new_files = []
        for path, mtime in after.items():
            if path not in before or mtime > before[path]:
                new_files.append((path, mtime))

        if new_files:
            # Wait for all candidates to stop being written
            now = time.time()
            stable = [p for p, mt in new_files if (now - mt) >= min_age]
            if stable:
                # Return the most recently modified stable file
                stable.sort(key=lambda p: after[p], reverse=True)
                return Path(stable[0])

    raise TimeoutError(
        f"No new audio file appeared in {folder} within {timeout}s"
    )


# ---------------------------------------------------------------------------
# Step 3: Load audio
# ---------------------------------------------------------------------------

def load_audio(path: Path, sr: Optional[int] = None) -> tuple[np.ndarray, int]:
    """
    Load an audio file with librosa.

    Parameters
    ----------
    path : Path
        File to load.
    sr : int or None
        Target sample rate. None preserves the file's native rate.

    Returns
    -------
    (audio, sr) where audio is float32 shape (samples,) for mono or
    (channels, samples) for stereo.
    """
    import librosa
    import soundfile as sf

    # Use soundfile first (preserves stereo), fall back to librosa mono
    try:
        audio, file_sr = sf.read(str(path), dtype="float32", always_2d=True)
        # soundfile returns (samples, channels) — transpose to (channels, samples)
        audio = audio.T
        if sr and sr != file_sr:
            import librosa.core
            audio = np.stack(
                [librosa.resample(ch, orig_sr=file_sr, target_sr=sr) for ch in audio]
            )
            file_sr = sr
        # Squeeze mono to 1D
        if audio.shape[0] == 1:
            audio = audio[0]
        return audio, file_sr
    except Exception:
        # librosa fallback (always mono)
        audio, file_sr = librosa.load(str(path), sr=sr, mono=True)
        return audio, file_sr


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def render_and_analyze(
    export_folder: Path = DEFAULT_EXPORT_FOLDER,
    timeout: float = 120.0,
    trigger: bool = True,
    accept_dialog: bool = True,
    dialog_delay: float = 2.0,
) -> dict:
    """
    Full pipeline: optionally trigger Ableton export, wait for the file,
    load it, and return psychoacoustic features.

    Parameters
    ----------
    export_folder : Path
        Folder Ableton writes exports to.
    timeout : float
        Max seconds to wait for the exported file (render time varies).
    trigger : bool
        If True, send Cmd+Shift+R to Ableton before watching the folder.
        Set False if you've already started the export manually.
    accept_dialog : bool
        Passed to trigger_render(). Ignored when trigger=False.
    dialog_delay : float
        Seconds to wait before pressing Return in the export dialog.

    Returns
    -------
    dict with keys:
        "file"     : str — absolute path of the rendered file
        "features" : dict — psychoacoustic features from psycho_features.analyze()
    """
    export_folder = Path(export_folder)

    if trigger:
        trigger_render(accept_dialog=accept_dialog, dialog_delay=dialog_delay)

    rendered_file = wait_for_render(folder=export_folder, timeout=timeout)
    audio, sr = load_audio(rendered_file)
    features = _analyze_audio(audio, sr)

    return {
        "file": str(rendered_file),
        "features": features,
    }


# ---------------------------------------------------------------------------
# CLI smoke test (no Ableton needed — analyzes an existing file)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python -m MCP_Server.render_pipeline <audio_file>")
        print("       (analyzes an existing file without triggering Ableton)")
        sys.exit(1)

    path = Path(sys.argv[1])
    if not path.exists():
        print(f"File not found: {path}")
        sys.exit(1)

    audio, sr = load_audio(path)
    features = _analyze_audio(audio, sr)
    print(f"File   : {path}")
    print(f"Shape  : {audio.shape}  sr={sr}")
    print()
    for k, v in sorted(features.items()):
        print(f"  {k:<30} {v}")
