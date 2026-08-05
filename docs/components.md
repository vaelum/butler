# Component reference

Every section of `butler.toml` is optional. A component's commands exist only
when its section is present, so `python butler.py --help` is always an accurate
description of the project.

Unknown keys and wrong types are errors naming the offending key — a typo never
silently does nothing.

---

## `[project]`

| key | type | default | meaning |
|---|---|---|---|
| `name` | string | **required** | used for artifact names, the keystore folder, backup filenames, env-var prefixes |
| `dist` | string | `"dist"` | where built installers are collected |
| `submodules` | bool | `false` | update git submodules before a build *(consumed by the build component, M7)* |
| `git_deps` | array of tables | `[]` | non-submodule checkouts: `{ path, url, ref }` *(M7)* |

---

## `[app]` — Tauri

| key | type | default | meaning |
|---|---|---|---|
| `kind` | string | `"tauri"` | only `tauri` so far |
| `dir` | string | `"app"` | the Tauri project, relative to the root; `src-tauri` is assumed inside it |
| `dev_identifier` | string | — | bundle identifier for `app dev` |
| `dev_product_name` | string | — | window/product name for `app dev` |
| `icon_generator` | string | — | script run before `cargo tauri icon`; must produce `app-icon.png` |
| `icon_source` | string | `app/app-icon.png` | master art for `cargo tauri icon`, relative to the **project** root — it is often shared with a web frontend and lives outside the app dir |

`dev_identifier` is worth setting. A distinct identifier gives the dev window
its own WebView data directory and keychain namespace, so it cannot collide
with — or read the credentials of — an installed release build.

**Commands**

| command | notes |
|---|---|
| `app dev` | `cargo tauri dev`, under the dev identity when configured |
| `app build [--debug] [--no-bundle] [--bundles KIND...]` | bundles land in `dist/` |
| `app icon` | runs `icon_generator`, then `cargo tauri icon` |
| `app install` | only when `[app.install]` is set |

Linux bundle builds run with `APPIMAGE_EXTRACT_AND_RUN=1` and `NO_STRIP=1`:
AppImage's linuxdeploy is itself an AppImage and needs FUSE, which headless,
containerised and hardened hosts don't have.

---

## `[app.install]` — Linux desktop install

| key | type | default | meaning |
|---|---|---|---|
| `name` | string | **required** | install name; match tauri `productName` |
| `programs_dir` | string | **required** | where the AppImage and its icon live |
| `comment` | string | `""` | `.desktop` Comment |
| `categories` | list | `["Utility"]` | `.desktop` Categories |
| `wm_class` | string | `name` | `StartupWMClass` |

`app install` copies the newest `dist/*.AppImage` to
`<programs_dir>/<name>.AppImage`, the icon beside it as `<name>.png`, and writes
`~/.local/share/applications/<name>.desktop` pointing at both by absolute path.
The names are stable and version-less, so installing a newer build over the old
one leaves the launcher valid.

---

## `[app.android]`

| key | type | default | meaning |
|---|---|---|---|
| `key_name` | string | project name | keystore folder and file name; also the APK name prefix |
| `dname` | string | derived | X.500 name for `keygen` |
| `vault` | string | `"~/Documents/important"` | keystore vault root; `$ANDROID_KEYSTORE_VAULT` overrides |
| `cleartext` | bool | `false` | permit plain-HTTP to a self-hosted LAN backend |
| `split_abi` | bool | `false` | one APK per ABI instead of one universal APK |
| `ndk_version` | string | — | preferred NDK, so a local build matches CI |
| `env_prefix` | string | `NAME` upper-cased | prefix for the four signing env vars |

**Commands**

| command | notes |
|---|---|
| `android init` | scaffolds `gen/android`; re-runnable |
| `android dev` | prepares the gen tree, then `cargo tauri android dev` |
| `android build [--debug] [--no-sign] [--split-abi] [--universal] [--install …]` | |
| `android keygen [--password P]` | one-time; random password by default |
| `android install [--device S] [--reinstall] [--logcat]` | sideloads the newest APK in `dist/` |

