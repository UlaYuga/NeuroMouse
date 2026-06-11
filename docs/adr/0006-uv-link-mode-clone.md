# ADR 0006: uv link-mode clone

## Status

Accepted.

## Context

The workspace is used across local worktrees and tool-driven sessions. Symlink or hardlink
environments can produce surprising behavior when a branch, worktree, or generated package
state changes underneath an active environment.

The root [`pyproject.toml`](../../pyproject.toml) sets:

```toml
[tool.uv]
package = false
link-mode = "clone"
```

## Decision

Use `uv` with `link-mode = "clone"` for the workspace environment.

`link-mode = "copy"` isolated workspace installs from hardlink/symlink cache behavior, but
fresh macOS virtualenvs still intermittently stalled while dyld validated copied native
extension files during cold imports (`scipy.fft`, `jsonschema_rs`, and `numpy`). The clone
mode keeps worktree environments isolated while reducing the slow copied-file validation
path observed in those cold-import samples.

The dev dependency `neuromouse-native-startup` installs
[`sitecustomize.py`](../../tools/native-startup/src/sitecustomize.py) as a top-level module in
site-packages. On macOS, when Python starts from this repo's local `.venv`, it disables
Python's `posix_spawn`/`vfork` subprocess paths for the test process and prewarms the native
SciPy, jsonschema-rs, and NumPy imports with short timeout/retry attempts. This converts the
intermittent dyld validation stall into a bounded startup step before pytest or the benchmark
harness reaches those imports.

## Consequences

- Workspace installs use copy-on-write clones where the filesystem supports them, keeping
  local worktree environments isolated without duplicating the dyld validation cost of
  freshly copied native extensions.
- Environment state is isolated from package-cache link behavior.
- Disk usage remains low on clone-capable filesystems and may fall back to ordinary copies
  where clone mode is unsupported.
- Python startup in this repo's `.venv` does a bounded native-import prewarm on macOS. Set
  `NEUROMOUSE_NATIVE_PREWARM=0` only for debugging that startup hook itself.
- Contributors should not remove this setting as a cleanup unless they also prove the
  environment behavior across worktrees.
