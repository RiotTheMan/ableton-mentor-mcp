# ableton_mcp_server.py
from mcp.server.fastmcp import FastMCP, Context
import asyncio
import socket
import json
import logging
import time
from dataclasses import dataclass
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator, Dict, Any, List, Optional, Union

# Configure logging
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("AbletonMCPServer")

@dataclass
class AbletonConnection:
    host: str
    port: int
    sock: socket.socket = None
    
    def connect(self) -> bool:
        """Connect to the Ableton Remote Script socket server"""
        if self.sock:
            return True
            
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.connect((self.host, self.port))
            logger.info(f"Connected to Ableton at {self.host}:{self.port}")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to Ableton: {str(e)}")
            self.sock = None
            return False
    
    def disconnect(self):
        """Disconnect from the Ableton Remote Script"""
        if self.sock:
            try:
                self.sock.close()
            except Exception as e:
                logger.error(f"Error disconnecting from Ableton: {str(e)}")
            finally:
                self.sock = None

    def receive_full_response(self, sock, buffer_size=8192):
        """Receive the complete response, potentially in multiple chunks"""
        chunks = []
        sock.settimeout(15.0)  # Increased timeout for operations that might take longer
        
        try:
            while True:
                try:
                    chunk = sock.recv(buffer_size)
                    if not chunk:
                        if not chunks:
                            raise Exception("Connection closed before receiving any data")
                        break
                    
                    chunks.append(chunk)
                    
                    # Check if we've received a complete JSON object
                    try:
                        data = b''.join(chunks)
                        json.loads(data.decode('utf-8'))
                        logger.info(f"Received complete response ({len(data)} bytes)")
                        return data
                    except json.JSONDecodeError:
                        # Incomplete JSON, continue receiving
                        continue
                except socket.timeout:
                    logger.warning("Socket timeout during chunked receive")
                    break
                except (ConnectionError, BrokenPipeError, ConnectionResetError) as e:
                    logger.error(f"Socket connection error during receive: {str(e)}")
                    raise
        except Exception as e:
            logger.error(f"Error during receive: {str(e)}")
            raise
            
        # If we get here, we either timed out or broke out of the loop
        if chunks:
            data = b''.join(chunks)
            logger.info(f"Returning data after receive completion ({len(data)} bytes)")
            try:
                json.loads(data.decode('utf-8'))
                return data
            except json.JSONDecodeError:
                raise Exception("Incomplete JSON response received")
        else:
            raise Exception("No data received")

    def send_command(self, command_type: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """Send a command to Ableton and return the response"""
        if not self.sock and not self.connect():
            raise ConnectionError("Not connected to Ableton")
        
        command = {
            "type": command_type,
            "params": params or {}
        }
        
        # Check if this is a state-modifying command
        is_modifying_command = command_type in [
            "create_midi_track", "create_audio_track", "set_track_name",
            "set_track_color", "create_clip", "add_notes_to_clip", "set_clip_name",
            "set_tempo", "fire_clip", "stop_clip", "set_device_parameter",
            "start_playback", "stop_playback", "set_song_position", "load_instrument_or_effect",
            "set_track_volume", "set_track_pan", "set_track_send",
            "set_track_solo", "set_track_mute", "set_device_parameter_by_display",
            "undo", "redo", "set_mixer_snapshot", "set_clip_properties"
        ]
        
        try:
            logger.info(f"Sending command: {command_type} with params: {params}")
            
            # Send the command
            self.sock.sendall(json.dumps(command).encode('utf-8'))
            logger.info(f"Command sent, waiting for response...")
            
            # For state-modifying commands, add a small delay to give Ableton time to process
            if is_modifying_command:
                time.sleep(0.1)  # 100ms delay

            # Set timeout based on command type
            timeout = 15.0 if is_modifying_command else 10.0
            self.sock.settimeout(timeout)

            # Receive the response
            response_data = self.receive_full_response(self.sock)
            logger.info(f"Received {len(response_data)} bytes of data")

            # Parse the response
            response = json.loads(response_data.decode('utf-8'))
            logger.info(f"Response parsed, status: {response.get('status', 'unknown')}")

            if response.get("status") == "error":
                logger.error(f"Ableton error: {response.get('message')}")
                raise Exception(response.get("message", "Unknown error from Ableton"))

            # For state-modifying commands, add another small delay after receiving response
            if is_modifying_command:
                time.sleep(0.1)  # 100ms delay
            
            return response.get("result", {})
        except socket.timeout:
            logger.error("Socket timeout while waiting for response from Ableton")
            self.sock = None
            raise Exception("Timeout waiting for Ableton response")
        except (ConnectionError, BrokenPipeError, ConnectionResetError) as e:
            logger.error(f"Socket connection error: {str(e)}")
            self.sock = None
            raise Exception(f"Connection to Ableton lost: {str(e)}")
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON response from Ableton: {str(e)}")
            if 'response_data' in locals() and response_data:
                logger.error(f"Raw response (first 200 bytes): {response_data[:200]}")
            self.sock = None
            raise Exception(f"Invalid response from Ableton: {str(e)}")
        except Exception as e:
            logger.error(f"Error communicating with Ableton: {str(e)}")
            self.sock = None
            raise Exception(f"Communication error with Ableton: {str(e)}")

@asynccontextmanager
async def server_lifespan(server: FastMCP) -> AsyncIterator[Dict[str, Any]]:
    """Manage server startup and shutdown lifecycle"""
    try:
        logger.info("AbletonMCP server starting up")
        
        try:
            ableton = get_ableton_connection()
            logger.info("Successfully connected to Ableton on startup")
        except Exception as e:
            logger.warning(f"Could not connect to Ableton on startup: {str(e)}")
            logger.warning("Make sure the Ableton Remote Script is running")
        
        yield {}
    finally:
        global _ableton_connection
        if _ableton_connection:
            logger.info("Disconnecting from Ableton on shutdown")
            _ableton_connection.disconnect()
            _ableton_connection = None
        logger.info("AbletonMCP server shut down")

# Create the MCP server with lifespan support
mcp = FastMCP(
    "AbletonMCP",
    lifespan=server_lifespan
)

# Global connection for resources
_ableton_connection = None

def get_ableton_connection():
    """Get or create a persistent Ableton connection"""
    global _ableton_connection
    
    if _ableton_connection is not None:
        try:
            # Verify the connection is alive with a real lightweight command
            _ableton_connection.sock.settimeout(2.0)
            _ableton_connection.send_command("get_session_info")
            return _ableton_connection
        except Exception as e:
            logger.warning(f"Existing connection is no longer valid: {str(e)}")
            try:
                _ableton_connection.disconnect()
            except Exception:
                pass
            _ableton_connection = None
    
    # Connection doesn't exist or is invalid, create a new one
    if _ableton_connection is None:
        # Try to connect up to 3 times with a short delay between attempts
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            try:
                logger.info(f"Connecting to Ableton (attempt {attempt}/{max_attempts})...")
                _ableton_connection = AbletonConnection(host="localhost", port=9877)
                if _ableton_connection.connect():
                    logger.info("Created new persistent connection to Ableton")
                    
                    # Validate connection with a simple command
                    try:
                        # Get session info as a test
                        _ableton_connection.send_command("get_session_info")
                        logger.info("Connection validated successfully")
                        return _ableton_connection
                    except Exception as e:
                        logger.error(f"Connection validation failed: {str(e)}")
                        _ableton_connection.disconnect()
                        _ableton_connection = None
                        # Continue to next attempt
                else:
                    _ableton_connection = None
            except Exception as e:
                logger.error(f"Connection attempt {attempt} failed: {str(e)}")
                if _ableton_connection:
                    _ableton_connection.disconnect()
                    _ableton_connection = None
            
            # Wait before trying again, but only if we have more attempts left
            if attempt < max_attempts:
                time.sleep(1.0)
        
        # If we get here, all connection attempts failed
        if _ableton_connection is None:
            logger.error("Failed to connect to Ableton after multiple attempts")
            raise Exception("Could not connect to Ableton. Make sure the Remote Script is running.")
    
    return _ableton_connection


async def _ableton_cmd(command_type: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
    """Run a blocking Ableton command in a thread so the async event loop stays free."""
    return await asyncio.to_thread(
        lambda: get_ableton_connection().send_command(command_type, params or {})
    )


# Core Tool endpoints

@mcp.tool()
async def get_session_info(ctx: Context) -> str:
    """Get an overview of the current Ableton session: tempo, time signature,
    master volume/panning, and a compact tracks list (index, name, type,
    device class names, occupied clip names). Use this first to identify
    which tracks need deeper inspection via get_track_info or get_device_parameters."""
    try:
        result = await _ableton_cmd("get_session_info")
        return json.dumps(result, separators=(',', ':'))
    except Exception as e:
        logger.error(f"Error getting session info from Ableton: {str(e)}")
        return f"Error getting session info: {str(e)}"

@mcp.tool()
async def get_track_info(ctx: Context, track_index: int) -> str:
    """
    Get detailed information about a specific track in Ableton.

    Parameters:
    - track_index: The index of the track to get information about
    """
    try:
        result = await _ableton_cmd("get_track_info", {"track_index": track_index})
        return json.dumps(result, separators=(',', ':'))
    except Exception as e:
        logger.error(f"Error getting track info from Ableton: {str(e)}")
        return f"Error getting track info: {str(e)}"

@mcp.tool()
async def create_midi_track(ctx: Context, index: int = -1) -> str:
    """
    Create a new MIDI track in the Ableton session.

    Parameters:
    - index: The index to insert the track at (-1 = end of list)
    """
    try:
        result = await _ableton_cmd("create_midi_track", {"index": index})
        return f"Created new MIDI track: {result.get('name', 'unknown')}"
    except Exception as e:
        logger.error(f"Error creating MIDI track: {str(e)}")
        return f"Error creating MIDI track: {str(e)}"


@mcp.tool()
async def set_track_name(ctx: Context, track_index: int, name: str) -> str:
    """
    Set the name of a track.

    Parameters:
    - track_index: The index of the track to rename
    - name: The new name for the track
    """
    try:
        result = await _ableton_cmd("set_track_name", {"track_index": track_index, "name": name})
        return f"Renamed track to: {result.get('name', name)}"
    except Exception as e:
        logger.error(f"Error setting track name: {str(e)}")
        return f"Error setting track name: {str(e)}"

@mcp.tool()
async def set_track_color(ctx: Context, track_index: int, color: int) -> str:
    """
    Set the color of a track.

    Parameters:
    - track_index: The index of the track to recolor
    - color: RGB color as an integer (e.g., 0xFF0000 for red, 0x00FF00 for green)
    """
    try:
        await _ableton_cmd("set_track_color", {"track_index": track_index, "color": color})
        return f"Set track {track_index} color to #{color:06X}"
    except Exception as e:
        logger.error(f"Error setting track color: {str(e)}")
        return f"Error setting track color: {str(e)}"

@mcp.tool()
async def create_clip(ctx: Context, track_index: int, clip_index: int, length: float = 4.0) -> str:
    """
    Create a new MIDI clip in the specified track and clip slot.

    Parameters:
    - track_index: The index of the track to create the clip in
    - clip_index: The index of the clip slot to create the clip in
    - length: The length of the clip in beats (default: 4.0)
    """
    try:
        await _ableton_cmd("create_clip", {
            "track_index": track_index,
            "clip_index": clip_index,
            "length": length,
        })
        return f"Created new clip at track {track_index}, slot {clip_index} with length {length} beats"
    except Exception as e:
        logger.error(f"Error creating clip: {str(e)}")
        return f"Error creating clip: {str(e)}"

@mcp.tool()
async def add_notes_to_clip(
    ctx: Context,
    track_index: int,
    clip_index: int,
    notes: List[Dict[str, Union[int, float, bool]]]
) -> str:
    """
    Add MIDI notes to a clip.

    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip
    - notes: List of note dictionaries, each with pitch, start_time, duration, velocity, and mute
    """
    try:
        await _ableton_cmd("add_notes_to_clip", {
            "track_index": track_index,
            "clip_index": clip_index,
            "notes": notes,
        })
        return f"Added {len(notes)} notes to clip at track {track_index}, slot {clip_index}"
    except Exception as e:
        logger.error(f"Error adding notes to clip: {str(e)}")
        return f"Error adding notes to clip: {str(e)}"

@mcp.tool()
async def set_clip_name(ctx: Context, track_index: int, clip_index: int, name: str) -> str:
    """
    Set the name of a clip.

    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip
    - name: The new name for the clip
    """
    try:
        await _ableton_cmd("set_clip_name", {
            "track_index": track_index,
            "clip_index": clip_index,
            "name": name,
        })
        return f"Renamed clip at track {track_index}, slot {clip_index} to '{name}'"
    except Exception as e:
        logger.error(f"Error setting clip name: {str(e)}")
        return f"Error setting clip name: {str(e)}"

@mcp.tool()
async def set_tempo(ctx: Context, tempo: float) -> str:
    """
    Set the tempo of the Ableton session.

    Parameters:
    - tempo: The new tempo in BPM
    """
    try:
        await _ableton_cmd("set_tempo", {"tempo": tempo})
        return f"Set tempo to {tempo} BPM"
    except Exception as e:
        logger.error(f"Error setting tempo: {str(e)}")
        return f"Error setting tempo: {str(e)}"


@mcp.tool()
async def load_instrument_or_effect(ctx: Context, track_index: int, uri: str) -> str:
    """
    Load an instrument or effect onto a track using its URI.

    Parameters:
    - track_index: The index of the track to load the instrument on
    - uri: The URI of the instrument or effect to load (e.g., 'query:Synths#Instrument%20Rack:Bass:FileId_5116')
    """
    try:
        result = await _ableton_cmd("load_browser_item", {
            "track_index": track_index,
            "item_uri": uri,
        })
        if result.get("loaded", False):
            new_devices = result.get("new_devices", [])
            if new_devices:
                return f"Loaded instrument with URI '{uri}' on track {track_index}. New devices: {', '.join(new_devices)}"
            devices = result.get("devices_after", [])
            return f"Loaded instrument with URI '{uri}' on track {track_index}. Devices on track: {', '.join(devices)}"
        return f"Failed to load instrument with URI '{uri}'"
    except Exception as e:
        logger.error(f"Error loading instrument by URI: {str(e)}")
        return f"Error loading instrument by URI: {str(e)}"

@mcp.tool()
async def fire_clip(ctx: Context, track_index: int, clip_index: int) -> str:
    """
    Start playing a clip.

    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip
    """
    try:
        await _ableton_cmd("fire_clip", {"track_index": track_index, "clip_index": clip_index})
        return f"Started playing clip at track {track_index}, slot {clip_index}"
    except Exception as e:
        logger.error(f"Error firing clip: {str(e)}")
        return f"Error firing clip: {str(e)}"

@mcp.tool()
async def stop_clip(ctx: Context, track_index: int, clip_index: int) -> str:
    """
    Stop playing a clip.

    Parameters:
    - track_index: The index of the track containing the clip
    - clip_index: The index of the clip slot containing the clip
    """
    try:
        await _ableton_cmd("stop_clip", {"track_index": track_index, "clip_index": clip_index})
        return f"Stopped clip at track {track_index}, slot {clip_index}"
    except Exception as e:
        logger.error(f"Error stopping clip: {str(e)}")
        return f"Error stopping clip: {str(e)}"

@mcp.tool()
async def start_playback(ctx: Context) -> str:
    """Start playing the Ableton session."""
    try:
        await _ableton_cmd("start_playback")
        return "Started playback"
    except Exception as e:
        logger.error(f"Error starting playback: {str(e)}")
        return f"Error starting playback: {str(e)}"

@mcp.tool()
async def stop_playback(ctx: Context) -> str:
    """Stop playing the Ableton session."""
    try:
        await _ableton_cmd("stop_playback")
        return "Stopped playback"
    except Exception as e:
        logger.error(f"Error stopping playback: {str(e)}")
        return f"Error stopping playback: {str(e)}"

@mcp.tool()
async def get_browser_tree(ctx: Context, category_type: str = "all") -> str:
    """
    Get a hierarchical tree of browser categories from Ableton.

    Parameters:
    - category_type: Type of categories to get ('all', 'instruments', 'sounds', 'drums', 'audio_effects', 'midi_effects')
    """
    try:
        result = await _ableton_cmd("get_browser_tree", {"category_type": category_type})

        if "available_categories" in result and len(result.get("categories", [])) == 0:
            available_cats = result.get("available_categories", [])
            return (f"No categories found for '{category_type}'. "
                    f"Available browser categories: {', '.join(available_cats)}")

        total_folders = result.get("total_folders", 0)
        formatted_output = f"Browser tree for '{category_type}' (showing {total_folders} folders):\n\n"

        def format_tree(item, indent=0):
            output = ""
            if item:
                prefix = "  " * indent
                name = item.get("name", "Unknown")
                path = item.get("path", "")
                has_more = item.get("has_more", False)
                output += f"{prefix}• {name}"
                if path:
                    output += f" (path: {path})"
                if has_more:
                    output += " [...]"
                output += "\n"
                for child in item.get("children", []):
                    output += format_tree(child, indent + 1)
            return output

        for category in result.get("categories", []):
            formatted_output += format_tree(category)
            formatted_output += "\n"

        return formatted_output
    except Exception as e:
        error_msg = str(e)
        if "Browser is not available" in error_msg:
            logger.error(f"Browser is not available in Ableton: {error_msg}")
            return "Error: The Ableton browser is not available. Make sure Ableton Live is fully loaded and try again."
        elif "Could not access Live application" in error_msg:
            logger.error(f"Could not access Live application: {error_msg}")
            return "Error: Could not access the Ableton Live application. Make sure Ableton Live is running and the Remote Script is loaded."
        else:
            logger.error(f"Error getting browser tree: {error_msg}")
            return f"Error getting browser tree: {error_msg}"

@mcp.tool()
async def get_browser_items_at_path(ctx: Context, path: str) -> str:
    """
    Get browser items at a specific path in Ableton's browser.

    Parameters:
    - path: Path in the format "category/folder/subfolder"
            where category is one of the available browser categories in Ableton
    """
    try:
        result = await _ableton_cmd("get_browser_items_at_path", {"path": path})

        if "error" in result and "available_categories" in result:
            error = result.get("error", "")
            available_cats = result.get("available_categories", [])
            return (f"Error: {error}\n"
                    f"Available browser categories: {', '.join(available_cats)}")

        return json.dumps(result, separators=(',', ':'))
    except Exception as e:
        error_msg = str(e)
        if "Browser is not available" in error_msg:
            logger.error(f"Browser is not available in Ableton: {error_msg}")
            return "Error: The Ableton browser is not available. Make sure Ableton Live is fully loaded and try again."
        elif "Could not access Live application" in error_msg:
            logger.error(f"Could not access Live application: {error_msg}")
            return "Error: Could not access the Ableton Live application. Make sure Ableton Live is running and the Remote Script is loaded."
        elif "Unknown or unavailable category" in error_msg:
            logger.error(f"Invalid browser category: {error_msg}")
            return f"Error: {error_msg}. Please check the available categories using get_browser_tree."
        elif "Path part" in error_msg and "not found" in error_msg:
            logger.error(f"Path not found: {error_msg}")
            return f"Error: {error_msg}. Please check the path and try again."
        else:
            logger.error(f"Error getting browser items at path: {error_msg}")
            return f"Error getting browser items at path: {error_msg}"

@mcp.tool()
async def load_drum_kit(ctx: Context, track_index: int, rack_uri: str, kit_path: str) -> str:
    """
    Load a drum rack and then load a specific drum kit into it.

    Parameters:
    - track_index: The index of the track to load on
    - rack_uri: The URI of the drum rack to load (e.g., 'Drums/Drum Rack')
    - kit_path: Path to the drum kit inside the browser (e.g., 'drums/acoustic/kit1')
    """
    try:
        result = await _ableton_cmd("load_browser_item", {"track_index": track_index, "item_uri": rack_uri})
        if not result.get("loaded", False):
            return f"Failed to load drum rack with URI '{rack_uri}'"

        kit_result = await _ableton_cmd("get_browser_items_at_path", {"path": kit_path})
        if "error" in kit_result:
            return f"Loaded drum rack but failed to find drum kit: {kit_result.get('error')}"

        kit_items = kit_result.get("items", [])
        loadable_kits = [item for item in kit_items if item.get("is_loadable", False)]
        if not loadable_kits:
            return f"Loaded drum rack but no loadable drum kits found at '{kit_path}'"

        kit_uri = loadable_kits[0].get("uri")
        await _ableton_cmd("load_browser_item", {"track_index": track_index, "item_uri": kit_uri})
        return f"Loaded drum rack and kit '{loadable_kits[0].get('name')}' on track {track_index}"
    except Exception as e:
        logger.error(f"Error loading drum kit: {str(e)}")
        return f"Error loading drum kit: {str(e)}"

@mcp.tool()
async def get_device_parameters(ctx: Context, track_index: int) -> str:
    """
    Get all device parameters for every device on a track, including devices
    nested inside racks (Instrument Racks, Audio Effect Racks, Drum Racks).

    Parameters:
    - track_index: The index of the track to inspect

    Returns a JSON object with each device's name, class, type, active state,
    and all parameters (name, value, display_value, min, max, is_enabled).
    Rack chains are included recursively under each rack device.
    """
    try:
        result = await _ableton_cmd("get_device_parameters", {"track_index": track_index})
        return json.dumps(result, separators=(',', ':'))
    except Exception as e:
        logger.error(f"Error getting device parameters: {str(e)}")
        return f"Error getting device parameters: {str(e)}"

@mcp.tool()
async def set_track_volume(ctx: Context, track_index: int, db: float) -> str:
    """
    Set a track's volume in dB.

    Parameters:
    - track_index: The index of the track
    - db: Volume in dB (range roughly -70 to +6, where 0 dB is unity)
    """
    try:
        result = await _ableton_cmd("set_track_volume", {"track_index": track_index, "db": db})
        return f"Set track {track_index} volume to {result.get('volume', f'{db} dB')}"
    except Exception as e:
        logger.error(f"Error setting track volume: {str(e)}")
        return f"Error setting track volume: {str(e)}"


@mcp.tool()
async def set_track_pan(ctx: Context, track_index: int, value: float) -> str:
    """
    Set a track's panning.

    Parameters:
    - track_index: The index of the track
    - value: Pan value from -1.0 (full left) to 1.0 (full right), 0.0 = center
    """
    try:
        result = await _ableton_cmd("set_track_pan", {"track_index": track_index, "value": value})
        return f"Set track {track_index} pan to {result.get('pan', value)}"
    except Exception as e:
        logger.error(f"Error setting track pan: {str(e)}")
        return f"Error setting track pan: {str(e)}"


@mcp.tool()
async def set_device_parameter(
    ctx: Context,
    track_index: int,
    device_index: int,
    parameter_name: str,
    value: float,
) -> str:
    """
    Set a device parameter on a track.

    Parameters:
    - track_index: The index of the track containing the device
    - device_index: The index of the device on the track
    - parameter_name: The exact name of the parameter (as returned by get_device_parameters)
    - value: The new value. For continuous params use the raw float in the parameter's
             min/max range. For quantized params use the integer index into value_items.
    """
    try:
        result = await _ableton_cmd("set_device_parameter", {
            "track_index": track_index,
            "device_index": device_index,
            "parameter_name": parameter_name,
            "value": value,
        })
        return (f"Set {result.get('device', '?')}.{result.get('parameter', '?')} "
                f"to {result.get('display_value', value)}")
    except Exception as e:
        logger.error(f"Error setting device parameter: {str(e)}")
        return f"Error setting device parameter: {str(e)}"


@mcp.tool()
async def set_track_send(ctx: Context, track_index: int, send_index: int, value: float) -> str:
    """
    Set a track's send level.

    Parameters:
    - track_index: The index of the track
    - send_index: The index of the send (0 = Send A, 1 = Send B, etc.)
    - value: Send level from 0.0 (off) to 1.0 (full)
    """
    try:
        result = await _ableton_cmd("set_track_send", {
            "track_index": track_index,
            "send_index": send_index,
            "value": value,
        })
        return f"Set track {track_index} send {send_index} to {result.get('send', value)}"
    except Exception as e:
        logger.error(f"Error setting track send: {str(e)}")
        return f"Error setting track send: {str(e)}"


@mcp.tool()
async def set_track_solo(ctx: Context, track_index: int, state: bool) -> str:
    """
    Set a track's solo state.

    Parameters:
    - track_index: The index of the track
    - state: True to solo, False to unsolo
    """
    try:
        result = await _ableton_cmd("set_track_solo", {"track_index": track_index, "state": state})
        return f"Set track {track_index} solo to {result.get('solo', state)}"
    except Exception as e:
        logger.error(f"Error setting track solo: {str(e)}")
        return f"Error setting track solo: {str(e)}"


@mcp.tool()
async def set_track_mute(ctx: Context, track_index: int, state: bool) -> str:
    """
    Set a track's mute state.

    Parameters:
    - track_index: The index of the track
    - state: True to mute, False to unmute
    """
    try:
        result = await _ableton_cmd("set_track_mute", {"track_index": track_index, "state": state})
        return f"Set track {track_index} mute to {result.get('mute', state)}"
    except Exception as e:
        logger.error(f"Error setting track mute: {str(e)}")
        return f"Error setting track mute: {str(e)}"


@mcp.tool()
async def undo(ctx: Context) -> str:
    """Undo the last action in Ableton."""
    try:
        await _ableton_cmd("undo")
        return "Undone"
    except Exception as e:
        logger.error(f"Error performing undo: {str(e)}")
        return f"Error performing undo: {str(e)}"


@mcp.tool()
async def redo(ctx: Context) -> str:
    """Redo the last undone action in Ableton."""
    try:
        await _ableton_cmd("redo")
        return "Redone"
    except Exception as e:
        logger.error(f"Error performing redo: {str(e)}")
        return f"Error performing redo: {str(e)}"


@mcp.tool()
async def get_arrangement_clips(ctx: Context) -> str:
    """
    Get all arrangement-view clips across all tracks.
    Returns each track's clips with name, start_time, end_time, length,
    loop_start, loop_end, and color. Only tracks that have clips are included.
    """
    try:
        result = await _ableton_cmd("get_arrangement_clips")
        return json.dumps(result, separators=(',', ':'))
    except Exception as e:
        logger.error(f"Error getting arrangement clips: {str(e)}")
        return f"Error getting arrangement clips: {str(e)}"


@mcp.tool()
async def set_device_parameter_by_display(
    ctx: Context,
    track_index: int,
    device_index: int,
    parameter_name: str,
    display_value: str,
) -> str:
    """
    Set a device parameter by its human-readable display value (e.g., "5.0 dB", "40 %").
    The Remote Script binary-searches the parameter range to find the raw value that
    produces a matching display string. For quantized parameters, it matches against
    value_items directly.

    Parameters:
    - track_index: The index of the track containing the device
    - device_index: The index of the device on the track
    - parameter_name: The exact name of the parameter
    - display_value: The target display string (as shown by get_device_parameters)
    """
    try:
        result = await _ableton_cmd("set_device_parameter_by_display", {
            "track_index": track_index,
            "device_index": device_index,
            "parameter_name": parameter_name,
            "display_value": display_value,
        })
        note = result.get("note", "")
        msg = (f"Set {result.get('device', '?')}.{result.get('parameter', '?')} "
               f"to {result.get('display_value', display_value)}")
        if note:
            msg += f" ({note})"
        return msg
    except Exception as e:
        logger.error(f"Error setting device parameter by display: {str(e)}")
        return f"Error setting device parameter by display: {str(e)}"


@mcp.tool()
async def mix_analysis(
    ctx: Context,
    bar: int = 1,
    bars: int = 4,
    device: str = "BlackHole",
) -> str:
    """
    Per-track spectral analysis of the mix.

    Solos each non-muted track one at a time, captures a loopback snippet,
    then captures the full master with nothing soloed. Returns a combined
    report with per-track spectral features and master analysis.

    Parameters:
    - bar:    Bar number to start from, 1-indexed (default: 1).
    - bars:   Number of bars to capture per track (default: 4).
    - device: Substring of the loopback device name (default: "BlackHole").

    WARNING: This is slow — captures audio once per audible track plus once
    for the master. For a 10-track session with 4-bar captures at 130 BPM it
    will take roughly 80 seconds.
    """
    try:
        from .loopback import capture_and_analyze

        # 1. Get session info
        info = await _ableton_cmd("get_session_info")
        tempo = float(info.get("tempo", 120.0))
        time_sig = info.get("time_signature", "4/4")
        beats_per_bar = int(time_sig.split("/")[0])
        beat_pos = (bar - 1) * beats_per_bar
        seconds = bars * (60.0 / tempo) * beats_per_bar

        tracks = info.get("tracks", [])

        # 2. Record original solo/mute states
        original_states = []
        for t in tracks:
            idx = t["index"]
            t_info = await _ableton_cmd("get_track_info", {"track_index": idx})
            original_states.append({
                "index": idx,
                "solo": t_info.get("solo", False),
                "mute": t_info.get("mute", False),
            })

        # Helper to capture one snippet
        async def _capture():
            await _ableton_cmd("set_song_position", {"beat": beat_pos})
            await _ableton_cmd("start_playback")
            await asyncio.sleep(0.15)
            result = await asyncio.to_thread(capture_and_analyze, seconds, device)
            await _ableton_cmd("stop_playback")
            return result

        per_track = []
        try:
            # 3. Unsolo everything first
            for st in original_states:
                if st["solo"]:
                    await _ableton_cmd("set_track_solo", {"track_index": st["index"], "state": False})

            # 4. Per-track: solo → capture → unsolo
            for t in tracks:
                idx = t["index"]
                state = next(s for s in original_states if s["index"] == idx)
                if state["mute"]:
                    continue

                await _ableton_cmd("set_track_solo", {"track_index": idx, "state": True})
                await asyncio.sleep(0.05)

                features = await _capture()
                per_track.append({
                    "track_index": idx,
                    "track_name": t.get("name", ""),
                    "features": features,
                })

                await _ableton_cmd("set_track_solo", {"track_index": idx, "state": False})
                await asyncio.sleep(0.05)

            # 5. Master capture (nothing soloed)
            master = await _capture()

        finally:
            # 6. Restore original solo/mute states
            for st in original_states:
                await _ableton_cmd("set_track_solo", {"track_index": st["index"], "state": st["solo"]})
                await _ableton_cmd("set_track_mute", {"track_index": st["index"], "state": st["mute"]})

        report = {
            "tempo": round(tempo, 1),
            "bar": bar,
            "bars": bars,
            "per_track": per_track,
            "master": master,
        }
        return json.dumps(report, separators=(',', ':'))

    except RuntimeError as e:
        return f"Error: {e}"
    except Exception as e:
        logger.error(f"Error in mix_analysis: {e}")
        return f"Error: {e}"


@mcp.tool()
async def get_mixer_snapshot(ctx: Context) -> str:
    """
    Capture the full mixer state: volume, pan, mute, solo, sends,
    and device on/off for every track. Use with set_mixer_snapshot to A/B mixes.
    """
    try:
        result = await _ableton_cmd("get_mixer_snapshot")
        return json.dumps(result, separators=(',', ':'))
    except Exception as e:
        logger.error(f"Error getting mixer snapshot: {str(e)}")
        return f"Error getting mixer snapshot: {str(e)}"


@mcp.tool()
async def set_mixer_snapshot(ctx: Context, snapshot: str) -> str:
    """
    Restore a previously saved mixer snapshot (from get_mixer_snapshot).

    Parameters:
    - snapshot: JSON string of the snapshot to restore
    """
    try:
        snap = json.loads(snapshot)
        result = await _ableton_cmd("set_mixer_snapshot", {"snapshot": snap})
        return f"Restored mixer snapshot ({result.get('applied', 0)} tracks)"
    except Exception as e:
        logger.error(f"Error setting mixer snapshot: {str(e)}")
        return f"Error setting mixer snapshot: {str(e)}"


@mcp.tool()
async def compare_snippets(
    ctx: Context,
    bar_a: int = 1,
    bar_b: int = 1,
    bars: int = 4,
    device: str = "BlackHole",
) -> str:
    """
    Capture two snippets and return a feature-by-feature comparison.

    Useful for A/B testing: capture bar_a, make changes, capture bar_b (can be same bar).
    If bar_a == bar_b, captures twice with a short pause between for before/after comparisons.

    Parameters:
    - bar_a: Bar number for first capture
    - bar_b: Bar number for second capture
    - bars: Number of bars per capture (default: 4)
    - device: Loopback device name substring
    """
    try:
        from .loopback import capture_and_analyze
        from .psycho_features import compare

        info = await _ableton_cmd("get_session_info")
        tempo = float(info.get("tempo", 120.0))
        time_sig = info.get("time_signature", "4/4")
        beats_per_bar = int(time_sig.split("/")[0])
        seconds = bars * (60.0 / tempo) * beats_per_bar

        async def _capture_bar(bar):
            beat_pos = (bar - 1) * beats_per_bar
            await _ableton_cmd("set_song_position", {"beat": beat_pos})
            await _ableton_cmd("start_playback")
            await asyncio.sleep(0.15)
            result = await asyncio.to_thread(capture_and_analyze, seconds, device)
            await _ableton_cmd("stop_playback")
            return result

        snap_a = await _capture_bar(bar_a)
        snap_b = await _capture_bar(bar_b)

        delta = compare(snap_a["features"], snap_b["features"])

        report = {
            "bar_a": bar_a,
            "bar_b": bar_b,
            "bars": bars,
            "features_a": snap_a["features"],
            "features_b": snap_b["features"],
            "delta": delta,
        }
        return json.dumps(report, separators=(',', ':'))

    except Exception as e:
        logger.error(f"Error in compare_snippets: {e}")
        return f"Error: {e}"


@mcp.tool()
async def masking_analysis(
    ctx: Context,
    bar: int = 1,
    bars: int = 2,
    device: str = "BlackHole",
) -> str:
    """
    Detect frequency masking between tracks.

    Solos each track, captures raw audio, then analyzes which pairs of tracks
    compete for the same frequency bands.

    Parameters:
    - bar: Bar number to start from (default: 1)
    - bars: Number of bars to capture per track (default: 2, kept short for speed)
    - device: Loopback device name substring

    WARNING: Slow — captures audio once per audible track.
    """
    try:
        from .loopback import capture_audio
        from .psycho_features import masking_report

        info = await _ableton_cmd("get_session_info")
        tempo = float(info.get("tempo", 120.0))
        time_sig = info.get("time_signature", "4/4")
        beats_per_bar = int(time_sig.split("/")[0])
        beat_pos = (bar - 1) * beats_per_bar
        seconds = bars * (60.0 / tempo) * beats_per_bar

        tracks = info.get("tracks", [])

        # Record original states
        original_states = []
        for t in tracks:
            idx = t["index"]
            t_info = await _ableton_cmd("get_track_info", {"track_index": idx})
            original_states.append({
                "index": idx,
                "solo": t_info.get("solo", False),
                "mute": t_info.get("mute", False),
            })

        audio_tracks = []
        try:
            # Unsolo everything
            for st in original_states:
                if st["solo"]:
                    await _ableton_cmd("set_track_solo", {"track_index": st["index"], "state": False})

            # Per-track: solo → capture raw audio → unsolo
            for t in tracks:
                idx = t["index"]
                state = next(s for s in original_states if s["index"] == idx)
                if state["mute"]:
                    continue

                await _ableton_cmd("set_track_solo", {"track_index": idx, "state": True})
                await asyncio.sleep(0.05)

                await _ableton_cmd("set_song_position", {"beat": beat_pos})
                await _ableton_cmd("start_playback")
                await asyncio.sleep(0.15)
                audio, sr, _ = await asyncio.to_thread(capture_audio, seconds, device)
                await _ableton_cmd("stop_playback")

                audio_tracks.append((audio, t.get("name", f"Track {idx}")))

                await _ableton_cmd("set_track_solo", {"track_index": idx, "state": False})
                await asyncio.sleep(0.05)

        finally:
            for st in original_states:
                await _ableton_cmd("set_track_solo", {"track_index": st["index"], "state": st["solo"]})
                await _ableton_cmd("set_track_mute", {"track_index": st["index"], "state": st["mute"]})

        report = masking_report(audio_tracks, sr)
        report["bar"] = bar
        report["bars"] = bars
        report["tracks_analyzed"] = len(audio_tracks)
        return json.dumps(report, separators=(',', ':'))

    except Exception as e:
        logger.error(f"Error in masking_analysis: {e}")
        return f"Error: {e}"


@mcp.tool()
async def compare_to_reference(
    ctx: Context,
    bar: int = 1,
    bars: int = 4,
    reference_track_index: int = 9,
    device: str = "BlackHole",
) -> str:
    """
    Compare your mix against a reference track.

    Unmutes and solos the reference track to capture it, then captures the full
    mix (without reference), and returns a feature-by-feature delta.

    Parameters:
    - bar: Bar to capture from
    - bars: Bars to capture
    - reference_track_index: Index of the reference track (default: 9)
    - device: Loopback device name
    """
    try:
        from .loopback import capture_and_analyze
        from .psycho_features import compare

        info = await _ableton_cmd("get_session_info")
        tempo = float(info.get("tempo", 120.0))
        time_sig = info.get("time_signature", "4/4")
        beats_per_bar = int(time_sig.split("/")[0])
        beat_pos = (bar - 1) * beats_per_bar
        seconds = bars * (60.0 / tempo) * beats_per_bar

        # Save reference track state
        ref_info = await _ableton_cmd("get_track_info", {"track_index": reference_track_index})
        ref_was_muted = ref_info.get("mute", False)
        ref_was_solo = ref_info.get("solo", False)

        async def _capture():
            await _ableton_cmd("set_song_position", {"beat": beat_pos})
            await _ableton_cmd("start_playback")
            await asyncio.sleep(0.15)
            result = await asyncio.to_thread(capture_and_analyze, seconds, device)
            await _ableton_cmd("stop_playback")
            return result

        try:
            # Capture reference (solo it, unmute it)
            await _ableton_cmd("set_track_mute", {"track_index": reference_track_index, "state": False})
            await _ableton_cmd("set_track_solo", {"track_index": reference_track_index, "state": True})
            await asyncio.sleep(0.05)
            ref_snap = await _capture()

            # Unsolo reference, re-mute it
            await _ableton_cmd("set_track_solo", {"track_index": reference_track_index, "state": False})
            await _ableton_cmd("set_track_mute", {"track_index": reference_track_index, "state": True})
            await asyncio.sleep(0.05)

            # Capture the mix
            mix_snap = await _capture()

        finally:
            # Restore reference track state
            await _ableton_cmd("set_track_mute", {"track_index": reference_track_index, "state": ref_was_muted})
            await _ableton_cmd("set_track_solo", {"track_index": reference_track_index, "state": ref_was_solo})

        delta = compare(ref_snap["features"], mix_snap["features"])

        report = {
            "reference": ref_snap["features"],
            "mix": mix_snap["features"],
            "delta": delta,
            "bar": bar,
            "bars": bars,
        }
        return json.dumps(report, separators=(',', ':'))

    except Exception as e:
        logger.error(f"Error in compare_to_reference: {e}")
        return f"Error: {e}"


@mcp.tool()
async def set_clip_properties(
    ctx: Context,
    track_index: int,
    clip_index: int,
    gain: float = None,
    pitch_coarse: int = None,
    pitch_fine: float = None,
    warp_mode: int = None,
    warping: bool = None,
) -> str:
    """
    Set properties on a clip (arrangement or session).

    Parameters:
    - track_index: Track index (supports -1 for master, -2/-3 for returns)
    - clip_index: Clip index (arrangement clips by index, or session clip slot)
    - gain: Clip gain (1.0 = unity, 0.5 = -6dB, 2.0 = +6dB)
    - pitch_coarse: Pitch shift in semitones
    - pitch_fine: Fine pitch in cents
    - warp_mode: 0=Beats, 1=Tones, 2=Texture, 3=Re-Pitch, 4=Complex, 5=REX, 6=Complex Pro
    - warping: Enable/disable warping
    """
    try:
        props = {}
        if gain is not None:
            props["gain"] = gain
        if pitch_coarse is not None:
            props["pitch_coarse"] = pitch_coarse
        if pitch_fine is not None:
            props["pitch_fine"] = pitch_fine
        if warp_mode is not None:
            props["warp_mode"] = warp_mode
        if warping is not None:
            props["warping"] = warping
        result = await _ableton_cmd("set_clip_properties", {
            "track_index": track_index,
            "clip_index": clip_index,
            "properties": props,
        })
        return f"Set clip '{result.get('name', '?')}' properties: {json.dumps(result, separators=(',', ':'))}"
    except Exception as e:
        logger.error(f"Error setting clip properties: {str(e)}")
        return f"Error setting clip properties: {str(e)}"


@mcp.tool()
async def lufs_timeline(
    ctx: Context,
    bar_start: int = 1,
    bar_end: int = 8,
    device: str = "BlackHole",
) -> str:
    """
    Capture per-bar loudness across a range of bars.

    Returns an array of per-bar analysis with LUFS, true peak, and energy bands.
    Useful for seeing dynamics and energy flow across the arrangement.

    Parameters:
    - bar_start: First bar to capture (1-indexed)
    - bar_end: Last bar to capture (inclusive)
    - device: Loopback device name substring
    """
    try:
        from .loopback import capture_and_analyze

        info = await _ableton_cmd("get_session_info")
        tempo = float(info.get("tempo", 120.0))
        time_sig = info.get("time_signature", "4/4")
        beats_per_bar = int(time_sig.split("/")[0])
        seconds_per_bar = (60.0 / tempo) * beats_per_bar

        timeline = []
        for bar in range(bar_start, bar_end + 1):
            beat_pos = (bar - 1) * beats_per_bar
            await _ableton_cmd("set_song_position", {"beat": beat_pos})
            await _ableton_cmd("start_playback")
            await asyncio.sleep(0.15)
            result = await asyncio.to_thread(capture_and_analyze, seconds_per_bar, device)
            await _ableton_cmd("stop_playback")

            entry = {"bar": bar}
            entry.update(result.get("features", {}))
            timeline.append(entry)

        return json.dumps({
            "tempo": round(tempo, 1),
            "bar_start": bar_start,
            "bar_end": bar_end,
            "timeline": timeline,
        }, separators=(',', ':'))

    except Exception as e:
        logger.error(f"Error in lufs_timeline: {e}")
        return f"Error: {e}"


@mcp.tool()
async def analyze_snippet(
    ctx: Context,
    bar: int = 1,
    bars: int = 4,
    device: str = "BlackHole",
) -> str:
    """
    Seek Ableton to a bar, auto-play, capture loopback audio, auto-stop, return psychoacoustic features.

    Full flow (no manual play needed):
      1. Fetches session tempo + time signature
      2. Seeks playback head to `bar`
      3. Starts playback
      4. Captures `bars` bars of audio from the loopback device
      5. Stops playback
      6. Returns ~17 psychoacoustic features

    Parameters:
    - bar:    Bar number to start from, 1-indexed (default: 1).
    - bars:   Number of bars to capture (default: 4).
    - device: Substring of the loopback device name (default: "BlackHole").
              Call list_audio_devices if unsure.

    Requires BlackHole (or another loopback device) installed and routed
    as Ableton's audio output.
    """
    try:
        from .loopback import capture_and_analyze

        info = await _ableton_cmd("get_session_info")
        tempo = float(info.get("tempo", 120.0))
        time_sig = info.get("time_signature", "4/4")
        beats_per_bar = int(time_sig.split("/")[0])

        beat_pos = (bar - 1) * beats_per_bar
        await _ableton_cmd("set_song_position", {"beat": beat_pos})

        seconds = bars * (60.0 / tempo) * beats_per_bar
        await _ableton_cmd("start_playback")
        await asyncio.sleep(0.15)  # let Ableton stabilise before opening capture

        # capture_and_analyze blocks for `seconds` — run in thread
        result = await asyncio.to_thread(capture_and_analyze, seconds, device)

        await _ableton_cmd("stop_playback")

        result["bar"] = bar
        result["bars"] = bars
        result["tempo"] = round(tempo, 1)
        return json.dumps(result, separators=(',', ':'))
    except RuntimeError as e:
        return f"Error: {e}"
    except Exception as e:
        logger.error(f"Error in analyze_snippet: {e}")
        return f"Error: {e}"


@mcp.tool()
async def list_audio_devices(ctx: Context) -> str:
    """List available audio input devices. Use this to find the right device
    name to pass to analyze_snippet if BlackHole is not detected."""
    try:
        from .loopback import list_input_devices
        devices = await asyncio.to_thread(list_input_devices)
        return json.dumps(devices, separators=(',', ':'))
    except Exception as e:
        return f"Error listing devices: {e}"


@mcp.tool()
async def analyze_render(
    ctx: Context,
    export_folder: str = str(Path.home() / "Music" / "Ableton" / "Exports"),
    timeout: float = 120.0,
    trigger: bool = True,
    accept_dialog: bool = True,
    dialog_delay: float = 2.0,
) -> str:
    """
    Trigger an Ableton export and return psychoacoustic analysis of the rendered file.

    Flow:
      1. Sends Cmd+Shift+R to Ableton (opens Export Audio/Video dialog)
      2. Optionally presses Return to accept the dialog with current settings
      3. Watches the export folder for the new file
      4. Loads the file and computes ~17 psychoacoustic features

    Parameters:
    - export_folder: Folder Ableton writes exports to
                     (default: ~/Music/Ableton/Exports)
    - timeout:       Max seconds to wait for the render to complete (default: 120)
    - trigger:       Send Cmd+Shift+R before watching. Set False if you already
                     started the export manually (default: True)
    - accept_dialog: Press Return to auto-accept the export dialog (default: True).
                     Set False to open the dialog and let the user configure it.
    - dialog_delay:  Seconds to wait for the dialog before pressing Return (default: 2.0)

    Returns JSON with:
      "file"     — absolute path of the rendered file
      "features" — dict of psychoacoustic features (lufs, lra, spectral centroid, etc.)

    Note: Requires macOS Accessibility permissions for System Events AppleScript.
    """
    try:
        from .render_pipeline import render_and_analyze
        result = await asyncio.to_thread(
            render_and_analyze,
            Path(export_folder),
            timeout,
            trigger,
            accept_dialog,
            dialog_delay,
        )
        return json.dumps(result, separators=(',', ':'))
    except FileNotFoundError as e:
        return f"Error: {e}. Check that the export folder exists and Ableton is configured to export there."
    except TimeoutError as e:
        return f"Error: {e}. The render may still be in progress, or the export folder may be wrong."
    except RuntimeError as e:
        return f"Error triggering render: {e}. Make sure Ableton is running and macOS Accessibility is enabled for your terminal/IDE."
    except Exception as e:
        logger.error(f"Error in analyze_render: {e}")
        return f"Error: {e}"


# Main execution
def main():
    """Run the MCP server"""
    mcp.run()

if __name__ == "__main__":
    main()