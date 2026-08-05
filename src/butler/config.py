"""butler.toml — parsing and validation.

In a config-first design the dominant failure mode is a typo'd key silently
doing nothing, so every table is consumed strictly: anything left over after the
known keys are read is an error naming the offending key. That is the whole
reason for the `Table` wrapper rather than plain dict access.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import ConfigError

CONFIG_NAME = "butler.toml"
TASKS_NAME = "butler_tasks.py"
# Both live in a butler/ subdirectory by default, so a project root gains one
# entry (the butler.py shim) rather than three. The flat layout is still read,
# so a project can move at its own pace.
CONFIG_DIR = "butler"

# Recognised but not yet implemented; named here so a project that declares one
# gets "not implemented yet" instead of "unknown key".
PLANNED_SECTIONS = {
    "build": "M6 — cmake / docker buildenv",
    "check": "M6 — MegaLinter / clang-tidy",
}


class Table:
    """A TOML table that must be fully consumed."""

    def __init__(self, data: Any, where: str):
        if not isinstance(data, dict):
            raise ConfigError(f"[{where}] must be a table, got {type(data).__name__}")
        self._d = dict(data)
        self._where = where

    def _pop(self, key: str, default: Any, required: bool) -> Any:
        if key in self._d:
            return self._d.pop(key)
        if required:
            raise ConfigError(f"[{self._where}] is missing the required key '{key}'")
        return default

    def _typed(self, key: str, type_: type, default: Any, required: bool) -> Any:
        val = self._pop(key, default, required)
        if val is not None and not isinstance(val, type_):
            raise ConfigError(
                f"[{self._where}] '{key}' must be {type_.__name__}, "
                f"got {type(val).__name__}")
        return val

    def str_(self, key, default=None, *, required=False) -> Any:
        return self._typed(key, str, default, required)

    def int_(self, key, default=None, *, required=False) -> Any:
        return self._typed(key, int, default, required)

    def bool_(self, key, default=None, *, required=False) -> Any:
        return self._typed(key, bool, default, required)

    def list_(self, key, default=None, *, required=False) -> list:
        val = self._typed(key, list, None, required)
        return list(val) if val is not None else list(default or [])

    def table(self, key: str) -> Table | None:
        val = self._pop(key, None, False)
        return Table(val, f"{self._where}.{key}") if val is not None else None

    def open_table(self, key: str) -> dict:
        """A table whose KEYS are user-chosen (script names), so it can't be
        consumed strictly — only its values are validated."""
        val = self._pop(key, None, False)
        if val is None:
            return {}
        if not isinstance(val, dict):
            raise ConfigError(f"[{self._where}.{key}] must be a table")
        return dict(val)

    def done(self) -> None:
        if self._d:
            keys = ", ".join(sorted(self._d))
            raise ConfigError(f"[{self._where}] has unknown key(s): {keys}")


# --------------------------------------------------------------------------- #
# component configs
# --------------------------------------------------------------------------- #

@dataclass
class InstallConfig:
    """`app install`: the Linux AppImage + icon + .desktop launcher."""
    name: str
    programs_dir: Path
    comment: str = ""
    categories: list[str] = field(default_factory=lambda: ["Utility"])
    wm_class: str | None = None

    @property
    def startup_wm_class(self) -> str:
        return self.wm_class or self.name


@dataclass
class AndroidConfig:
    key_name: str
    dname: str
    # A vault OUTSIDE the repo holds the signing keys, one subfolder per app, so
    # a keystore is never in a project tree and one vault signs several apps.
    # $ANDROID_KEYSTORE_VAULT wins; this is the fallback.
    vault: Path = Path("~/Documents/important")
    # Permit plain-HTTP to a self-hosted LAN backend via a network security
    # config (see components/android.py for why not usesCleartextTraffic).
    cleartext: bool = False
    # One APK per ABI instead of one universal APK carrying all of them.
    split_abi: bool = False
    ndk_version: str | None = None
    # Prefix for the four signing-override env vars, e.g. MYAPP ->
    # MYAPP_ANDROID_KEYSTORE / _KS_PASS / _KEY_ALIAS / _KEY_PASS.
    env_prefix: str = ""


@dataclass
class TauriConfig:
    dir: Path
    android: AndroidConfig | None = None
    install: InstallConfig | None = None
    # `cargo tauri dev` under a distinct identity, so a dev window can't collide
    # with an installed release build's WebView storage / keychain entries.
    dev_identifier: str | None = None
    dev_product_name: str | None = None
    icon_generator: str | None = None   # script run before `cargo tauri icon`
    # Master art for `cargo tauri icon`, relative to the PROJECT root — it is
    # often shared with the web frontend and so lives outside the app dir.
    icon_source: Path | None = None

    @property
    def tauri_dir(self) -> Path:
        return self.dir / "src-tauri"


@dataclass
class DeployConfig:
    host: str
    dir: str
    backup_dir: str | None = None
    # How to snapshot before overwriting: zip the whole data dir (a real restore
    # point), copy a single sqlite file, or nothing.
    backup: str = "zip-data-dir"
    data_dir: str = "data"
    db_file: str | None = None
    exclude: list[str] = field(default_factory=lambda: [
        "data/", ".env", ".venv/", "__pycache__/", "*.egg-info/", ".pytest_cache/",
    ])
    # After a FIRST deploy, poll the logs for this prefix and print what follows
    # (the one-time claim token these servers emit when unclaimed).
    post_deploy_watch: str | None = None


@dataclass
class ScriptAction:
    """A command the project already has a script for.

    Not every server is compose-and-rsync. Some drive their own
    `scripts/build.sh`, and re-expressing that in config would be a rewrite
    rather than a migration — so butler delegates and just owns the CLI.
    """
    name: str
    cmd: list[str]
    help: str


@dataclass
class ServerConfig:
    dir: Path
    module: str = "app.main:app"
    port: int = 8000
    dev_port: int | None = None      # host port the compose stack publishes
    service: str = "server"          # compose service name
    compose: bool = True
    # The sqlite file inside the data dir, if the server has one. Used by
    # `server reset` locally and as the default for a sqlite-file deploy backup.
    db_file: str | None = None
    data_dir: str = "data"
    venv: Path | None = None
    test: list[str] = field(default_factory=lambda: ["-m", "pytest"])
    deploy: DeployConfig | None = None
    # Extra (or overriding) actions that shell out to the project's own scripts.
    scripts: list[ScriptAction] = field(default_factory=list)


@dataclass
class FirefoxConfig:
    # A stable add-on id, so storage survives updates and Mozilla can sign it
    # later. Email-style ids are valid AMO ids.
    id: str
    min_version: str = "115.0"


@dataclass
class ExtensionConfig:
    dir: Path
    artifact: str                    # base name of the produced zips
    firefox: FirefoxConfig | None = None


@dataclass
class ProjectConfig:
    name: str
    dist: Path
    git_deps: list[dict] = field(default_factory=list)
    submodules: bool = False


@dataclass
class Config:
    root: Path
    project: ProjectConfig
    app: TauriConfig | None = None
    server: ServerConfig | None = None
    extension: ExtensionConfig | None = None
    # Sections that parsed as "planned but unimplemented"; the CLI turns each
    # into a command that says so rather than pretending it doesn't exist.
    planned: dict[str, str] = field(default_factory=dict)

    @property
    def dist_dir(self) -> Path:
        return self.root / self.project.dist


# --------------------------------------------------------------------------- #
# loading
# --------------------------------------------------------------------------- #

def config_path(root: Path) -> Path | None:
    """This project's butler.toml — nested first, then the flat fallback."""
    for candidate in (root / CONFIG_DIR / CONFIG_NAME, root / CONFIG_NAME):
        if candidate.is_file():
            return candidate
    return None


