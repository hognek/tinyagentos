"""macOS launchd plist migration for Settings updates.

This module provides a pure function to migrate old bare-uvicorn plists
(from pre-#3313 installs) to use the package entrypoint `python -m tinyagentos`.

The migration is necessary because only the package entrypoint starts the
LLM gateway's agent listener and sets app.state.llm_gateway_agent_port.
A bare-uvicorn controller has no verified gateway port, so local agent
deploys are refused.
"""

from __future__ import annotations

import logging
import plistlib
from pathlib import Path

logger = logging.getLogger(__name__)

PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / "com.tinyagentos.controller.plist"


def _is_tinyagentos_controller_plist(plist: dict) -> bool:
    """Check if this is the tinyagentos controller plist."""
    return plist.get("Label") == "com.tinyagentos.controller"


def _is_old_uvicorn_format(program_args: list[str]) -> bool:
    """Detect if ProgramArguments uses bare uvicorn (old format)."""
    if not program_args:
        return False
    # Check for uvicorn in any argument
    for arg in program_args:
        if arg.endswith("uvicorn") or "tinyagentos.app:" in arg:
            return True
    return False


def _is_already_migrated(program_args: list[str]) -> bool:
    """Check if ProgramArguments already uses the module entrypoint."""
    return (
        len(program_args) >= 3
        and program_args[0].endswith(".venv/bin/python")
        and program_args[1] == "-m"
        and program_args[2] == "tinyagentos"
    )


def _extract_host_port_from_args(program_args: list[str]) -> tuple[str | None, str | None]:
    """Extract --host and --port values from uvicorn command line args."""
    host = None
    port = None

    i = 0
    while i < len(program_args):
        arg = program_args[i]
        if arg.startswith("--host="):
            host = arg.split("=", 1)[1]
        elif arg == "--host" and i + 1 < len(program_args):
            host = program_args[i + 1]
            i += 1
        elif arg.startswith("--port="):
            port = arg.split("=", 1)[1]
        elif arg == "--port" and i + 1 < len(program_args):
            port = program_args[i + 1]
            i += 1
        i += 1

    return host, port


def migrate_launchd_plist(plist_bytes: bytes, install_dir: str) -> bytes | None:
    """Migrate an old bare-uvicorn launchd plist to the new module entrypoint format.

    This is a pure function (bytes in, bytes out or None) for testability on Linux CI.

    Parameters
    ----------
    plist_bytes:
        Raw plist data as bytes (XML format).
    install_dir:
        The installation directory (used to construct the venv python path).

    Returns
    -------
    bytes | None
        New plist bytes if migration was needed, None if already migrated
        or not a tinyagentos controller plist.

    Notes
    -----
    - Uses plistlib, not regex, for robust XML parsing.
    - Preserves ALL other keys and environment variables unchanged.
    - Extracts --host/--port from old ProgramArguments and sets TAOS_HOST/TAOS_PORT.
    - Keeps a .bak copy and writes atomically (caller responsibility).
    """
    try:
        plist = plistlib.loads(plist_bytes)
    except Exception:
        # Invalid plist - log and return None (safety: don't corrupt unknown plists)
        logger.debug("launchd migration: invalid plist data, skipping")
        return None

    # Only migrate our controller plist
    if not _is_tinyagentos_controller_plist(plist):
        return None

    program_args = plist.get("ProgramArguments", [])

    # Already migrated?
    if _is_already_migrated(program_args):
        return None

    # Not an old uvicorn format?
    if not _is_old_uvicorn_format(program_args):
        return None

    # Extract host/port from old args
    host, port = _extract_host_port_from_args(program_args)
    host = host or "0.0.0.0"
    port = port or "6969"

    # Build new ProgramArguments
    venv_python = f"{install_dir}/.venv/bin/python"
    new_program_args = [venv_python, "-m", "tinyagentos"]

    # Update EnvironmentVariables with TAOS_HOST/TAOS_PORT
    env_vars = plist.get("EnvironmentVariables", {})
    new_env_vars = dict(env_vars)  # Preserve all existing env vars
    new_env_vars["TAOS_HOST"] = host
    new_env_vars["TAOS_PORT"] = str(port)

    # Build new plist preserving ALL other keys
    new_plist = dict(plist)
    new_plist["ProgramArguments"] = new_program_args
    new_plist["EnvironmentVariables"] = new_env_vars

    logger.info(
        "launchd migration: migrated com.tinyagentos.controller.plist from bare uvicorn "
        "to `python -m tinyagentos` (host=%s, port=%s)",
        host,
        port,
    )

    return plistlib.dumps(new_plist, fmt=plistlib.FMT_XML)


async def apply_launchd_migration(install_dir: str) -> tuple[bool, str | None]:
    """Apply the launchd plist migration on Darwin.

    This is the async wrapper that handles file I/O, atomic write, backup,
    and launchctl reload. Called from the Settings update path.

    Parameters
    ----------
    install_dir:
        The installation directory.

    Returns
    -------
    tuple[bool, str | None]
        (success, error_message). success=True means migration applied or not needed.
        error_message is None on success, or a warning message on failure.
    """
    import sys

    if sys.platform != "darwin":
        return True, None

    plist_path = PLIST_PATH
    if not plist_path.exists():
        return True, None

    try:
        # Read current plist
        plist_bytes = plist_path.read_bytes()

        # Attempt migration
        new_plist_bytes = migrate_launchd_plist(plist_bytes, install_dir)

        if new_plist_bytes is None:
            # Already migrated or not applicable
            return True, None

        # Write atomically: temp file + rename, keep .bak
        bak_path = plist_path.with_suffix(".plist.bak")
        tmp_path = plist_path.with_suffix(".plist.tmp")

        # Backup current
        plist_path.replace(bak_path)

        # Write new
        tmp_path.write_bytes(new_plist_bytes)
        tmp_path.replace(plist_path)

        # Reload launchd agent
        import asyncio

        proc = await asyncio.create_subprocess_exec(
            "launchctl", "bootout", f"gui/{Path.home().owner()}", str(plist_path),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()

        proc = await asyncio.create_subprocess_exec(
            "launchctl", "bootstrap", f"gui/{Path.home().owner()}", str(plist_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()

        if proc.returncode != 0:
            # Try unload/load as fallback
            proc = await asyncio.create_subprocess_exec(
                "launchctl", "unload", str(plist_path),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.wait()
            proc = await asyncio.create_subprocess_exec(
                "launchctl", "load", str(plist_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()

        if proc.returncode != 0:
            err = stderr.decode() if stderr else "unknown error"
            logger.warning("launchd migration: reload failed: %s", err)
            return True, f"plist migrated but launchctl reload failed: {err}"

        return True, None

    except Exception as e:
        logger.warning("launchd migration failed: %s", e)
        return True, f"launchd migration failed: {e}"


def _maybe_migrate_launchd_plist(plist_bytes: bytes, install_dir: str) -> bytes | None:
    """Platform-gated migration function for testability.

    On Darwin, calls migrate_launchd_plist. On other platforms, returns None.
    This allows the update path to call it unconditionally while the Darwin
    gate is tested via monkeypatch.
    """
    import sys

    if sys.platform != "darwin":
        return None
    return migrate_launchd_plist(plist_bytes, install_dir)