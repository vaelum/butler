"""Deploying a server to a box over SSH.

The shape is the same in every project that does it: stop the stack so the data
is quiescent, snapshot it, rsync the code in without touching the live data
directory or the production .env, then rebuild and start.

Two things the copies disagreed on, resolved here:

  * the snapshot — one copied just the sqlite file, another zipped the whole
    data directory. The zip is a genuine restore point (WAL and sidecars
    included, plus whatever else the app keeps beside the DB): stop the stack,
    replace data/ with the zip's contents, start again, and the instance is
    exactly what it was. It's the default; `backup = "sqlite-file"` keeps the
    cheaper behaviour for projects that only have a DB.
  * first deploy — one of them probes for it and polls the fresh instance's logs
    for the one-time claim token. Without that the very first deploy leaves you
    with a running server you can't log into without going and reading container
    logs by hand.
"""

from __future__ import annotations

from datetime import datetime

from .. import proc, ui
from ..config import DeployConfig, ServerConfig
from ..context import Ctx
from ..errors import ButlerError


def ssh_sh(ctx: Ctx, host: str, script: str) -> int:
    """Run a POSIX shell script on `host`. See proc.feed for why via stdin."""
    return proc.feed(["ssh", "-T", host, "sh", "-s"], script.strip() + "\n",
                     dry_run=ctx.dry_run)


def _require(ctx: Ctx, host: str, script: str, what: str) -> None:
    rc = ssh_sh(ctx, host, script)
    if rc != 0:
        raise ButlerError(f"deploy aborted: {what} failed", code=rc)


def is_first_deploy(ctx: Ctx, cfg: DeployConfig) -> bool:
    """No data directory on the far end means nothing to preserve.

    `test` exits 1 for "absent"; anything above that is ssh itself failing, and
    must not be mistaken for a clean first deploy — that would skip the backup.
    """
    rc = ssh_sh(ctx, cfg.host,
                f"mkdir -p {cfg.dir}\ntest -d {cfg.dir}/{cfg.data_dir}")
    if rc not in (0, 1):
        raise ButlerError("deploy aborted: could not reach the deploy host", code=rc)
    return rc == 1


def stop_stack(ctx: Ctx, cfg: DeployConfig, *, preflight: str = "") -> None:
    """Stop whatever is running, if anything is.

    Any preflight check belongs BEFORE the stack goes down — discovering that
    `zip` isn't installed after taking the service offline is a bad trade.
    """
    _require(ctx, cfg.host, preflight + f"""
if [ -f {cfg.dir}/docker-compose.yml ] || [ -f {cfg.dir}/compose.yml ] || \\
   [ -f {cfg.dir}/docker-compose.yaml ] || [ -f {cfg.dir}/compose.yaml ]; then
  cd {cfg.dir} && docker compose down
else
  echo 'no compose file in {cfg.dir} — nothing to stop'
fi""", "stopping the existing stack")


def snapshot(ctx: Ctx, cfg: DeployConfig, stamp: str) -> str | None:
    """Take the pre-deploy restore point. Returns where it landed."""
    if cfg.backup == "none":
        return None
    assert cfg.backup_dir

    if cfg.backup == "zip-data-dir":
        target = f"{cfg.backup_dir}/{ctx.name}-{stamp}.zip"
        # Paths inside the zip are `data/...`, so it unpacks straight into the
        # deploy dir.
        _require(ctx, cfg.host, f"""
set -e
mkdir -p {cfg.backup_dir}
cd {cfg.dir} && zip -rq {target} {cfg.data_dir}
echo "backed up -> {target} ($(du -h {target} | cut -f1))" """, "the data-dir backup")
        return target

    target = f"{cfg.backup_dir}/{ctx.name}-{stamp}.db"
    # Copy the WAL/SHM sidecars too, so the snapshot is internally consistent.
    _require(ctx, cfg.host, f"""
set -e
mkdir -p {cfg.backup_dir}
cp -a {cfg.dir}/{cfg.data_dir}/{cfg.db_file} {target}
for ext in -wal -shm; do
  if [ -f {cfg.dir}/{cfg.data_dir}/{cfg.db_file}$ext ]; then
    cp -a {cfg.dir}/{cfg.data_dir}/{cfg.db_file}$ext {target}$ext
  fi
done
echo 'backed up -> {target}'""", "the database backup")
    return target


def push_code(ctx: Ctx, server: ServerConfig, cfg: DeployConfig) -> None:
    """rsync the server directory in. The trailing slash on the source copies
    its CONTENTS, and --delete then prunes files removed from the repo — hence
    the excludes: live data, the production .env and build junk must survive."""
    excludes = [f"--exclude={e}" for e in cfg.exclude]
    rc = ctx.run(["rsync", "-az", "--delete", *excludes,
                  f"{server.dir}/", f"{cfg.host}:{cfg.dir}/"])
    if rc != 0:
        raise ButlerError("deploy aborted: rsync failed", code=rc)


def start_stack(ctx: Ctx, cfg: DeployConfig) -> None:
    rc = ssh_sh(ctx, cfg.host, f"cd {cfg.dir} && docker compose up -d --build")
    if rc != 0:
        raise ButlerError("deploy failed: docker compose up failed", code=rc)


def watch_for(ctx: Ctx, cfg: DeployConfig, service: str, prefix: str) -> None:
    """Poll a fresh instance's logs for a one-time value it prints on boot."""
    rc = ssh_sh(ctx, cfg.host, f"""
cd {cfg.dir}
tries=0
while [ $tries -lt 15 ]; do
  value=$(docker compose logs {service} 2>/dev/null | sed -n 's/.*{prefix} *//p' | tail -n 1)
  [ -n "$value" ] && {{ echo "{prefix} $value"; exit 0; }}
  tries=$((tries+1)); sleep 2
done
echo 'nothing matched in the logs yet'; exit 1""")
    if rc != 0:
        ui.warn("could not read it from the logs", "— check the container output:\n"
                f"  ssh {cfg.host} 'cd {cfg.dir} && docker compose logs {service}'")


def deploy(ctx: Ctx, server: ServerConfig) -> int:
    cfg = server.deploy
    if cfg is None:
        raise ButlerError("this project has no [server.deploy] configuration")

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    first = is_first_deploy(ctx, cfg)
    if first:
        ui.warn("first deploy", f"— no {cfg.dir}/{cfg.data_dir} yet, nothing to back up")

    preflight = ""
    if not first and cfg.backup == "zip-data-dir":
        preflight = ("command -v zip >/dev/null 2>&1 || "
                     "{ echo 'zip is not installed on the deploy host'; exit 1; }\n")
    stop_stack(ctx, cfg, preflight=preflight)

    backup = None if first else snapshot(ctx, cfg, stamp)
    push_code(ctx, server, cfg)
    start_stack(ctx, cfg)

    ui.plain()
    ui.ok("deployed", f"{cfg.host}:{cfg.dir}" + (f"  (backup: {backup})" if backup else ""))
    if first and cfg.post_deploy_watch:
        watch_for(ctx, cfg, server.service, cfg.post_deploy_watch)
    return 0
