# ADR 0006: uv link-mode copy

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
link-mode = "copy"
```

## Decision

Use `uv` with `link-mode = "copy"` for the workspace environment.

## Consequences

- Workspace installs are less clever but more predictable across local branches and
  worktrees.
- Environment state is isolated from package-cache link behavior.
- Disk usage can be higher than link modes, but repeatable local verification is more
  important for this repository right now.
- Contributors should not remove this setting as a cleanup unless they also prove the
  environment behavior across worktrees.