### What `build` does, in order

1. resolve the toolchain (SDK, NDK, JDK) or fail with everything that's missing;
2. `android init` if `gen/android` isn't there;
3. copy `src-tauri/icons/android/` over the template's stock artwork — `init`
   seeds the res tree once and never re-reads it, so without this the APK ships
   the wrong icon;
4. write `network_security_config.xml` and wire it into the manifest, when
   `cleartext = true`;
5. **delete `app/build/outputs`** — Gradle leaves an APK behind for every
   variant ever built and the signing step globs the whole tree, so a stale
   universal APK would be re-signed with today's label and shipped as if it were
   this build;
6. `cargo tauri android build --apk`, `--split-per-abi` when asked;
7. debug APKs are already signed with the Android debug key; release APKs come
   out unsigned, so zipalign + apksigner them into
   `<key_name>[-<abi>]-<label>.apk`, where the label is the exact git tag on
   HEAD or a UTC timestamp;
8. copy into `dist/`, and sideload if `--install`.

Nothing here edits the generated Gradle. `gen/android` stays regenerable:
steps 3–5 are idempotent and re-applied before every build, and signing is a
post-build step.

### Cleartext

`cleartext = true` writes a network security config rather than flipping
`usesCleartextTraffic`. On API 24+ the config takes precedence **and** keeps the
system trust anchors, so ordinary HTTPS is unaffected. Add `<domain>` entries to
the generated file's template if you'd rather not allow cleartext globally.

### Sideloading

`--install` picks the APK to install by asking the device for
`ro.product.cpu.abi` and matching it against the split APKs' arch tokens
(a split build leaves five APKs behind and only two will run on any given
device; the matching split is ~4x smaller). It falls back to the universal APK,
then the newest.

Unsigned and aligned intermediates are never install candidates. Swapping
between a debug and a release build trips `INSTALL_FAILED_UPDATE_INCOMPATIBLE`
because the signing keys differ; butler explains that this needs a clean install
and that a clean install **wipes the app's on-device data**, then asks.
`--reinstall` skips the question.

---

## `[server]` — FastAPI

| key | type | default | meaning |
|---|---|---|---|
| `kind` | string | `"fastapi"` | only `fastapi` so far |
| `dir` | string | `"server"` | the server project |
| `module` | string | `"app.main:app"` | uvicorn target |
| `port` | int | `8000` | port for `server run` |
| `dev_port` | int | — | host port the Compose stack publishes (help text only) |
| `service` | string | `"server"` | Compose service name |
| `compose` | bool | `true` | whether there's a Compose stack |
| `db_file` | string | — | sqlite file inside the data dir; enables `server reset` |
| `data_dir` | string | `"data"` | data directory inside `dir` |
| `venv` | string | `".venv"` | project venv; `""` to always use the current interpreter |
| `test` | list | `["-m", "pytest"]` | test command, run with the venv's python |

butler does **not** create the venv. The dependency set is the project's
business, and silently building one hides a missing install until something
imports differently in CI. `doctor` tells you it's absent and prints the command.

**Commands:** `run`, `dev [-d]`, `down`, `logs [--no-follow]`, `test [extra…]`,
`deploy`, `reset`. The Compose ones appear only when `compose = true`; `reset`
also needs `db_file`.

`server reset` wipes local data and un-claims the instance, so it demands the
word `wipe` rather than a y/N — a mistyped `y` shouldn't be able to do that.

---

## `[server.scripts]` — delegating to the project's own scripts

Not every server is compose-and-rsync. When a project already drives its stack
with shell scripts, re-expressing that in config would be a rewrite rather than
a migration — so butler delegates and just owns the CLI.

```toml
[server.scripts]
dev    = ["bash", "scripts/build.sh", "dev"]
build  = { cmd = ["bash", "scripts/build.sh"], help = "production stack (Caddy + TLS)" }
```

Each key becomes a `server <name>` command, run with the server directory as
cwd. A value is either an argv array, or a table with `cmd` and an optional
`help` (the default help is `run <cmd>`).

