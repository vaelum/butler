# Changelog

All notable changes to this project are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

A project pins the harness by tag in its `butler.py` (`HARNESS_REF`), so a tag
here is what projects actually consume — keep these sections accurate before
tagging. `butler.py --version` reports the version in use and the pin the
project asked for.

## [0.3.0]

First published release.

### The harness

- One CLI grammar for every project: `butler.py <component> <action>`, built
  from `butler/butler.toml`. A command exists only when the config declares that
  component, so `--help` always describes the project accurately.
- Components: `app` (Tauri desktop + Android), `server` (FastAPI, Compose or the
  project's own scripts), `extension` (Chrome + Firefox bundles from one source
  tree), and `doctor`, which reports the whole toolchain up front instead of
  letting a build discover a missing SDK ten minutes in.
- `butler/butler_tasks.py` escape hatch: `@task("a.b.c")` adds or replaces a
  command, `wraps=True` decorates a built-in. Handlers are introspected by
  parameter name (`ctx`, `args`, `inner`).
- Strict config loading — unknown keys and wrong types are errors naming the
  offending key, so a typo can never silently do nothing.
- `--dry-run`, `--verbose`, `--yes` and `--no-color` work at any depth, before
  or after the subcommand. Dry-run covers butler's own filesystem writes, not
  just the commands it shells out to.
- `--version` reports what is running, where from, and the project's pin.
- Stdlib only. The bootstrap shim is ~90 lines and pins an exact ref, so a
  project is never silently upgraded; `BUTLER_HARNESS_PATH` runs a working tree
  with no install at all.

### Notable behaviour

Where the hand-rolled scripts this replaces had drifted apart, the better
implementation won:

- Android cleartext uses a `network_security_config.xml` rather than the
  `usesCleartextTraffic` manifest placeholder — it takes precedence on API 24+
  and keeps the system trust anchors, so HTTPS is unaffected.
- `app/build/outputs` is always cleared before an Android build. Gradle leaves
  an APK behind for every variant ever built and the signing step globs the
  tree, so a stale APK would otherwise be re-signed with today's label and
  shipped as if it were the current build.
- Sideloading picks the split APK matching the device's `ro.product.cpu.abi`,
  falling back to a universal one; unsigned and aligned intermediates are never
  install candidates.
- The default deploy snapshot zips the whole data directory — a genuine restore
  point — with a single-sqlite-file copy (plus its WAL/SHM sidecars) as an
  option.
- Helpers raise `ButlerError` instead of calling `sys.exit()`, so a wrapping
  task can catch and carry on.
- The shim hands off through the venv's console script rather than
  `python -m butler`: the project root is on `sys.path` for `-m`, so `butler.py`
  would shadow the installed package and the shim would re-exec itself forever.
