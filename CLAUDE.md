# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
uv sync

# Run the MCP server directly
uv run ableton-mcp

# Run via uvx (no install needed)
uvx ableton-mcp

# Build/install locally for development
uv pip install -e .
```

There are no tests in this project.

## Architecture

This project has two independent components that communicate over TCP sockets on `localhost:9877`:

### 1. Ableton Remote Script (`AbletonMCP_Remote_Script/__init__.py`)
A MIDI Remote Script that runs **inside Ableton Live**. It extends `ControlSurface` from Ableton's `_Framework` and starts a TCP socket server on port 9877. Each incoming connection is handled in a separate thread. It receives JSON commands, executes them against the Live Python API (`self.song()`), and returns JSON responses.

This file must be copied into Ableton's MIDI Remote Scripts directory and selected in Ableton's preferences — it cannot be run from the command line.

### 2. MCP Server (`MCP_Server/server.py`)
A Python MCP server using `FastMCP` that exposes Ableton control as MCP tools. The entry point is `main()` → `mcp.run()`. It connects to the Remote Script socket as a TCP client.

- `AbletonConnection` manages the TCP connection with reconnect logic (3 attempts)
- `get_ableton_connection()` maintains a global singleton connection with liveness checking
- All tools follow the same pattern: call `get_ableton_connection()`, call `ableton.send_command(command_type, params)`, return a string result
- State-modifying commands (track creation, clip creation, note addition, etc.) get 100ms delays before and after the response to give Ableton time to process

### Communication Protocol
Commands are JSON: `{"type": "command_name", "params": {...}}`  
Responses are JSON: `{"status": "ok"|"error", "result": {...}}` or `{"status": "error", "message": "..."}`

The `receive_full_response` method accumulates TCP chunks and validates complete JSON before returning.

### Adding New Tools
1. Add a handler in `AbletonMCP_Remote_Script/__init__.py` that reads from `self._song` and returns a result dict
2. Add a `@mcp.tool()` decorated function in `MCP_Server/server.py` that calls `ableton.send_command("your_command_type", params)`
3. If the new command modifies Live's state, add it to the `is_modifying_command` list in `send_command()`
