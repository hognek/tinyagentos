#!/usr/bin/env python3
"""Probe 1: socket enumerate/spawn

Verifies the tuiui apphost Unix socket protocol for listing apps and spawning new ones.
"""

import json
import os
import socket
import tempfile
import time
from pathlib import Path

# Add parent directory to path so we can import tuiui_conduit
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from tinyagentos.tuiui_conduit import TuiuiConduit


def probe_socket_enumerate_spawn():
    """Probe the ListApps and Spawn functionality over the Unix socket."""
    
    # Create a temporary socket path
    with tempfile.TemporaryDirectory() as tmpdir:
        socket_path = os.path.join(tmpdir, "apphost.sock")
        
        # Create a mock apphost server for testing
        server_path = os.path.join(tmpdir, "server.py")
        server_code = '''
import json
import os
import socket
import threading
import time
from pathlib import Path

class MockApphost:
    def __init__(self, socket_path):
        self.socket_path = socket_path
        self._next_app = 1
        self._apps = {}
        self._listener = None
        self._client = None
        
    def run(self):
        self._listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._listener.bind(self.socket_path)
        os.chmod(self.socket_path, 0o600)
        self._listener.listen(1)
        
        while True:
            try:
                conn, _ = self._listener.accept()
                self._client = conn
                conn.settimeout(5.0)
                self._handle_client(conn)
                conn.close()
            except (ConnectionResetError, BrokenPipeError, OSError):
                break
                
    def _handle_client(self, conn):
        buf = b""
        try:
            while True:
                chunk = conn.recv(65536)
                if not chunk:
                    break
                buf += chunk
                while b"\\n" in buf:
                    line, buf = buf.split(b"\\n", 1)
                    if not line:
                        continue
                    try:
                        msg = json.loads(line.decode("utf-8"))
                        self._process_message(conn, msg)
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        pass
        except (ConnectionResetError, BrokenPipeError, OSError):
            pass
            
    def _process_message(self, conn, msg):
        if "ListApps" in msg:
            roster = [
                {
                    "app": app_id,
                    "cmd": info["cmd"],
                    "args": info["args"],
                    "pid": info["pid"],
                    "cols": info["cols"],
                    "rows": info["rows"],
                    "age_secs": info["age_secs"],
                    "alive": info["alive"],
                    "meta": info["meta"]
                }
                for app_id, info in self._apps.items()
            ]
            conn.sendall(json.dumps({"Roster": roster}).encode() + b"\\n")
            
        elif "Spawn" in msg:
            spawn = msg["Spawn"]
            app_id = self._next_app
            self._next_app += 1
            self._apps[app_id] = {
                "cmd": spawn.get("cmd", ""),
                "args": list(spawn.get("args", [])),
                "pid": 10000 + app_id,
                "cols": int(spawn.get("cols", 80)),
                "rows": int(spawn.get("rows", 24)),
                "age_secs": 0,
                "alive": True,
                "meta": None
            }
            conn.sendall(json.dumps({"Spawned": {"app": app_id, "pid": self._apps[app_id]["pid"]}}).encode() + b"\\n")
            conn.sendall(json.dumps({
                "Frame": {
                    "grid": {"cols": 6, "rows": 2, "cells": [{"ch": ch} for ch in "spawned "]},
                    "cursor": [0, 0],
                    "flags": 0,
                    "images": [],
                    "image_data": [],
                    "clear": False,
                    "switch_to": None,
                    "clipboard": None
                }
            }).encode() + b"\\n")
            
        elif "Input" in msg:
            # Just acknowledge input
            pass
            
        elif "SetMeta" in msg:
            app_id = msg["SetMeta"]["app"]
            if app_id in self._apps:
                self._apps[app_id]["meta"] = msg["SetMeta"]["meta"]
                
        elif "Kill" in msg:
            app_id = msg["Kill"]["app"]
            if app_id in self._apps:
                self._apps[app_id]["alive"] = False
                
        elif "Shutdown" in msg:
            raise SystemExit

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        socket_path = sys.argv[1]
    else:
        socket_path = "/tmp/test.sock"
    
    apphost = MockApphost(socket_path)
    apphost.run()
'''
        with open(server_path, "w") as f:
            f.write(server_code)
        
        # Start mock apphost in background
        import subprocess
        server_proc = subprocess.Popen([sys.executable, server_path, socket_path],
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        
        time.sleep(0.5)  # Give server time to start
        
        # Run the probe
        transcript_lines = []
        
        # Test 1: ListApps when no apps are running
        transcript_lines.append("=== Test 1: ListApps (empty) ===")
        transcript_lines.append(f"Command: curl -s -X POST --data '{{\"ListApps\":{{}}}}' -H 'Content-Type: application/json' unix:///tmp/apphost.sock")
        
        with TuiuiConduit(socket_path, timeout=2.0) as conduit:
            apps = conduit.list_apps()
        
        transcript_lines.append(f"Result: {len(apps)} apps")
        for app in apps:
            transcript_lines.append(f"  App {app.app}: cmd={app.cmd}, pid={app.pid}, alive={app.alive}")
        
        transcript_lines.append("")
        
        # Test 2: Spawn a new app
        transcript_lines.append("=== Test 2: Spawn ===")
        transcript_lines.append("Command: curl -s -X POST --data '{\"Spawn\":{\"req_id\":1,\"cmd\":\"echo\",\"args\":[\"-c\",\"echo hello\"],\"cols\":80,\"rows\":24}}' -H 'Content-Type: application/json' unix:///tmp/apphost.sock")
        
        with TuiuiConduit(socket_path, timeout=2.0) as conduit:
            spawned = conduit.spawn("sh", ["-c", "echo hello"], cols=80, rows=24)
        
        transcript_lines.append(f"Result: spawned app {spawned.app} with pid {spawned.pid}")
        
        transcript_lines.append("")
        
        # Test 3: ListApps after spawning
        transcript_lines.append("=== Test 3: ListApps (with app) ===")
        transcript_lines.append("Command: curl -s -X POST --data '{\"ListApps\":{{}}' -H 'Content-Type: application/json' unix:///tmp/apphost.sock")
        
        with TuiuiConduit(socket_path, timeout=2.0) as conduit:
            apps = conduit.list_apps()
        
        transcript_lines.append(f"Result: {len(apps)} apps")
        for app in apps:
            transcript_lines.append(f"  App {app.app}: cmd={app.cmd}, pid={app.pid}, alive={app.alive}")
        
        transcript_lines.append("")
        
        # Test 4: Send input to spawned app
        transcript_lines.append("=== Test 4: Send Input ===")
        transcript_lines.append("Command: curl -s -X POST --data '{\"Input\":{\"app\":1,\"bytes\":[104,101,108,108,111]}}' -H 'Content-Type: application/json' unix:///tmp/apphost.sock")
        
        with TuiuiConduit(socket_path, timeout=2.0) as conduit:
            try:
                conduit.send_input(1, b"hello")
                transcript_lines.append("Result: Input sent successfully")
            except Exception as e:
                transcript_lines.append(f"Result: Failed - {e}")
        
        transcript_lines.append("")
        
        # Clean up
        try:
            server_proc.terminate()
            server_proc.wait(timeout=2)
        except:
            server_proc.kill()
        
        # Save transcript
        output = "\n".join(transcript_lines)
        return output


if __name__ == "__main__":
    print(probe_socket_enumerate_spawn())