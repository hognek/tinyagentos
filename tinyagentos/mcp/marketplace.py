"""MCP server marketplace: curated registry + install flow.

taOS ships a large set of *bundled* MCP plugins (see ``app-catalog/plugins/``),
installed through the app Store.  This module adds the other half of the model —
a *marketplace*: a curated registry of community MCP servers a user can browse
and install in one step, the way a code editor installs an extension.

Three pieces, deliberately separable so each can be tested without a network or
a spawned process:

``MCPRegistryManifest``
    The manifest format.  ``id``/``name``/``description``/``version``/``author``
    plus the install command, the run command, and the *permissions the server
    declares it needs*.  Validated at the load boundary with pydantic, exactly
    like ``tinyagentos.registry.AppManifest``: one malformed entry must never
    abort the listing of the rest.

``MCPRegistry``
    A directory of manifests — the shipped curated snapshot
    (``tinyagentos/mcp/registry_data/``).  ``MCPRegistry`` takes the directory as
    a constructor argument, so the same loader reads a mounted or downloaded
    copy of the hosted registry without a code change.

``MCPMarketplace``
    The install flow: resolve a manifest -> optionally run its install command
    -> register a *runnable server config* in ``MCPServerStore``.  The config it
    writes uses the ``cmd`` key that ``MCPSupervisor._resolve_cmd`` already
    reads, so an installed marketplace server is launchable by the existing MCP
    loader with no extra wiring.

Declared permissions vs. access grants
    ``permissions`` on a manifest is a *requirement* the server states about
    itself (``filesystem:write`` means "I write files").  It is what the
    installer validates and records in the server config; it is NOT a grant.
    Who may call which tool stays where it already lives — the attachment model
    in ``MCPServerStore``/``check_permission``.  Keeping the two apart means
    installing a server can never silently widen an agent's access.
"""

from __future__ import annotations

import asyncio
import logging
import re
import shlex
import threading
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterable, Literal

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from tinyagentos.mcp.registry import MCPServerStore

logger = logging.getLogger(__name__)


class InvalidPermissionSet(ValueError):
    """A manifest declared a permission set the runtime does not recognise."""


# The permission vocabulary a marketplace manifest may declare.
#
# Namespaced capabilities take the form ``<area>:<read|write>``; unscoped ones
# are a single word.  Kept small and closed on purpose: an unknown permission is
# rejected rather than ignored, because silently dropping a capability the
# server asked for would install it into an environment it does not expect.
PERMISSION_VOCABULARY: frozenset[str] = frozenset({
    "network",
    "secrets",
    "gpu",
    "container:run",
    "filesystem:read",
    "filesystem:write",
    "database:read",
    "database:write",
})

# Wildcards are refused: a marketplace entry must enumerate what it needs.  The
# whole point of a permission set is that a reviewer can read it, and ``*``
# defeats that while looking shorter.
_WILDCARDS = frozenset({"*", "all", "any", "full"})

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


def validate_permissions(raw: Any) -> list[str]:
    """Validate and normalise a manifest's declared permission set.

    Rules, all of which must hold for the set to be accepted:

    * it is a sequence of non-empty strings;
    * no wildcard (``*``/``all``/``any``/``full``) — enumerate, don't blanket;
    * every entry is in :data:`PERMISSION_VOCABULARY`;
    * a ``<area>:write`` entry requires the matching ``<area>:read`` — asking
      to write data you have not declared the ability to read is almost always
      an authoring mistake, and it is cheaper to catch here than at runtime.

    Returns the sorted, de-duplicated permission list.
    """
    if raw is None:
        return []
    if isinstance(raw, str):
        raise InvalidPermissionSet(
            "permissions must be a list of permission strings, not a string"
        )
    if not isinstance(raw, (list, tuple)):
        raise InvalidPermissionSet(
            f"permissions must be a list, got {type(raw).__name__}"
        )

    normalised: set[str] = set()
    for entry in raw:
        if not isinstance(entry, str) or not entry.strip():
            raise InvalidPermissionSet(
                f"permission entries must be non-empty strings, got {entry!r}"
            )
        perm = entry.strip()
        if perm.lower() in _WILDCARDS:
            raise InvalidPermissionSet(
                f"wildcard permission {perm!r} is not allowed; declare the "
                "specific permissions the server needs"
            )
        if perm not in PERMISSION_VOCABULARY:
            raise InvalidPermissionSet(
                f"unknown permission {perm!r}; known permissions: "
                f"{', '.join(sorted(PERMISSION_VOCABULARY))}"
            )
        normalised.add(perm)

    for perm in sorted(normalised):
        area, _, scope = perm.partition(":")
        if scope == "write" and f"{area}:read" not in normalised:
            raise InvalidPermissionSet(
                f"{perm!r} requires {area + ':read'!r} to also be declared"
            )

    return sorted(normalised)