Scripts are applied last and **replace** a same-named built-in — a project that
says how to do something has said so on purpose. Other built-ins are untouched,
so a scripted `dev` can sit beside a Compose `down`.

A `butler_tasks.py` task can still wrap a scripted action, which is how chords
ships its API key to the remote before `scripts/deploy.sh` runs.

---

## `[extension]` — browser extension

| key | type | default | meaning |
|---|---|---|---|
| `dir` | string | `"extension"` | the extension source tree |
| `artifact` | string | `"<project>-extension"` | base name of the produced zips |

| `[extension.firefox]` | type | default | meaning |
|---|---|---|---|
| `id` | string | **required** | stable gecko add-on id (email-style ids are valid) |
| `min_version` | string | `"115.0"` | `strict_min_version` |

**`extension package [--label L]`** writes
`dist/<artifact>-chrome-<label>.zip` and, when `[extension.firefox]` is present,
`dist/<artifact>-firefox-<label>.zip`. The label defaults to the git tag on HEAD
or a UTC timestamp; CI passes it explicitly, since `git describe` in a shallow
checkout can't be trusted.

One source tree produces both. Rather than maintaining a second manifest that
will drift, the Firefox manifest is **derived** from the Chrome one at package
time, changing only the two things Firefox needs and Chrome rejects:

- `background` becomes an event page (`{"scripts": ["background.js"]}`) instead
  of a service worker. The same `background.js` ships unchanged — it already
  has to register listeners at top level and persist state to survive a
  service-worker restart, which is exactly what an event page needs too;
- `browser_specific_settings.gecko` carries the stable add-on id and minimum
  version.

Permissions, icons, action and options_page are identical and are never
duplicated. The source manifest on disk is never modified. Zip entries are
written in sorted order, so two runs over the same source produce byte-identical
archives.

---

## `[server.deploy]`

| key | type | default | meaning |
|---|---|---|---|
| `host` | string | **required** | ssh target |
| `dir` | string | **required** | deploy directory on the host |
| `backup_dir` | string | required unless `backup = "none"` | where snapshots land |
| `backup` | string | `"zip-data-dir"` | `zip-data-dir`, `sqlite-file`, or `none` |
| `data_dir` | string | from `[server]` | data directory name on the host |
| `db_file` | string | from `[server]` | required for `sqlite-file` |
| `exclude` | list | see below | rsync excludes |
| `post_deploy_watch` | string | — | log prefix to poll for after a first deploy |

Default excludes: `data/`, `.env`, `.venv/`, `__pycache__/`, `*.egg-info/`,
`.pytest_cache/`. These matter — the rsync uses `--delete`, so without them a
deploy would remove the live data directory and the production `.env`.

**`server deploy`, in order**

1. probe for `<dir>/<data_dir>`; absent means first deploy. `test` exits 1 for
   "absent" and >1 for ssh failing, and the two are not conflated — treating an
   unreachable host as a first deploy would skip the backup;
2. preflight (is `zip` installed?) **and then** stop the stack — finding out the
   backup tool is missing after taking the service down is a bad trade;
3. snapshot. `zip-data-dir` zips the whole data directory, which is a genuine
   restore point: stop, replace `data/` with the zip's contents, start, and the
   instance is exactly what it was. `sqlite-file` copies the DB plus its
   `-wal`/`-shm` sidecars so the copy is internally consistent;
4. rsync the code in;
5. `docker compose up -d --build`;
6. on a first deploy only, poll the logs for `post_deploy_watch` and print what
   follows it — this is how the one-time claim token these servers emit on first
   boot gets surfaced without reading container logs by hand.

Shell scripts go to the host over `ssh -T host sh -s` with the script on stdin,
never as an ssh command string: the remote login shell is whatever the user set
(fish, here), and it would try to parse POSIX syntax. This way the login shell
only ever sees the two words `sh -s`.

---

## Planned

`[build]` (CMake + Docker buildenv) and `[check]` (MegaLinter + clang-tidy) are
recognised and will parse, but produce a command that says they're not
implemented yet.
