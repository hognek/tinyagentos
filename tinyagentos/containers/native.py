"""Native (bare-metal) container backend.

Runs agent workloads directly on the host without container overhead.
Useful on constrained nodes where container runtimes (Docker, Incus)
are too heavy, such as CPU-only Qwen3-Embedding-8B deployments.

Selected when ``container_runtime`` is explicitly set to ``"native"``
in the taOS config.  Not auto-detected — bare metal is always available
on a Linux host, so detecting it unconditionally would shadow LXC/Docker.
"""

from __future__ import annotations

import asyncio
import logging
import os
import pty
import select
import shlex
import shutil
import signal
import subprocess
from pathlib import Path

from .backend import ContainerBackend, ContainerInfo, PtyHandle, _parse_memory

logger = logging.getLogger(__name__)

_SYSTEMD_DIR = Path("/etc/systemd/system")


class _NativePtyHandle(PtyHandle):
    """PtyHandle backed by a subprocess on the native host."""

    def __init__(self, proc: subprocess.Popen, master_fd: int) -> None:
        self._proc = proc
        self._master_fd = master_fd

    def read(self, size: int = 4096) -> bytes:
        ready, _, _ = select.select([self._master_fd], [], [], 0.1)
        if ready:
            return os.read(self._master_fd, size)
        return b""

    def write(self, data: bytes) -> None:
        os.write(self._master_fd, data)

    def resize(self, rows: int, cols: int) -> None:
        import fcntl
        import struct
        import termios
        winsize = struct.pack("HHHH", rows, cols, 0, 0)
        fcntl.ioctl(self._master_fd, termios.TIOCSWINSZ, winsize)

    def close(self) -> None:
        try:
            self._proc.send_signal(signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            os.close(self._master_fd)
        except OSError:
            pass
        self._proc.wait(timeout=5)


async def _run(cmd: list[str], timeout: int = 120) -> tuple[int, str]:
    """Run a command on the host and return (returncode, output)."""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    return proc.returncode or 0, stdout.decode() if stdout else ""


def _service_unit_path(name: str) -> Path:
    """Return the systemd service unit path for a container name."""
    return _SYSTEMD_DIR / f"{name}.service"


def _has_systemd() -> bool:
    """Return True if systemd is available on this host."""
    return shutil.which("systemctl") is not None


class NativeBackend(ContainerBackend):
    """Container backend that runs workloads directly on the bare-metal host.

    Each "container" is a systemd service unit named after the container
    (e.g. ``taos-agent-foo.service``).  Commands run directly on the host
    via subprocess — no container isolation.  This is intended for
    single-purpose constrained nodes where every cycle counts.

    When systemd is not available (container-in-container, CI), falls back
    to a simple subprocess-pid tracking approach for ``list_containers``
    and treats ``start/stop/destroy`` as no-ops with a warning.
    """

    # ------------------------------------------------------------------
    # list_containers
    # ------------------------------------------------------------------

    async def list_containers(self, prefix: str = "taos-agent-") -> list[ContainerInfo]:
        """List systemd services whose name starts with *prefix*."""
        if not _has_systemd():
            return await self._list_containers_fallback(prefix)
        code, output = await _run(
            ["systemctl", "list-units", "--type=service", "--all",
             "--no-legend", "--no-pager", f"{prefix}*"],
            timeout=15,
        )
        if code != 0:
            logger.warning("systemctl list-units failed: %s", output)
            return []
        results: list[ContainerInfo] = []
        for line in output.splitlines():
            parts = line.split()
            if len(parts) < 4:
                continue
            unit = parts[0]
            # strip .service suffix to get container name
            name = unit[:-len(".service")] if unit.endswith(".service") else unit
            if not name.startswith(prefix):
                continue
            status = parts[3]  # ACTIVE: active, inactive, failed, etc.
            # Map systemd states to container-ish statuses
            if status == "active":
                mapped = "Running"
            elif status == "inactive":
                mapped = "Stopped"
            elif status == "failed":
                mapped = "Stopped"
            else:
                mapped = status.capitalize()
            results.append(ContainerInfo(
                name=name,
                status=mapped,
                ip="127.0.0.1",   # bare metal — always reachable at localhost
                memory_mb=0,
                cpu_cores=0,
            ))
        return results

    async def _list_containers_fallback(
        self, prefix: str = "taos-agent-",
    ) -> list[ContainerInfo]:
        """Fallback when systemd is unavailable: probe /etc/systemd/system."""
        results: list[ContainerInfo] = []
        if not _SYSTEMD_DIR.exists():
            return results
        for unit_file in sorted(_SYSTEMD_DIR.glob(f"{prefix}*.service")):
            name = unit_file.stem  # strip .service
            if not name.startswith(prefix):
                continue
            results.append(ContainerInfo(
                name=name,
                status="Stopped",
                ip="127.0.0.1",
                memory_mb=0,
                cpu_cores=0,
            ))
        return results

    # ------------------------------------------------------------------
    # set_root_quota
    # ------------------------------------------------------------------

    async def set_root_quota(self, name: str, size_gib: int) -> dict:
        """Disk quotas are not enforced on bare metal.

        Returns success=True with an advisory note so callers don't block."""
        return {
            "success": True,
            "note": "disk quota not enforced on bare metal; OS-managed filesystem",
        }

    # ------------------------------------------------------------------
    # create_container
    # ------------------------------------------------------------------

    async def create_container(
        self,
        name: str,
        image: str = "images:debian/bookworm",
        memory_limit: str | None = None,
        cpu_limit: int | None = None,
        mounts: list[tuple[str, str]] | None = None,
        env: dict[str, str] | None = None,
        host_uid: int | None = None,
        root_size_gib: int | None = None,
    ) -> dict:
        """Create a systemd service unit for the agent.

        The created unit is a stub — the deployer is expected to follow
        up with ``push_file`` and ``exec_in_container`` to install the
        agent payload and start it.  The ``image`` parameter is ignored
        on bare metal (the host *is* the image).

        Returns ``{"success": True, "name": name}`` on success.
        """
        if not _has_systemd():
            return {
                "success": True,
                "name": name,
                "note": "systemd not available; bare-metal agent runs directly",
            }

        unit_path = _service_unit_path(name)
        # Build environment lines
        env_lines = ""
        for key, value in (env or {}).items():
            env_lines += f"Environment={key}={value}\n"

        memory_limit_line = ""
        if memory_limit is not None:
            memory_limit_line = f"MemoryLimit={memory_limit}\n"

        cpu_limit_line = ""
        if cpu_limit is not None:
            cpu_limit_line = f"CPUQuota={cpu_limit * 100}%\n"

        unit_content = f"""[Unit]
Description=taOS Agent: {name}
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/bin/true
Restart=no
{memory_limit_line}{cpu_limit_line}{env_lines}
[Install]
WantedBy=multi-user.target
"""

        try:
            _SYSTEMD_DIR.mkdir(parents=True, exist_ok=True)
            unit_path.write_text(unit_content)
            code, output = await _run(["systemctl", "daemon-reload"], timeout=15)
            if code != 0:
                logger.warning("daemon-reload failed: %s", output)
                # Not fatal — the unit is still on disk.
        except OSError as exc:
            logger.error("Failed to write unit file %s: %s", unit_path, exc)
            return {"success": False, "error": str(exc)}

        logger.info("bare-metal: created systemd unit %s", name)
        return {"success": True, "name": name}

    # ------------------------------------------------------------------
    # exec_in_container
    # ------------------------------------------------------------------

    async def exec_in_container(
        self, name: str, cmd: list[str], timeout: int = 300
    ) -> tuple[int, str]:
        """Execute a command directly on the host.

        The *name* parameter is ignored — all commands run on the bare
        host with no isolation.
        """
        return await _run(cmd, timeout=timeout)

    # ------------------------------------------------------------------
    # push_file
    # ------------------------------------------------------------------

    async def push_file(
        self, name: str, local_path: str, remote_path: str
    ) -> tuple[int, str]:
        """Copy a file to the host filesystem.

        The *name* parameter is ignored — files are copied directly.
        ``remote_path`` is an absolute host path.
        """
        try:
            remote_dir = os.path.dirname(remote_path)
            if remote_dir:
                os.makedirs(remote_dir, exist_ok=True)
            shutil.copy2(local_path, remote_path)
            return 0, ""
        except OSError as exc:
            return 1, str(exc)

    # ------------------------------------------------------------------
    # start / stop / restart / destroy
    # ------------------------------------------------------------------

    async def start_container(self, name: str) -> dict:
        """Start the systemd service for *name*."""
        if not _has_systemd():
            return {"success": True, "output": "systemd not available; service not started"}
        unit_path = _service_unit_path(name)
        if not unit_path.exists():
            return {"success": False, "output": f"unit {name}.service not found"}
        code, output = await _run(["systemctl", "start", f"{name}.service"], timeout=30)
        return {"success": code == 0, "output": output}

    async def stop_container(self, name: str, force: bool = False) -> dict:
        """Stop the systemd service for *name*."""
        if not _has_systemd():
            return {"success": True, "output": "systemd not available"}
        cmd = ["systemctl", "stop", f"{name}.service"]
        if force:
            cmd.insert(1, "--force")
        code, output = await _run(cmd, timeout=30)
        return {"success": code == 0, "output": output}

    async def restart_container(self, name: str) -> dict:
        """Restart the systemd service for *name*."""
        if not _has_systemd():
            return {"success": True, "output": "systemd not available"}
        code, output = await _run(
            ["systemctl", "restart", f"{name}.service"], timeout=30,
        )
        return {"success": code == 0, "output": output}

    async def destroy_container(self, name: str) -> dict:
        """Stop and delete the systemd unit for *name*."""
        if not _has_systemd():
            return {"success": True, "output": "systemd not available"}
        unit_path = _service_unit_path(name)
        # Stop first
        await _run(["systemctl", "stop", f"{name}.service"], timeout=30)
        # Disable
        await _run(["systemctl", "disable", f"{name}.service"], timeout=30)
        # Remove unit file
        try:
            unit_path.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("Failed to remove unit %s: %s", unit_path, exc)
        await _run(["systemctl", "daemon-reload"], timeout=15)
        return {"success": True, "output": f"destroyed {name}"}

    # ------------------------------------------------------------------
    # get_container_logs
    # ------------------------------------------------------------------

    async def get_container_logs(self, name: str, lines: int = 100) -> str:
        """Get recent journalctl logs for the service."""
        if not _has_systemd():
            return "systemd not available; no logs"
        code, output = await _run(
            ["journalctl", "--no-pager", "-n", str(lines),
             "-u", f"{name}.service"],
            timeout=30,
        )
        return output if code == 0 else f"Error getting logs: {output}"

    # ------------------------------------------------------------------
    # rename_container
    # ------------------------------------------------------------------

    async def rename_container(self, old_name: str, new_name: str) -> dict:
        """Rename the systemd service unit file."""
        if not _has_systemd():
            return {"success": True, "output": "systemd not available"}
        old_path = _service_unit_path(old_name)
        new_path = _service_unit_path(new_name)
        if not old_path.exists():
            return {"success": False, "output": f"unit {old_name}.service not found"}
        try:
            old_path.rename(new_path)
            await _run(["systemctl", "daemon-reload"], timeout=15)
            return {"success": True, "output": f"renamed {old_name} -> {new_name}"}
        except OSError as exc:
            return {"success": False, "output": str(exc)}

    # ------------------------------------------------------------------
    # add_proxy_device
    # ------------------------------------------------------------------

    async def add_proxy_device(
        self, name: str, device_name: str, listen: str, connect: str,
        bind_mode: str | None = None,
    ) -> dict:
        """No-op on bare metal — everything is localhost already."""
        return {"success": True, "output": "proxy devices not needed on bare metal"}

    # ------------------------------------------------------------------
    # snapshots
    # ------------------------------------------------------------------

    async def snapshot_create(self, name: str, snapshot_name: str) -> dict:
        """Snapshots not supported on bare metal."""
        return {
            "success": False,
            "output": "",
            "note": "snapshots not supported on bare metal; use host-level backup tools",
        }

    async def snapshot_restore(self, name: str, snapshot_name: str) -> dict:
        """Snapshots not supported on bare metal."""
        return {
            "success": False,
            "output": "",
            "note": "snapshots not supported on bare metal",
        }

    async def snapshot_list(self, name: str) -> dict:
        """Snapshots not supported on bare metal."""
        return {"success": False, "snapshots": [], "output": "not supported on bare metal"}

    # ------------------------------------------------------------------
    # spawn_pty
    # ------------------------------------------------------------------

    def spawn_pty(self, name: str, cmd: list[str] | None = None) -> PtyHandle:
        """Open an interactive PTY directly on the host.

        *name* is ignored — the PTY runs on the bare host.
        """
        master_fd, slave_fd = pty.openpty()
        shell_cmd = "exec bash -l" if cmd is None else " ".join(shlex.quote(c) for c in cmd)
        proc = subprocess.Popen(
            ["bash", "-lc", shell_cmd],
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            close_fds=True,
        )
        os.close(slave_fd)
        return _NativePtyHandle(proc, master_fd)

    # ------------------------------------------------------------------
    # set_env
    # ------------------------------------------------------------------

    async def set_env(self, name: str, key: str, value: str) -> dict:
        """Update an Environment= line in the systemd service unit.

        Systemd does not support hot-reload of environment variables on a
        running service — the service must be restarted to pick up the
        change.  The unit file is updated in-place and daemon-reloaded.
        """
        if not _has_systemd():
            return {
                "success": True,
                "output": "systemd not available; env not persisted",
            }
        unit_path = _service_unit_path(name)
        if not unit_path.exists():
            return {"success": False, "output": f"unit {name}.service not found"}

        try:
            content = unit_path.read_text()
        except OSError as exc:
            return {"success": False, "output": str(exc)}

        # Replace existing Environment= line for this key, or add new one
        env_line = f"Environment={key}={value}"
        old_prefix = f"Environment={key}="
        if old_prefix in content:
            # Replace the existing line
            lines = content.splitlines()
            new_lines = []
            for line in lines:
                if line.strip().startswith(old_prefix):
                    new_lines.append(env_line)
                else:
                    new_lines.append(line)
            content = "\n".join(new_lines) + "\n"
        else:
            # Insert before [Install] or at end
            if "\n[Install]" in content:
                content = content.replace("\n[Install]", f"\n{env_line}\n[Install]")
            else:
                content = content.rstrip("\n") + f"\n{env_line}\n"

        try:
            unit_path.write_text(content)
            await _run(["systemctl", "daemon-reload"], timeout=15)
        except OSError as exc:
            return {"success": False, "output": str(exc)}

        return {"success": True, "output": f"set {key}={value} in {name}.service"}
