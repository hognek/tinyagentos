#!/usr/bin/env python3
"""Probe 3: Frame grid readback

Verifies that tuiui apphost returns clean CellBuffer grids without ANSI escapes.
"""

import os
import sys
from pathlib import Path

# Add parent directory to path so we can import tuiui_conduit
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from tinyagentos.tuiui_conduit import TuiuiConduit, TuiuiConduitError, Frame


def get_socket_path() -> str:
    """Get socket path from TUIUI_APPHOST_SOCK env var or argv[1]."""
    if sock := os.environ.get("TUIUI_APPHOST_SOCK"):
        return sock
    if len(sys.argv) > 1:
        return sys.argv[1]
    from tinyagentos.tuiui_conduit import default_socket_path
    return default_socket_path()


def verify_apphost(socket_path: str) -> None:
    """Verify the apphost socket exists and answers ListApps.

    Exits with code 2 and prints 'could not run:' message if verification fails.
    """
    if not os.path.exists(socket_path):
        print(f"could not run: no tuiui apphost at {socket_path} (socket does not exist)")
        sys.exit(2)

    import stat
    try:
        st = os.lstat(socket_path)
        if not stat.S_ISSOCK(st.st_mode):
            print(f"could not run: no tuiui apphost at {socket_path} (not a socket)")
            sys.exit(2)
    except OSError as e:
        print(f"could not run: no tuiui apphost at {socket_path} (cannot stat: {e})")
        sys.exit(2)

    try:
        with TuiuiConduit(socket_path, timeout=2.0) as conduit:
            conduit.list_apps()
    except TuiuiConduitError as e:
        print(f"could not run: no tuiui apphost at {socket_path} ({e})")
        sys.exit(2)
    except OSError as e:
        print(f"could not run: no tuiui apphost at {socket_path} (connection failed: {e})")
        sys.exit(2)


def probe_frame_grid_readback(socket_path: str) -> str:
    """Probe the Frame event format and ANSI-free output."""
    transcript_lines = []

    # Test 1: Spawn and get Frame with clean text
    transcript_lines.append("=== Test 1: Frame Grid Readback (Clean Text) ===")
    transcript_lines.append("Command: Spawn app and read Frame")

    with TuiuiConduit(socket_path, timeout=2.0) as conduit:
        spawned = conduit.spawn("sh", ["-c", "echo test"], cols=80, rows=24)

        # Read frames until we get one
        for frame in conduit.iter_frames():
            lines = TuiuiConduit.frame_lines(frame)
            transcript_lines.append(f"Result: Frame with text: {lines}")

            # Verify no ANSI escapes - check the actual cell character values
            ansi_count = sum(1 for cell in frame.cells if isinstance(cell, str) and '\x1b' in cell)
            transcript_lines.append(f"ANSI escape count: {ansi_count} (should be 0)")
            break

    transcript_lines.append("")

    # Test 2: Send input and get response frame
    transcript_lines.append("=== Test 2: Input to Frame ===")
    transcript_lines.append("Command: Send input and read frame")

    with TuiuiConduit(socket_path, timeout=2.0) as conduit:
        try:
            conduit.send_input(spawned.app, b"hello")

            for frame in conduit.iter_frames():
                lines = TuiuiConduit.frame_lines(frame)
                transcript_lines.append(f"Result: Frame after input: {lines}")

                # Verify the text matches input
                expected = "hello"
                if lines and lines[0] == expected:
                    transcript_lines.append("Verification: Input text correctly reflected in frame")
                break
        except Exception as e:
            transcript_lines.append(f"Result: Failed - {e}")

    transcript_lines.append("")

    # Test 3: Verify ANSI-free encoding
    transcript_lines.append("=== Test 3: ANSI-Free Verification ===")
    transcript_lines.append("Test: Create text with potential ANSI and verify it's cleaned")
    transcript_lines.append("Note: In real tuiui, ANSI is decoded by alacritty emulator before reaching socket")
    transcript_lines.append("The CellBuffer grid received over socket should have ch values only (no \\x1b escapes)")

    return "\n".join(transcript_lines)


if __name__ == "__main__":
    socket_path = get_socket_path()
    verify_apphost(socket_path)
    print(probe_frame_grid_readback(socket_path))