def tasks_path(root: Path) -> Path | None:
    """This project's butler_tasks.py, beside whichever butler.toml was found."""
    for candidate in (root / CONFIG_DIR / TASKS_NAME, root / TASKS_NAME):
        if candidate.is_file():
            return candidate
    return None


def find_root(start: Path | None = None) -> Path:
    """Walk up from `start` looking for a project.

    Walking up (rather than demanding cwd == project root) is what makes
    `python ../../butler.py app dev` and running from a subdirectory work.
    """
    here = (start or Path.cwd()).resolve()
    for d in [here, *here.parents]:
        if (d / CONFIG_DIR / CONFIG_NAME).is_file():
            return d
        # The flat layout, except when `d` IS the butler/ directory of the
        # project above — running from inside butler/ must find the project,
        # not mistake that directory for the root.
        if (d / CONFIG_NAME).is_file() and d.name != CONFIG_DIR:
            return d
    raise ConfigError(
        f"no {CONFIG_DIR}/{CONFIG_NAME} found in {here} or any parent directory",
        hint="Create one with:  butler new .")


def load(root: Path) -> Config:
    path = config_path(root)
    if path is None:
        raise ConfigError(f"no {CONFIG_DIR}/{CONFIG_NAME} under {root}")
    try:
        raw = tomllib.loads(path.read_text())
    except OSError as e:
        raise ConfigError(f"cannot read {path}: {e}") from e
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path} is not valid TOML: {e}") from e
    return parse(raw, root)


