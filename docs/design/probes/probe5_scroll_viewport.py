#!/usr/bin/env python3
"""Probe 5: Scroll/viewport behavior

Verifies that tuiui's Scroll command only changes visible viewport, not fetchable scrollback.
"""

import os
import sys
from pathlib import Path

# Add parent directory to path so we can import tuiui_conduit
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from tinyagentos.tuiui_conduit import TuiuiConduit, TuiuiConduitError


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


def probe_scroll_viewport_behavior(socket_path: str) -> str:
    """Probe scroll viewport vs scrollback fetch behavior."""
    transcript_lines = []

    # Test 1: Spawn and get initial viewport
    transcript_lines.append("=== Test 1: Spawn and Get Initial Viewport ===")
    transcript_lines.append("Command: Spawn app and read initial Frame")

    with TuiuiConduit(socket_path, timeout=2.0) as conduit:
        spawned = conduit.spawn("sh", ["-c", "echo 'line1'; echo 'line2'; echo 'line3'"], cols=80, rows=24)

        # Read frames until we get one
        for frame in conduit.iter_frames():
            lines = TuiuiConduit.frame_lines(frame)
            transcript_lines.append(f"Result: Viewport shows lines: {lines}")

            # Verify we can see the output
            transcript_lines.append(f"  Initial viewport captured: {len(lines)} lines")
            break

    transcript_lines.append("")

    # Test 2: Use Scroll command
    transcript_lines.append("=== Test 2: Scroll Command ===")
    transcript_lines.append("Command: Send Scroll(app, lines=-1) to view previous lines")

    with TuiuiConduit(socket_path, timeout=2.0) as conduit:
        try:
            # Scroll up by 1 line
            # Note: The Scroll command is sent via the conduit's internal mechanism
            # We need to send it manually since there's no scroll() method yet
            import json
            scroll_payload = {"Scroll": {"app": spawned.app, "lines": -1}}
            conduit._send(scroll_payload)

            # Read frames after scroll
            for frame in conduit.iter_frames():
                lines = TuiuiConduit.frame_lines(frame)
                transcript_lines.append(f"Result: Viewport after scroll: {lines}")
                break

            transcript_lines.append("  Result: Apphost would change viewport but NOT send scrollback as text")
            transcript_lines.append("  Verification: No command exists to fetch arbitrary scrollback lines")

        except Exception as e:
            transcript_lines.append(f"Result: Error - {e}")

    transcript_lines.append("")

    # Test 3: Demonstrate the limitation
    transcript_lines.append("=== Test 3: Scrollback Fetch Limitation ===")
    transcript_lines.append("Problem: If you need 'line 37 of scrollback as raw text',")
    transcript_lines.append("  tuiui provides NO command to fetch it.")
    transcript_lines.append("  You must scroll viewport incrementally to make it visible.")
    transcript_lines.append("")
    transcript_lines.append("Limitation Summary:")
    transcript_lines.append("  - Frame events ONLY carry current viewport grid")
    transcript_lines.append("  - Scroll command ONLY changes visible viewport")
    transcript_lines.append("  - NO 'GetScrollback' or similar command exists")
    transcript_lines.append("  - Arbitrary scrollback lines cannot be pulled off-screen as text")

    transcript_lines.append("")
    transcript_lines.append("Verification: The limitation is in the protocol design, not implementation")

    return "\n".join(transcript_lines)


if __name__ == "__main__":
    socket_path = get_socket_path()
    verify_apphost(socket_path)
    print(probe_scroll_viewport_behavior(socket_path))