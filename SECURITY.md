# Security Policy

## Reporting a Vulnerability

Use **[GitHub Private Security Advisories](https://github.com/UlaYuga/speedmouse/security/advisories/new)**
to report a vulnerability privately.  
Include: affected component, reproduction steps, and impact assessment.  
Expected initial response: within 7 days.  
Please do **not** open a public issue for security findings.

---

## Threat Model

NeuroMouse is a **local-first** neural-signal workbench. All analysis runs in the
browser or on the local machine. No neural data is transmitted to any cloud service.

### Neural data (highest sensitivity)

| Risk | Mitigation |
|------|------------|
| EEG/neural data treated as sensitive biometric-adjacent health data | Never commit real session data; `data/` contains only the synthetic demo dataset; `source-data/` is `.gitignore`-d |
| PII exposure in committed files | PII scan passes 0 findings (see `audit/agent-6-security.md`); do not add identifiers to `data.json` |
| Accidental upload of local recordings | No cloud upload path exists; WebSocket only connects to `127.0.0.1`; data never leaves the browser session |

### Frontend / JavaScript supply chain

| Risk | Mitigation |
|------|------------|
| Third-party script injection at page load | No external JS is fetched on initial load |
| JSZip CDN (loaded lazily on ZIP import) | Trust-on-first-use; loaded only when the user triggers a ZIP import; for production deployments, vendor the asset or pin with Subresource Integrity (SRI) |
| No Node.js production dependencies | `package.json` declares no `dependencies`; `npm install` is not required to run the app |

### Python / backend supply chain

| Risk | Mitigation |
|------|------------|
| Transitive dependency compromise | All packages are pinned in `uv.lock`; reproduce the environment with `uv sync --frozen` |
| Dependency audit | Run `uv tree` or `pip-audit` against the lock file; review on dependency updates |
| Workspace packages are local-only | `neuromouse-adapters` and `neuromouse-native-startup` are workspace members; no PyPI publishing |

### Infrastructure

The production deployment (Railway) serves only the pre-built static assets and the
`server.mjs` file server. No database and no user-authentication surface exist.

---

## Known Dev-Environment Caveat — macOS `dlopen` prewarm

`neuromouse-native-startup` installs a `sitecustomize.py` that runs at Python
startup inside the local `.venv`. It:

1. Disables Python's `posix_spawn`/`vfork` subprocess paths for the test process.
2. Prewarms `scipy`, `numpy`, and `jsonschema-rs` imports with short timeout/retry
   attempts to avoid intermittent dyld validation stalls on cold macOS virtualenvs.

**This is expected behavior, not a backdoor.** The hook is source-visible at
[`tools/native-startup/src/sitecustomize.py`](tools/native-startup/src/sitecustomize.py).  
Set `NEUROMOUSE_NATIVE_PREWARM=0` to disable the prewarm during debugging.  
Do not remove `link-mode = "clone"` without re-validating dyld behavior across worktrees
(see [ADR 0006](docs/adr/0006-uv-link-mode-clone.md)).

---

## Supported Versions

This project does not yet have versioned releases. The `main` branch is the supported
surface. Older commits receive no backported fixes.