def parse(raw: dict, root: Path) -> Config:
    top = Table(raw, "")

    project = _project(top.table("project"), root)
    app = _tauri(top.table("app"), root, project.name)
    server = _server(top.table("server"), root)
    extension = _extension(top.table("extension"), root, project.name)

    planned = {}
    for name, milestone in PLANNED_SECTIONS.items():
        if top.table(name) is not None:
            planned[name] = milestone
    top.done()

    return Config(root=root, project=project, app=app, server=server,
                  extension=extension, planned=planned)


def _extension(t: Table | None, root: Path, project_name: str) -> ExtensionConfig | None:
    if t is None:
        return None
    firefox = t.table("firefox")
    cfg = ExtensionConfig(
        dir=root / t.str_("dir", "extension"),
        artifact=t.str_("artifact", f"{project_name}-extension"),
        firefox=FirefoxConfig(
            id=firefox.str_("id", required=True),
            min_version=firefox.str_("min_version", "115.0"),
        ) if firefox else None,
    )
    if firefox:
        firefox.done()
    t.done()
    return cfg


def _project(t: Table | None, root: Path) -> ProjectConfig:
    if t is None:
        raise ConfigError("butler.toml has no [project] section",
                          hint='Minimum:  [project]\n          name = "myproject"')
    cfg = ProjectConfig(
        name=t.str_("name", required=True),
        dist=Path(t.str_("dist", "dist")),
        submodules=t.bool_("submodules", False),
        git_deps=_git_deps(t.list_("git_deps")),
    )
    t.done()
    return cfg


def _git_deps(items: list) -> list[dict]:
    out = []
    for i, item in enumerate(items):
        d = Table(item, f"project.git_deps[{i}]")
        out.append({
            "path": d.str_("path", required=True),
            "url": d.str_("url", required=True),
            "ref": d.str_("ref", "origin/main"),
        })
        d.done()
    return out


def _tauri(t: Table | None, root: Path, project_name: str) -> TauriConfig | None:
    if t is None:
        return None
    kind = t.str_("kind", "tauri")
    if kind != "tauri":
        raise ConfigError(f"[app] kind '{kind}' is not supported (only 'tauri' so far)")
    android = _android(t.table("android"), project_name)
    install = _install(t.table("install"))
    cfg = TauriConfig(
        dir=root / t.str_("dir", "app"),
        android=android,
        install=install,
        dev_identifier=t.str_("dev_identifier"),
        dev_product_name=t.str_("dev_product_name"),
        icon_generator=t.str_("icon_generator"),
        icon_source=(root / src) if (src := t.str_("icon_source")) else None,
    )
    t.done()
    return cfg