def _coerce_argv(value: Any, *, field: str) -> list[str]:
    """Coerce a manifest command into an argv list.

    A string is split with :func:`shlex.split` (so ``/path/with space/bin`` can
    be quoted), a list is used as-is.  ``None``/``""`` becomes ``[]``.
    """
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            return shlex.split(text)
        except ValueError as exc:
            raise ValueError(f"{field} is not a valid command line: {exc}") from exc
    if isinstance(value, (list, tuple)):
        argv: list[str] = []
        for item in value:
            if not isinstance(item, str):
                raise ValueError(f"{field} entries must be strings, got {item!r}")
            argv.append(item)
        return argv
    raise ValueError(f"{field} must be a string or a list of strings")


class MCPInstallSpec(BaseModel):
    """How to fetch a marketplace server.

    ``command`` is the install argv (``npm install -g …``, ``pip install …``);
    an entry that needs no fetch step (a single-file script served over stdio,
    a remote URL) leaves it empty and the installer skips straight to
    registration.
    """

    model_config = ConfigDict(extra="ignore")

    method: Literal["npm", "pip", "uvx", "docker", "binary", "script", "none"] = "none"
    package: str = ""
    command: list[str] = Field(default_factory=list)

    @field_validator("command", mode="before")
    @classmethod
    def _coerce_command(cls, value: Any) -> list[str]:
        return _coerce_argv(value, field="install.command")


class MCPRunSpec(BaseModel):
    """How to launch the server once installed.

    For ``stdio`` transports ``command``/``args`` are the argv the supervisor
    spawns.  ``env`` holds non-secret environment defaults; credentials belong
    in the secrets store and are injected at start time, never in a manifest.
    """

    model_config = ConfigDict(extra="ignore")

    command: list[str] = Field(default_factory=list)
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    url: str = ""

    @field_validator("command", mode="before")
    @classmethod
    def _coerce_command(cls, value: Any) -> list[str]:
        return _coerce_argv(value, field="run.command")

    @field_validator("args", mode="before")
    @classmethod
    def _coerce_args(cls, value: Any) -> list[str]:
        return _coerce_argv(value, field="run.args")


