"""Git: release labels, submodules, and non-submodule dependency checkouts."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from . import proc, ui
from .errors import ButlerError


def release_label(root: Path) -> str:
    """The label release artifacts are named with: the exact git tag on HEAD
    when this is a tagged build, else a UTC datetime stamp.

    The datetime fallback is what makes untagged builds safe to accumulate in
    dist/ — two builds an hour apart don't overwrite each other, and the name
    says which is which.
    """
    r = proc.capture(["git", "describe", "--tags", "--exact-match"], cwd=root)
    if r.ok and r.out.strip():
        return r.out.strip()
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def update_submodules(root: Path, *, quiet: bool = True) -> None:
    """Init/update submodules, if this is a git checkout at all (a source
    tarball or a `pip download` of the project is not, and must still build)."""
    if not (root / ".git").exists():
        return
    cmd = ["git", "submodule", "update", "--init", "--recursive"]
    if quiet:
        cmd.append("--quiet")
    proc.check(cmd, cwd=root, what="git submodule update")


def ensure_git_deps(root: Path, deps: list[dict]) -> None:
    """Clone/refresh dependencies that are plain checkouts rather than
    submodules, so their URL and ref live in butler.toml instead of .gitmodules.

    An existing checkout is fetched and `checkout`ed — never `reset --hard`.
    git carries uncommitted work along, or refuses; either way local changes
    survive, which matters because these trees are often being edited — a
    dependency can be a sibling project, not a vendored blob.
    """
    for dep in deps:
        dest = root / dep["path"]
        url, ref = dep["url"], dep.get("ref", "origin/main")

        if (dest / ".git").exists():
            ui.plain(f"Updating {dep['path']} -> {ref}")
            if proc.run(["git", "-C", dest, "fetch", "--quiet", "origin"], echo=False) != 0:
                ui.warn("warning:", f"git fetch failed for {dep['path']}; "
                                    f"using the last-known {ref}.")
            switched = proc.run(
                ["git", "-C", dest, "-c", "advice.detachedHead=false",
                 "checkout", "--quiet", ref], echo=False) == 0
            if not switched:
                ui.warn("warning:", f"could not switch {dep['path']} to {ref} without "
                                    f"overwriting local changes; keeping the current checkout.")
                continue
        else:
            ui.plain(f"Cloning {url} -> {dep['path']} @ {ref}")
            dest.parent.mkdir(parents=True, exist_ok=True)
            proc.check(["git", "clone", url, dest], what=f"clone {dep['path']}")
            proc.check(["git", "-C", dest, "-c", "advice.detachedHead=false",
                        "checkout", "--quiet", ref], what=f"checkout {ref}")

        proc.check(["git", "submodule", "update", "--init", "--recursive", "--quiet"],
                   cwd=dest, what=f"submodules of {dep['path']}")


def require_clean(root: Path) -> None:
    """Refuse to proceed with uncommitted changes. Not used by default — it's
    here for projects that want a release task to insist on it."""
    r = proc.capture(["git", "status", "--porcelain"], cwd=root)
    if r.ok and r.out.strip():
        raise ButlerError("the working tree has uncommitted changes",
                          hint="commit or stash them, or re-run with --dirty")
