#!/usr/bin/env python3
"""Probe 1: socket enumerate/spawn

Verifies the tuiui apphost Unix socket protocol for listing apps and spawning new ones.
"""

import json
import os
import socket
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
    # Fallback to default for convenience when running manually
    from tinyagentos.tuiui_conduit import default_socket_path
    return default_socket_path()


def verify_apphost(socket_path: str) -> None:
    """Verify the apphost socket exists and answers ListApps.

    Exits with code 2 and prints 'could not run:' message if verification fails.
    """
    # Check socket exists
    if not os.path.exists(socket_path):
        print(f"could not run: no tuiui apphost at {socket_path} (socket does not exist)")
        sys.exit(2)

    # Check it's a socket
    if not os.path.isfile(socket_path):
        # lstat to detect symlinks standing in for sockets
        import stat
        try:
            st = os.lstat(socket_path)
            if not stat.S_ISSOCK(st.st_mode):
                print(f"could not run: no tuiui apphost at {socket_path} (not a socket)")
                sys.exit(2)
        except OSError as e:
            print(f"could not run: no tuiui apphost at {socket_path} (cannot stat: {e})")
            sys.exit(2)

    # Try to connect and run ListApps
    try:
        with TuiuiConduit(socket_path, timeout=2.0) as conduit:
            conduit.list_apps()
    except TuiuiConduitError as e:
        print(f"could not run: no tuiui apphost at {socket_path} ({e})")
        sys.exit(2)
    except OSError as e:
        print(f"could not run: no tuiui apphost at {socket_path} (connection failed: {e})")
        sys.exit(2)


def probe_socket_enumerate_spawn(socket_path: str) -> str:
    """Probe the ListApps and Spawn functionality over the Unix socket."""
    transcript_lines = []

    # Test 1: ListApps when no apps are running
    transcript_lines.append("=== Test 1: ListApps (empty) ===")
    with TuiuiConduit(socket_path, timeout=2.0) as conduit:
        apps = conduit.list_apps()

    transcript_lines.append(f"Result: {len(apps)} apps")
    for app in apps:
        transcript_lines.append(f"  App {app.app}: cmd={app.cmd}, pid={app.pid}, alive={app.alive}")

    transcript_lines.append("")

    # Test 2: Spawn a new app
    transcript_lines.append("=== Test 2: Spawn ===")
    with TuiuiConduit(socket_path, timeout=2.0) as conduit:
        spawned = conduit.spawn("sh", ["-c", "echo hello"], cols=80, rows=24)

    transcript_lines.append(f"Result: spawned app {spawned.app} with pid {spawned.pid}")

    transcript_lines.append("")

    # Test 3: ListApps after spawning
    transcript_lines.append("=== Test 3: ListApps (with app) ===")
    with TuiuiConduit(socket_path, timeout=2.0) as conduit:
        apps = conduit.list_apps()

    transcript_lines.append(f"Result: {len(apps)} apps")
    for app in apps:
        transcript_lines.append(f"  App {app.app}: cmd={app.cmd}, pid={app.pid}, alive={app.alive}")

    transcript_lines.append("")

    # Test 4: Send input to spawned app
    transcript_lines.append("=== Test 4: Send Input ===")
    with TuiuiConduit(socket_path, timeout=2.0) as conduit:
        try:
            conduit.send_input(spawned.app, b"hello")
            transcript_lines.append("Result: Input sent successfully")
        except Exception as e:
            transcript_lines.append(f"Result: Failed - {e}")

    transcript_lines.append("")

    return "\n".join(transcript_lines)


if __name__ == "__main__":
    socket_path = get_socket_path()
    verify_apphost(socket_path)
    print(probe_socket_enumerate_spawn(socket_path))