class MCPRegistryManifest(BaseModel):
    """A validated entry in the MCP marketplace registry.

    ``extra="ignore"`` keeps the format forward-compatible with newer registry
    fields this runtime has not learned about yet, mirroring ``AppManifest``.
    """

    model_config = ConfigDict(extra="ignore")

    id: str
    name: str
    description: str = ""
    version: str = "0.0.0"
    author: str = ""
    homepage: str = ""
    license: str = ""
    categories: list[str] = Field(default_factory=list)
    transport: Literal["stdio", "sse", "http"] = "stdio"
    permissions: list[str] = Field(default_factory=list)
    install: MCPInstallSpec = Field(default_factory=MCPInstallSpec)
    run: MCPRunSpec = Field(default_factory=MCPRunSpec)
    # Registry-curated entries are reviewed by a maintainer; the flag is
    # surfaced in the browse payload so a UI can badge them.
    verified: bool = False
    manifest_path: Path | None = None

    @field_validator("id")
    @classmethod
    def _check_id(cls, value: str) -> str:
        if not _ID_RE.match(value or ""):
            raise ValueError(
                f"id {value!r} is not a valid marketplace id "
                "(lowercase letters, digits, '.', '_', '-' — must start alphanumeric)"
            )
        return value

    @field_validator("version", mode="before")
    @classmethod
    def _coerce_version(cls, value: Any) -> str:
        if isinstance(value, bool):
            raise ValueError("version must be a string")
        if isinstance(value, (int, float)):
            return str(value)
        if not isinstance(value, str):
            raise ValueError("version must be a string")
        return value

    @field_validator("permissions", mode="before")
    @classmethod
    def _check_permissions(cls, value: Any) -> list[str]:
        return validate_permissions(value)

    @field_validator("categories", mode="before")
    @classmethod
    def _check_categories(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [value.strip()] if value.strip() else []
        if not isinstance(value, (list, tuple)):
            raise ValueError("categories must be a list of strings")
        out: list[str] = []
        for item in value:
            if not isinstance(item, str) or not item.strip():
                raise ValueError("category entries must be non-empty strings")
            out.append(item.strip())
        return out

    @model_validator(mode="after")
    def _check_launchable(self) -> "MCPRegistryManifest":
        if self.transport == "stdio":
            if not self.run.command:
                raise ValueError(
                    "a stdio server needs run.command — there is nothing for "
                    "the MCP supervisor to launch"
                )
        elif not self.run.url:
            raise ValueError(
                f"a {self.transport} server needs run.url"
            )
        return self

    # -- derived views ----------------------------------------------------

    def launch_argv(self) -> list[str]:
        """The full argv the MCP supervisor will execute (stdio only)."""
        return [*self.run.command, *self.run.args]

    def server_config(self) -> dict:
        """The server config row that makes this manifest loadable.

        ``MCPSupervisor._resolve_cmd`` reads ``config["cmd"]`` first and falls
        back to the app catalog, so a config carrying ``cmd`` is launchable by
        the loader as-is.  ``permissions`` rides along as a record of what the
        server declared, and ``env`` supplies non-secret launch defaults.
        """
        config: dict[str, Any] = {
            "source": "marketplace",
            "permissions": list(self.permissions),
        }
        if self.transport == "stdio":
            config["cmd"] = self.launch_argv()
        else:
            config["url"] = self.run.url
        if self.run.env:
            config["env"] = dict(self.run.env)
        return config

    def to_dict(self) -> dict:
        """Browse payload: the manifest fields plus derived launch data."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "author": self.author,
            "homepage": self.homepage,
            "license": self.license,
            "categories": list(self.categories),
            "transport": self.transport,
            "permissions": list(self.permissions),
            "verified": self.verified,
            "install_method": self.install.method,
            "install_package": self.install.package,
            "command": self.launch_argv(),
        }

    # -- construction -----------------------------------------------------

    @classmethod
    def from_dict(cls, data: dict, manifest_path: Path | None = None) -> "MCPRegistryManifest":
        if not isinstance(data, dict):
            raise ValueError("manifest top level is not a mapping")
        return cls.model_validate({**data, "manifest_path": manifest_path})

    @classmethod
    def from_file(cls, path: Path) -> "MCPRegistryManifest":
        """Parse a manifest file, naming the file in any validation error."""
        try:
            data = yaml.safe_load(path.read_text())
        except yaml.YAMLError as exc:
            raise ValueError(f"manifest {path} has invalid YAML: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError(f"manifest {path} top level is not a mapping")
        try:
            return cls.from_dict(data, manifest_path=path)
        except ValidationError:
            logger.warning("manifest %s failed validation", path, exc_info=True)
            raise


def default_registry_dir() -> Path:
    """The curated registry shipped with this build of taOS."""
    return Path(__file__).parent / "registry_data"


def _manifest_files(registry_dir: Path) -> Iterable[Path]:
    """Yield manifest files under *registry_dir* in a stable order.

    Both layouts the app catalog already uses are accepted: a flat
    ``<id>.yaml`` and a per-entry ``<id>/manifest.yaml`` directory.
    """
    if not registry_dir.is_dir():
        return []
    files: list[Path] = []
    for path in sorted(registry_dir.iterdir()):
        if path.is_dir():
            candidate = path / "manifest.yaml"
            if candidate.is_file():
                files.append(candidate)
        elif path.suffix in (".yaml", ".yml"):
            files.append(path)
    return files


class MCPRegistry:
    """A directory of curated MCP marketplace manifests.

    Loading is deferred and guarded by a lock, mirroring ``AppRegistry``: a
    boot does not pay for parsing every manifest, and a concurrent first read
    from two request handlers parses once.  A malformed entry is logged and
    skipped — the rest of the registry still lists — but it is also recorded in
    :attr:`errors` so an operator (or the reload route) can see it instead of
    wondering why an entry is missing.
    """

    def __init__(self, registry_dir: Path):
        self.registry_dir = Path(registry_dir)
        self._manifests: dict[str, MCPRegistryManifest] = {}
        self._errors: list[dict[str, str]] = []
        self._loaded = False
        self._lock = threading.Lock()

    # -- loading ----------------------------------------------------------

    def _read_dir(self) -> tuple[dict[str, MCPRegistryManifest], list[dict[str, str]]]:
        """Parse the registry directory.  Pure — no shared state touched."""
        manifests: dict[str, MCPRegistryManifest] = {}
        errors: list[dict[str, str]] = []
        for path in _manifest_files(self.registry_dir):
            try:
                manifest = MCPRegistryManifest.from_file(path)
            except (ValidationError, ValueError) as exc:
                errors.append({"path": str(path), "error": str(exc)})
                continue
            if manifest.id in manifests:
                errors.append({
                    "path": str(path),
                    "error": f"duplicate id {manifest.id!r} already defined by "
                             f"{manifests[manifest.id].manifest_path}",
                })
                continue
            manifests[manifest.id] = manifest
        return manifests, errors

    def _publish(
        self,
        manifests: dict[str, MCPRegistryManifest],
        errors: list[dict[str, str]],
    ) -> None:
        # Assign under the lock so a reader never sees a half-replaced registry.
        with self._lock:
            self._manifests = manifests
            self._errors = errors
            self._loaded = True

    def load(self) -> None:
        """(Re)read the registry directory."""
        self._publish(*self._read_dir())

    def _ensure_loaded(self) -> None:
        # Double-checked locking, with the parse itself done outside the lock:
        # `load()` takes the same lock, so parsing while holding it would
        # deadlock the first read.
        if self._loaded:
            return
        with self._lock:
            if self._loaded:
                return
        self.load()

    def reload(self) -> None:
        self.load()

    # -- reads ------------------------------------------------------------

    @property
    def errors(self) -> list[dict[str, str]]:
        self._ensure_loaded()
        return list(self._errors)

    def get(self, manifest_id: str) -> MCPRegistryManifest | None:
        self._ensure_loaded()
        return self._manifests.get(manifest_id)

    def list(
        self,
        query: str | None = None,
        category: str | None = None,
    ) -> list[MCPRegistryManifest]:
        """List entries, optionally filtered by free text and/or category.

        The free-text match is a case-insensitive substring over id, name,
        description, author and categories — enough for a search box without
        pulling in a fuzzy matcher.
        """
        self._ensure_loaded()
        results = sorted(self._manifests.values(), key=lambda m: m.name.lower())
        if category:
            wanted = category.strip().lower()
            results = [
                m for m in results
                if any(c.lower() == wanted for c in m.categories)
            ]
        if query:
            needle = query.strip().lower()
            if needle:
                results = [
                    m for m in results
                    if needle in " ".join([
                        m.id, m.name, m.description, m.author,
                        *m.categories,
                    ]).lower()
                ]
        return results

    def categories(self) -> list[str]:
        self._ensure_loaded()
        seen: set[str] = set()
        for manifest in self._manifests.values():
            seen.update(manifest.categories)
        return sorted(seen, key=str.lower)


# An install-command runner: argv -> (returncode, stdout, stderr).
InstallRunner = Callable[[list[str]], Awaitable[tuple[int, str, str]]]


class MCPMarketplaceError(Exception):
    """An install/browse action failed.  ``status_code`` is the HTTP hint."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


async def _subprocess_runner(argv: list[str]) -> tuple[int, str, str]:
    """Default runner: execute the install command and capture its output."""
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate()
    return (
        proc.returncode or 0,
        out.decode(errors="replace"),
        err.decode(errors="replace"),
    )


class MCPMarketplace:
    """Browse the registry and install entries into ``MCPServerStore``.

    The install command is executed through an injectable ``runner`` so the
    flow can be tested end-to-end (manifest -> registered, launchable config)
    without fetching anything from the network.  ``run_install_command=False``
    resolves and registers without executing, which is what a test or a
    dry-run preview uses.
    """

    def __init__(
        self,
        registry: MCPRegistry,
        store: MCPServerStore,
        supervisor: Any | None = None,
        runner: InstallRunner | None = None,
    ):
        self.registry = registry
        self.store = store
        self.supervisor = supervisor
        self._runner: InstallRunner = runner or _subprocess_runner

    # -- browse -----------------------------------------------------------

    def categories(self) -> list[str]:
        return self.registry.categories()

    async def installed_ids(self) -> set[str]:
        return {s["id"] for s in await self.store.list_servers()}

    async def browse(
        self,
        query: str | None = None,
        category: str | None = None,
    ) -> list[dict]:
        """Registry entries annotated with their install/running state."""
        installed = await self.installed_ids()
        entries: list[dict] = []
        for manifest in self.registry.list(query=query, category=category):
            entry = manifest.to_dict()
            entry["installed"] = manifest.id in installed
            entry["running"] = False
            if entry["installed"] and self.supervisor is not None:
                status = self.supervisor.get_status(manifest.id)
                entry["running"] = bool(status.get("running"))
            entries.append(entry)
        return entries

    def get_manifest(self, manifest_id: str) -> MCPRegistryManifest:
        manifest = self.registry.get(manifest_id)
        if manifest is None:
            raise MCPMarketplaceError(
                f"marketplace entry {manifest_id!r} not found", status_code=404
            )
        return manifest

    async def detail(self, manifest_id: str) -> dict:
        manifest = self.get_manifest(manifest_id)
        entry = manifest.to_dict()
        entry["installed"] = False
        entry["running"] = False
        server = await self.store.get_server(manifest_id)
        if server is not None:
            entry["installed"] = True
            entry["installed_version"] = server.get("version", "")
            entry["installed_config"] = server.get("config", {})
            if self.supervisor is not None:
                entry["running"] = bool(
                    self.supervisor.get_status(manifest_id).get("running")
                )
        return entry

    # -- install ----------------------------------------------------------

    async def install(
        self,
        manifest_id: str,
        *,
        run_install_command: bool = True,
    ) -> dict:
        """Resolve a manifest and register a loadable server config for it.

        Raises :class:`MCPMarketplaceError` when the entry is unknown (404),
        already installed (409), or its install command fails (502).  A failed
        install leaves the store untouched — the server is registered only
        after the fetch step succeeded, so a half-installed entry never shows
        up as launchable.
        """
        manifest = self.get_manifest(manifest_id)

        if await self.store.get_server(manifest.id) is not None:
            raise MCPMarketplaceError(
                f"{manifest.id!r} is already installed", status_code=409
            )

        config = manifest.server_config()
        install_output: str | None = None

        if run_install_command and manifest.install.command:
            returncode, stdout, stderr = await self._runner(manifest.install.command)
            if returncode != 0:
                raise MCPMarketplaceError(
                    f"install command for {manifest.id!r} failed "
                    f"(exit {returncode}): {stderr.strip()[:400] or stdout.strip()[:400]}",
                    status_code=502,
                )
            install_output = stdout[-2000:]

        await self.store.register_server(
            manifest.id, manifest.version, manifest.transport, config
        )
        logger.info(
            "mcp marketplace: installed %s v%s (%s, %d declared permissions)",
            manifest.id, manifest.version, manifest.transport,
            len(manifest.permissions),
        )
        return {
            "status": "installed",
            "server_id": manifest.id,
            "version": manifest.version,
            "transport": manifest.transport,
            "config": config,
            "permissions": list(manifest.permissions),
            "install_output": install_output,
        }

    async def uninstall(self, manifest_id: str) -> dict:
        """Remove an installed marketplace server.

        Delegates to the supervisor when one is wired (it also drops the
        server's attachments and any ``mcp:<id>:`` secrets — the "no leftover
        state" half of a clean uninstall), and falls back to the store.
        """
        if await self.store.get_server(manifest_id) is None:
            raise MCPMarketplaceError(
                f"{manifest_id!r} is not installed", status_code=404
            )
        if self.supervisor is not None:
            result = await self.supervisor.uninstall(manifest_id)
        else:
            await self.store.delete_server(manifest_id)
            result = {"agents_affected": [], "env_secrets_dropped": 0}
        result["status"] = "uninstalled"
        result["server_id"] = manifest_id
        return result
