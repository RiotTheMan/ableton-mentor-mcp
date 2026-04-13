# Ableton Mentor — AI Sound Engineering Guide

**AbletonMCP is a sound engineering mentor for Ableton Live.** It connects your session to Claude AI—not to automate, but to analyze, teach, and give you actionable feedback on your mixing decisions.

Instead of guessing why your track sounds dark or mono, the mentor tells you *exactly* which devices are causing it, *why*, and *how to fix it*.

> **Example:** You have a stem bus with reverb + echo + EQ. The track sounds dark despite Ping Pong echo. The mentor tells you:
> - The EQ notch at 3 kHz removes the presence region where stereo imaging is strongest
> - The echo's LP filter at 5 kHz keeps the delays muffled, so Ping Pong stereo can't breathe
> - **The fix:** Raise the 3 kHz notch, lift the echo LP toward 8–10 kHz → delays instantly feel wider

That's mentor-level feedback, not a button press.

---

## About This Fork

**Original project:** [AbletonMCP](https://github.com/ahujasid/ableton-mcp) by [Siddharth](https://x.com/sidahuj)

**This fork adds:**
- **Holistic mentor data layer** — automation envelopes, routing, mixer levels, warp modes, loop regions, scene names
- **On-demand psychoacoustic analysis** — auto-seek to bar, auto-play, loopback capture, ~17 audio metrics per snippet
- **Mentor-first positioning** — observe → analyze → teach (not automation)
- **Expanded session awareness** — return tracks, sends, automation flags, input/output routing
- **Clip-level detail** — gain, pitch, warp mode, loop region, automation per clip

**Maintained by:** [Emile Harel](https://github.com/RiotTheMan)

This is an actively maintained fork focused on teaching mixing through parameter-to-perception feedback. The mentor helps you understand *why* your mixing decisions sound the way they do.

---

## What the Mentor Does

### 1. **Listens to Your Session**
Pulls complete, holistic data:
- **Track routing & mixing**: Volume, pan, sends, input/output routing, automation flags
- **Clip details**: Warp mode, loop regions, automation envelopes, gain/pitch
- **Device chain**: Every parameter on every device (including nested racks)
- **Structure**: Scenes, return tracks, master processing

### 2. **Analyzes Your Audio**
Captures live playback (no manual export needed) and measures ~17 psychoacoustic features:
- **Loudness**: LUFS (streaming target), true peak (clipping risk)
- **Tone**: Spectral centroid (dark ↔ bright), frequency distribution
- **Stereo**: Width, imaging clarity
- **Transients**: Energy distribution, crest factor

### 3. **Connects the Dots**
Reasons about your mixing decisions:
- *"Your bass loop is at -3.1 dB with Kickstart 2 at 96% sidechain. Why does the mix still feel dynamic?"*
- *"Your return tracks have reverb + delay but no sends. Those are idle. Why?"*
- *"True peak is at -0.99 dBTP. Where is the clipping coming from? The Utility +10dB on the stem bus."*

### 4. **Teaches You**
Explains the *why* behind each observation, so you learn how your parameter choices affect the sound.

---

## Typical Mentor Workflow

```
1. Ask: "What's in my session?"
   → get_session_info → 13 audio tracks, 2 return tracks, explicit routing/sends
   
2. Ask: "Analyze bars 9–12"
   → analyze_snippet(bar=9, bars=4) → LUFS -13.8, stereo_width 0.08, 95% energy below 250Hz
   
3. Flag: "Why is it so mono?"
   → get_track_info(track=8) → reveal EQ notch at 3 kHz, Echo LP at 5 kHz
   
4. Ask: "How do I widen this?"
   → Mentor explains: raise the notch, lift the echo filter → feedback loop with real-time testing
```

---

## Installation

### Prerequisites
- **Ableton Live 10+**
- **Python 3.8+**
- **uv** package manager: `brew install uv` (macOS) or [install here](https://docs.astral.sh/uv/getting-started/installation/)
- **Optional**: BlackHole loopback device for audio analysis (macOS) or [VB-Audio Virtual Cable](https://vb-audio.com/Cable/) (Windows/Linux)

### Step 1: Install the Ableton Remote Script

Download `AbletonMCP_Remote_Script/__init__.py` and copy it to Ableton's MIDI Remote Scripts folder:

**macOS:**
- Applications → Right-click Ableton Live → Show Package Contents → `Contents/App-Resources/MIDI Remote Scripts/AbletonMCP/`
- *Alternate:* `~/Library/Preferences/Ableton/Live XX/User Remote Scripts/AbletonMCP/`

**Windows:**
- `C:\Users\[Username]\AppData\Roaming\Ableton\Live X.X.X\Preferences\User Remote Scripts\AbletonMCP\`
- *Alternate:* `C:\Program Files\Ableton\Live XX\Resources\MIDI Remote Scripts\AbletonMCP\`

Then:
1. Restart Ableton Live
2. Go to Settings → Link, Tempo & MIDI → Control Surface → Select **AbletonMCP**
3. Set Input and Output to **None**

### Step 2: Connect Claude Desktop

Edit `~/.claude/settings.json` (or create it):

```json
{
  "mcpServers": {
    "ableton_mcp": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "--directory", "/path/to/ableton-mentor-mcp", "ableton-mcp"]
    }
  }
}
```

Replace `/path/to/ableton-mentor-mcp` with your clone location.

Restart Claude Desktop. You'll now see Ableton tools in the UI.

### Step 3 (Optional): Set Up Audio Analysis

For live psychoacoustic analysis (`analyze_snippet`), install a loopback device:

**macOS:** [BlackHole 2ch](https://existential.audio/blackhole/) (free, straightforward)
- After install: Ableton → Settings → Audio/MIDI → Output → BlackHole 2ch

**Windows/Linux:** [VB-Audio Virtual Cable](https://vb-audio.com/Cable/)

---

## Core Tools

### Session Analysis
- `get_session_info` — Full session snapshot: tracks, routing, sends, automation, scenes
- `get_track_info(track_index)` — Deep dive: clips, automation envelopes, warp, loop, devices
- `get_device_parameters(track_index)` — All parameters on every device (nested racks included)

### Audio Analysis
- `analyze_snippet(bar=1, bars=4)` — Seek to bar, auto-play, capture, return psycho features. No manual playback.
- `analyze_render(export_folder)` — Render current selection, watch export folder, analyze the file
- `list_audio_devices()` — Find loopback device names

### Session Control
- `start_playback`, `stop_playback` — Transport
- `set_song_position(beat)` — Seek to bar (used by analyze_snippet)
- `fire_clip(track, slot)`, `stop_clip(track, slot)` — Clip control

### Creation & Editing
- `create_midi_track`, `create_clip`, `add_notes_to_clip` — Build MIDI
- `set_track_name`, `set_track_color` — Organize
- `load_instrument_or_effect`, `load_drum_kit` — Browse Ableton's library
- `set_tempo` — Adjust BPM

---

## Example Mentor Sessions

### Session 1: Diagnosing a Dark Mix
```
You:     "Why does my mix sound so dark?"
Mentor:  [Captures 4 bars] LUFS -13.8, spectral centroid 1607 Hz (very dark)
         [Checks devices] EQ8 has high-shelf cut at 4.5 kHz, LP at 11.6 kHz
         
You:     "Can I fix it?"
Mentor:  Lift the high-shelf (or remove it). That will add air above 4 kHz.
         Your percussion (hats, rides) have zero EQ — they're relying on raw
         recordings which might be dull to begin with. Try a presence peak at 5 kHz.
```

### Session 2: Clipping Investigation
```
You:     "My mix is hitting -0.99 dBTP. Where's the clip?"
Mentor:  [Gets device params] Track 8 (stem bus) has Utility at +10 dB.
         The stem routes into this bus, hits +10 dB, then reverb + echo.
         The Utility is your culprit.
         
You:     "Should I reduce it?"
Mentor:  Yes, but first check: why +10 dB? If you need the gain, raise the track
         fader instead (more transparent). If you don't, just pull it back to 0 dB.
```

### Session 3: Stereo Width Mystery
```
You:     "I have Ping Pong echo at 70% wet, but the mix is still mono."
Mentor:  [Analyzes] stereo_width 0.08 (mono), EQ has notch at 3 kHz (resonance 2.11).
         The presence region (3–5 kHz) is where our ears perceive stereo imaging.
         By cutting 3 kHz, you're removing the cues that make Ping Pong sound wide.
         
You:     "How do I fix it?"
Mentor:  Disable or raise the 3 kHz notch. Also, your echo's LP filter is at 5 kHz,
         which keeps the delays dull. Lift it to 8–10 kHz so delays have air.
         Once you do that, the Ping Pong will instantly feel wider.
```

---

## How It Works (Technical)

### Architecture
1. **Ableton Remote Script** (runs inside Ableton on port 9877)
   - Exposes Live's Python API (tracks, devices, parameters, clips)
   - Receives JSON commands, executes them, returns results
   
2. **MCP Server** (stdio process managed by Claude Desktop)
   - Connects to the Remote Script over TCP
   - Implements MCP tools (get_session_info, analyze_snippet, etc.)
   - Calls Claude's reasoning engine for mentoring feedback

3. **Psychoacoustic Analysis** (`MCP_Server/loopback.py`, `psycho_features.py`)
   - Captures loopback audio (BlackHole, Virtual Cable, etc.)
   - Computes ~17 features: LUFS, LRA, true peak, spectral centroid, stereo width, etc.
   - Returns human-readable metrics (e.g., "stereo_width: 0.08 = mono")

### Data Scrubbing (Token Cost Philosophy)
Every field in the JSON is intentional:
- Default volumes (0.0 dB) are omitted
- Center pans are omitted  
- Idle sends (0.0) are omitted
- Flat automation envelopes are omitted
- Master fields only appear if non-default

This keeps the mentor's context tight while preserving all actionable information.

---

## Limitations

- **Audio analysis requires loopback device** — BlackHole (macOS), VB-Audio Cable (Windows)
- **Render analysis requires macOS Accessibility permissions** — for AppleScript export trigger
- **VST internals are opaque** — The mentor sees generic parameters (gain, mix, etc.) but not proprietary sidechain routing, internal state, etc.
- **Automation breakpoints aren't visible** — Only envelope min/max ranges (future: add breakpoint sampling)
- **Large sessions may need chunking** — Mentor can analyze 20+ tracks, but breaking into smaller questions helps

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| "Connection closed" | Restart Ableton Live. The Remote Script caches Python bytecode (`__pycache__`). |
| `analyze_snippet` not found | Restart Claude Desktop after installing. MCP tools load at startup. |
| No audio captured | Verify loopback device is routed to Ableton Output. Run `list_audio_devices()` to see available devices. |
| Timeout on large sessions | Break the request: Get session info first, then drill into flagged tracks one at a time. |

---

## Contributing

This is an active research project. Contributions welcome:
- New psychoacoustic features (contact psychoacoustics research)
- Better device parameter documentation
- Mentor prompts that teach mixing theory
- Integration examples

---

## What This Is Not

❌ Ableton control panel / remote  
❌ Automatic mixing / mastering plugin  
❌ Real-time DSP or audio processing  
❌ Replacement for learning mixing fundamentals  

**What it is:**
✅ A teacher that knows your session inside and out  
✅ Feedback loop for your mixing decisions  
✅ Bridge between parametric thinking (EQ @ 3 kHz) and perceptual thinking (sounds dark)  

---

## Thanks

- Built with [Claude 4.6 Sonnet](https://claude.ai)
- Audio analysis via [librosa](https://librosa.org/) + [pyloudnorm](https://github.com/csteinmetz1/pyloudnorm)
- Psychoacoustic features from research in music information retrieval
- Special thanks to the sound engineers who've tested and refined this mentor

---

**Made for people who mix with intention.**
