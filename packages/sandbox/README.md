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
| `no_new_privs` + non-dumpable | Linux `prctl(PR_SET_NO_NEW_PRIVS)` and `PR_SET_DUMPABLE=0` | privilege gain via exec, same-UID ptrace/proc inspection by sibling processes |
| Seccomp-bpf | Linux `libseccomp` deny rules before untrusted import | raw syscall network egress, process/exec, namespace entry, mount/chroot, ptrace, `bpf`, `perf_event_open`, module/kexec/keyring/io_uring surfaces |
| Landlock | Linux path rules before untrusted import: read allow-list + workdir write-only area | raw `openat`/`os.open` bypasses against `/proc`, secrets, and host paths outside the method/package allow-list |
| `sys.addaudithook` policy | irrevocable audit hook installed before untrusted import | network, filesystem escape, process spawn, `ctypes` |
| Work-dir split | response/request files live outside the child's only writable dir | result-envelope forgery |

### Linux kernel policy

The kernel layer is controlled by `NEUROMOUSE_SANDBOX_KERNEL`:

- `auto` (default): enable seccomp/Landlock on Linux when available; no-op on macOS
  and other dev platforms.
- `required`: fail the method closed if the Linux kernel layer cannot be installed.
  `Dockerfile.backend` sets this for hosted deployment and installs `libseccomp2`.
- `off`: keep only the portable subprocess/audit-hook/rlimit policy.

The worker installs seccomp before untrusted import and denies syscall families that
do not belong in method code: networking, process creation/exec, namespace creation
or entry, mount/chroot/pivot-root, ptrace/cross-process memory, kernel-module/kexec,
keyring, `bpf`, `perf_event_open`, `userfaultfd`, and `io_uring`.

Landlock is installed in the same trusted phase. It allows reads only under the
Python/runtime/package/method directories already used by the audit-hook read
allow-list, and allows writes only under the per-run work dir. This is the kernel
path layer for raw `openat("/proc/self/environ")` and similar tricks that do not
emit Python audit events. Landlock is not a mount namespace and does not hide the
existence of the broader filesystem; it denies access when the worker tries to open
or mutate paths outside the ruleset.

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
| 7 | raw Linux syscalls for `socket`, `ptrace`, `unshare`; raw `openat("/proc/self/environ")` | **missing kernel layer** | add seccomp-bpf deny-list and Landlock path confinement; backend image sets `NEUROMOUSE_SANDBOX_KERNEL=required` |
| 8 | Linux full sandbox regression under required kernel mode, including `spike_detect` 57/57 | none | — |
| 9 | repeated Linux full sandbox regression under required kernel mode | none | — |

## Residual risks (documented, accepted for this layer)

- **Not a complete kernel jail.** The hosted worker now has seccomp-bpf and
  Landlock, but it does not create new PID/mount/user/network namespaces. The
  backend container/runtime remains the outer isolation boundary.
- **Kernel feature dependency.** `required` mode needs Linux with libseccomp and
  Landlock support. If either cannot be installed, the worker fails closed. macOS
  development keeps using the Python audit-hook/rlimit/watchdog fallback.
- **Seccomp is a syscall-family deny-list, not a full allow-list.** It blocks the
  high-risk escape families listed above while preserving enough of CPython for
  legitimate scientific methods. Unknown future syscalls should be reviewed before
  treating this as a hard multi-tenant boundary.
- **Landlock is path-based, not a hidden filesystem view.** It prevents opens and
  mutations outside the allow-list, including raw `/proc` opens, but it does not
  make `/proc` or other mounts disappear. Some local Docker bind mounts behave
  differently from the hosted image `COPY` layout; hosted proof should run from
  container-owned files.
- **Symlinks are not dereferenced** in path checks (we avoid `realpath` to keep the
  hook non-recursive). Creating a symlink that escapes is blocked by the Python
  policy, and Landlock denies kernel opens outside allowed trees on Linux; on
  non-Linux fallback, pre-existing symlink edge cases remain lower-confidence.
- **`RLIMIT_CPU` / `RLIMIT_AS` are unreliable on macOS.** The wall-clock and RSS
  watchdogs are the cross-platform backstops; Linux CI additionally enforces both
  rlimits.
- **Fork-bomb memory in the kill window.** `RLIMIT_NPROC` bounds the process count
  and `killpg` reaps the group, but on macOS (no per-process `RLIMIT_AS`) a brief
  burst of processes can allocate before the wall-clock kill. Bounded, not zero.
- **A method can fail its own job** by spamming stderr or corrupting non-response
  files in its work dir; it cannot affect other jobs or forge a success.