def _android(t: Table | None, project_name: str) -> AndroidConfig | None:
    if t is None:
        return None
    key_name = t.str_("key_name", project_name)
    cfg = AndroidConfig(
        key_name=key_name,
        dname=t.str_("dname", f"CN={key_name}, OU={key_name}, O={key_name}, C=DE"),
        vault=Path(t.str_("vault", "~/Documents/important")),
        cleartext=t.bool_("cleartext", False),
        split_abi=t.bool_("split_abi", False),
        ndk_version=t.str_("ndk_version"),
        env_prefix=t.str_("env_prefix", project_name.upper()),
    )
    t.done()
    return cfg


def _install(t: Table | None) -> InstallConfig | None:
    if t is None:
        return None
    cfg = InstallConfig(
        name=t.str_("name", required=True),
        programs_dir=Path(t.str_("programs_dir", required=True)).expanduser(),
        comment=t.str_("comment", ""),
        categories=t.list_("categories", ["Utility"]),
        wm_class=t.str_("wm_class"),
    )
    t.done()
    return cfg


def _server(t: Table | None, root: Path) -> ServerConfig | None:
    if t is None:
        return None
    kind = t.str_("kind", "fastapi")
    if kind != "fastapi":
        raise ConfigError(f"[server] kind '{kind}' is not supported (only 'fastapi' so far)")
    db_file = t.str_("db_file")
    data_dir = t.str_("data_dir", "data")
    scripts = _scripts(t.open_table("scripts"))
    deploy = _deploy(t.table("deploy"), db_file, data_dir)
    venv = t.str_("venv", ".venv")
    directory = root / t.str_("dir", "server")
    cfg = ServerConfig(
        dir=directory,
        module=t.str_("module", "app.main:app"),
        port=t.int_("port", 8000),
        dev_port=t.int_("dev_port"),
        service=t.str_("service", "server"),
        compose=t.bool_("compose", True),
        db_file=db_file,
        data_dir=data_dir,
        venv=(directory / venv) if venv else None,
        test=t.list_("test", ["-m", "pytest"]),
        deploy=deploy,
        scripts=scripts,
    )
    t.done()
    return cfg


def _scripts(raw: dict) -> list[ScriptAction]:
    """`[server.scripts]` — either `name = [argv…]` or a table with cmd/help."""
    out = []
    for name, value in raw.items():
        where = f"server.scripts.{name}"
        if isinstance(value, list):
            cmd, help_ = value, None
        elif isinstance(value, dict):
            tbl = Table(value, where)
            cmd = tbl.list_("cmd", required=True)
            help_ = tbl.str_("help")
            tbl.done()
        else:
            raise ConfigError(f"[{where}] must be an array of strings, or a table "
                              f"with 'cmd' (and optionally 'help')")
        if not cmd or not all(isinstance(c, str) for c in cmd):
            raise ConfigError(f"[{where}] cmd must be a non-empty array of strings")
        out.append(ScriptAction(name=name, cmd=list(cmd),
                                help=help_ or f"run {' '.join(cmd)}"))
    return out


def _deploy(t: Table | None, db_file: str | None, data_dir: str) -> DeployConfig | None:
    if t is None:
        return None
    backup = t.str_("backup", "zip-data-dir")
    if backup not in ("zip-data-dir", "sqlite-file", "none"):
        raise ConfigError(
            f"[server.deploy] backup '{backup}' is not one of: "
            "zip-data-dir, sqlite-file, none")
    cfg = DeployConfig(
        host=t.str_("host", required=True),
        dir=t.str_("dir", required=True),
        backup_dir=t.str_("backup_dir"),
        backup=backup,
        data_dir=t.str_("data_dir", data_dir),
        db_file=t.str_("db_file", db_file),
        exclude=t.list_("exclude", DeployConfig.__dataclass_fields__["exclude"].default_factory()),
        post_deploy_watch=t.str_("post_deploy_watch"),
    )
    t.done()
    if cfg.backup == "sqlite-file" and not cfg.db_file:
        raise ConfigError("[server.deploy] backup = 'sqlite-file' needs 'db_file'")
    if cfg.backup != "none" and not cfg.backup_dir:
        raise ConfigError(f"[server.deploy] backup = '{cfg.backup}' needs 'backup_dir'")
    return cfg
