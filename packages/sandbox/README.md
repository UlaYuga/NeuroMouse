# neuromouse-sandbox

Process-isolation boundary for **untrusted method / sorter code** (arch P1-4).
Third-party `compute` code must never run in-process in the backend; this package
runs it in a short-lived, locked-down subprocess with a clean JSON in/out contract.

## Why

The backend's `MethodCatalog.run` used to call `method.compute(...)` in-process. A
hostile or buggy method could then read secrets, reach the network, exhaust
memory/CPU, fork-bomb, or crash the backend. This package moves `compute` (and the
untrusted module import + param construction it implies) across a process boundary
so that **any** misbehaviour degrades to a graceful job failure.

## Public surface

```python
from neuromouse_sandbox import run_in_sandbox, MethodRef, SandboxLimits

result = run_in_sandbox(
    MethodRef(kind="file", path=".../methods/spike_detect.py", attr="method"),
    dataset=validated_dataset_dict,        # or None
    params={"polarity": "positive"},
    limits=SandboxLimits(),
    required_inputs=("meta.channels", ...),
    output_fields=("spike_detect.spikes", ...),
)
```

Outcomes map to `SandboxError` subclasses: `SandboxTimeout`, `SandboxResourceLimit`,
`SandboxPolicyViolation`, `SandboxMethodError`. The backend translates all of them
into a failed job — the API process is never affected.

## Isolation mechanism

| Layer | Mechanism | Threats covered |
|-------|-----------|-----------------|
| Subprocess | `compute` runs in `python -m neuromouse_sandbox.worker` | crashes, segfaults never reach the backend |
| Process group | `start_new_session=True` + `killpg` on exit/breach | reaps fork-bomb descendants |
| Wall-clock | parent watchdog kills the group past the deadline | infinite loops, sleeps, any hang |
| `RLIMIT_CPU` | soft `SIGXCPU` + hard `SIGKILL` (`cpu+1`) | CPU-spin (Linux; macOS falls through to wall-clock) |
| `RLIMIT_AS` + **RSS watchdog** | Linux address-space cap **and** a cross-platform parent RSS poll via `ps` | OOM (RLIMIT_AS is ignored on macOS, hence the watchdog) |
| `RLIMIT_NPROC` | per-user process ceiling | fork bombs (bounds concurrent processes) |
| `RLIMIT_FSIZE` / `RLIMIT_CORE` | file-size cap, no core dumps | disk write amplification |
| Scrubbed env | minimal `PATH`, `HOME`/`TMPDIR` → work dir, no inherited vars, single-threaded BLAS | secret/token exfiltration via env |
| `sys.addaudithook` policy | irrevocable audit hook installed before untrusted import | network, filesystem escape, process spawn, `ctypes` |
| Work-dir split | response/request files live outside the child's only writable dir | result-envelope forgery |

### Audit-hook policy (denied)

- **Network** — any `socket.*` event (connect/bind/getaddrinfo/socket creation), plus `urllib`/`ftplib`/`smtplib`.
- **Process spawn** — `subprocess.Popen`, the `os` spawn family (system/exec/spawn/posix_spawn/forkpty), `pty.spawn`.
- **Native escape** — any `ctypes.*` event (dlopen/dlsym/call_function).
- **Filesystem reads** — `open` (incl. low-level `os.open`) and directory reads (`os.listdir`/`os.scandir`) must be under a read allow-list (stdlib/site-packages/workspace `src`/work dir) and never a sensitive name (`.ssh`, `.aws`, `.env`, `id_rsa`, …).
- **Filesystem writes/mutations** — `open(w)`, `os.rename`/`remove`/`mkdir`/`symlink`/`link`/`chmod`/… must stay inside the work dir.
- **Directory change** — `os.chdir`/`os.fchdir` denied (would desync the cached-cwd path check from the kernel's live cwd).

Audit hooks cannot be removed once installed and fire for C-level operations, so a
method cannot un-sandbox itself from Python. Catching a `PolicyViolation` does not
help the attacker: the hook raises **before** the side effect happens.

## Escape → harden rounds

The probe suite (`tests/probes/`, exercised by `tests/test_hostile_probes*.py`) was
grown adversarially. Two consecutive rounds with **no** successful escape ended the loop.

| Round | New vectors | Escape? | Hardening |
|-------|-------------|---------|-----------|
| 1 | network, fs read/write, subprocess, shell exec, ctypes, CPU spin, sleep, **OOM**, fork bomb, env harvest | **OOM on macOS** (`RLIMIT_AS` ignored) | added parent RSS-polling watchdog |
| 2 | symlink plant, **dir enumeration**, path traversal, low-level `os.open`, multiprocessing | **`os.listdir`/`scandir` of `/etc`** | gate directory reads through the read allow-list |
| 3 | result-envelope forgery, recursion/stack crash, dynamic `exec` of a socket call, `/proc/self/environ`, SIGXCPU trap | none | (work-dir/response split added defensively) |
| 4 | **`os.chdir` + relative `open`** | **leaked `/etc/passwd`** | deny `os.chdir`/`os.fchdir` |
| 5 | thread bomb, self-rlimit-raise then OOM, local `socketpair` | none | — |
| 6 | full regression of all probes | none | — |

## Residual risks (documented, accepted for this layer)

- **No kernel-level sandbox.** This is a defense-in-depth Python-level boundary
  (audit hook + rlimits + subprocess), not a container/seccomp/namespace jail. For
  hard multi-tenant isolation, run the worker inside a container or gVisor as a
  further layer.
- **Symlinks are not dereferenced** in path checks (we avoid `realpath` to keep the
  hook non-recursive). Creating a symlink that escapes is blocked (the target path
  is checked), but a pre-existing symlink inside an allow-listed dir pointing
  outside it could be followed. Low value given reads are already allow-listed.
- **`RLIMIT_CPU` / `RLIMIT_AS` are unreliable on macOS.** The wall-clock and RSS
  watchdogs are the cross-platform backstops; Linux CI additionally enforces both
  rlimits.
- **Fork-bomb memory in the kill window.** `RLIMIT_NPROC` bounds the process count
  and `killpg` reaps the group, but on macOS (no per-process `RLIMIT_AS`) a brief
  burst of processes can allocate before the wall-clock kill. Bounded, not zero.
- **A method can fail its own job** by spamming stderr or corrupting non-response
  files in its work dir; it cannot affect other jobs or forge a success.
