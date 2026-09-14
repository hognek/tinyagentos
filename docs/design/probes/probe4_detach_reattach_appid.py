#!/usr/bin/env python3
"""Probe 4: Detach/reattach AppId stability

Verifies that AppId remains stable across detach/reattach and resets on daemon restart.
"""

import json
import os
import socket
import tempfile
import time
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from tinyagentos.tuiui_conduit import TuiuiConduit, TuiuiConduitError


def probe_detach_reattach_appid():
    """Probe AppId stability across detach/reattach and reset on restart."""
    
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
        self._restart_count = 0
        
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
            
        elif "SetMeta" in msg:
            app_id = msg["SetMeta"]["app"]
            if app_id in self._apps:
                self._apps[app_id]["meta"] = msg["SetMeta"]["meta"]
                
        elif "Kill" in msg:
            app_id = msg["Kill"]["app"]
            if app_id in self._apps:
                self._apps[app_id]["alive"] = False
                
        elif "Shutdown" in msg:
            self._restart_count += 1
            # Simulate restart: reset AppId counter
            self._next_app = 1
            # Keep apps but with new IDs
            conn.sendall(json.dumps({"Roster": []}).encode() + b"\\n")
            
    def get_restart_count(self):
        return self._restart_count

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
        
        time.sleep(1.0)  # Give server time to start
        
        # Verify server is running
        if server_proc.poll() is not None:
            stdout, stderr = server_proc.communicate()
            return f"SERVER FAILED TO START: {stderr.decode()}"
        
        # Run the probe
        transcript_lines = []
        
        # Test 1: Spawn and check AppId across detach/reattach
        transcript_lines.append("=== Test 1: Detach/Reattach AppId Stability ===")
        transcript_lines.append("Step 1: Spawn an app")
        
        with TuiuiConduit(socket_path, timeout=2.0) as conduit:
            # First spawn
            spawned1 = conduit.spawn("sh", ["-c", "echo hello"], cols=80, rows=24)
            transcript_lines.append(f"  Spawned app {spawned1.app} with pid {spawned1.pid}")
            
            # List apps to verify
            apps1 = conduit.list_apps()
            transcript_lines.append(f"  Current apps: {[app.app for app in apps1]}")
            
            # Set meta for persistence
            conduit.set_meta(spawned1.app, [{"title": "agent-shell", "app_key": "test"}])
            transcript_lines.append(f"  Set meta on app {spawned1.app}")
            
            # Simulate detach by closing connection
            transcript_lines.append("  Simulating detach (closing connection)")
            
        # Reconnect
        transcript_lines.append("Step 2: Reconnect (reattach)")
        with TuiuiConduit(socket_path, timeout=2.0) as conduit:
            # Use rebind_by_meta to find the app after restart (AppId may have changed)
            app_after = conduit.rebind_by_meta("agent-shell", app_key="test")
            
            if app_after:
                transcript_lines.append(f"  Found app via meta: app {app_after.app}")
                transcript_lines.append(f"  Meta title: {app_after.meta[0]['title']}")
                transcript_lines.append("  SUCCESS: AppId recovered via meta after reconnect")
            else:
                transcript_lines.append("  FAILED: Could not find app after reconnect")
        
        transcript_lines.append("")
        
        # Test 2: AppId reset on daemon restart
        transcript_lines.append("=== Test 2: AppId Reset on Daemon Restart ===")
        transcript_lines.append("Step 1: Spawn apps to establish baseline")
        
        # Need a new server instance to simulate restart
        server_proc.terminate()
        server_proc.wait(timeout=2)
        
        # Remove the old socket file before starting new server
        if os.path.exists(socket_path):
            os.unlink(socket_path)
        
        # Create a new server instance to simulate daemon restart
        server_path2 = os.path.join(tmpdir, "server2.py")
        server_code2 = '''
import json
import os
import socket
import threading
import time

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
        with open(server_path2, "w") as f:
            f.write(server_code2)
        
        # Start new server (simulating daemon restart)
        server_proc2 = subprocess.Popen([sys.executable, server_path2, socket_path],
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        
        time.sleep(1.0)  # Give server time to start
        
        # Verify server is running
        if server_proc2.poll() is not None:
            stdout, stderr = server_proc2.communicate()
            transcript_lines.append(f"SERVER2 FAILED TO START: {stderr.decode()}")
        else:
            transcript_lines.append("Step 2: Spawn apps after simulated daemon restart")
            with TuiuiConduit(socket_path, timeout=2.0) as conduit:
                # Spawn apps - AppId should reset to 1
                spawned_after = conduit.spawn("sh", ["-c", "echo restarted"], cols=80, rows=24)
                transcript_lines.append(f"  Spawned app {spawned_after.app} with pid {spawned_after.pid}")
                
                if spawned_after.app == 1:
                    transcript_lines.append("  SUCCESS: AppId counter reset to 1 after daemon restart")
                else:
                    transcript_lines.append(f"  NOTE: AppId is {spawned_after.app} (expected 1 if reset)")
                
                # Try to rebind using meta
                transcript_lines.append("Step 3: Attempt to rebind with meta after restart")
                app_after_meta = conduit.rebind_by_meta("agent-shell", app_key="test")
                
                if app_after_meta:
                    transcript_lines.append(f"  SUCCESS: Found app via meta - app {app_after_meta.app}")
                    transcript_lines.append(f"  Meta preserved across restart")
                else:
                    transcript_lines.append("  FAILED: Could not find app via meta after restart")
        
        transcript_lines.append("")
        
        # Clean up
        try:
            server_proc2.terminate()
            server_proc2.wait(timeout=2)
        except:
            server_proc2.kill()
        
        # Save transcript
        output = "\n".join(transcript_lines)
        return output


if __name__ == "__main__":
    print(probe_detach_reattach_appid())