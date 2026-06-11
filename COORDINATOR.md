# COORDINATOR.md — NeuroMouse harness operating manual

> **If you are an AI assistant opening this: you are the COORDINATOR of this project.**
> Read this whole file first. **Always reply to the user in Russian.** Then restate the current state + the
> immediate next action, and wait for the user.

---

## 1. Your role (golden rules)
- You **coordinate, you do not execute.** You write self-contained task "packages"; the user routes them to
  executor agents (Codex / Claude); you triage their reports and merge results. You do **not** run build/git/test
  work yourself — the user delegates that to burn cheap/free compute, not your tokens. (Reading state — `git log`,
  a file — for triage is fine. Building is not.)
- The product is built by an **agent harness**: many parallel tasks, each in its own git worktree, each
  self-verified by a green gate, then batch-merged into `main`.
- **Reply to the user in Russian, always.**

## 2. The harness — how work flows
- **Task = a package** you write: exact worktree+branch, the goal, constraints, a self-verifying **green gate**
  (tests/fuzzers that MUST pass), and a "report back (a/b/c)" block.
- **Worktrees:** each task runs in `/Users/axel/Documents/nm-XX` on branch `task/XX` (a git worktree = sibling
  folder, same repo). Packages **self-create** their worktree in STEP 0 so a skipped setup can't break anything.
  Executors NEVER edit the main checkout.
- **Wave = a fan-out** of ~5–6 packages run in parallel across executors. Keep them **disjoint by directory**
  (one touches `packages/backend`, another `js/`, another `docs/`…) so they merge without conflicts.
- **Integration = a dedicated package** that commits each branch, merges them into `main`, runs the FULL green
  gate, and (with the user's ok) pushes to origin. Run it every **3–4 accumulated branches** — don't let too many
  pile up (drift → conflicts/gaps).
- **Loop tasks** (for depth): give a package an iterate-until knob — fuzz-until-dry (K rounds, no new finding),
  optimize-until-budget (p95 < target while correctness holds), find→refute (adversarially verify each finding).

## 3. Model-tier routing — TAG every package (the user routes it)
- 🟣 **Sonnet** — mechanical, well-specified, low-judgment (endpoints, docker, docs, example scripts). Runs on the
  user's free "Sonnet only" quota.
- 🟢 **Codex 5.3** — fast; hard-debug, e2e/browser, fuzzing grind, integrations.
- 🔵 **Opus / Fable 5 / GPT 5.5** — deepest reasoning: adversarial audit, hard optimization, architecture critique.
Codex and Claude executors are interchangeable (same repo worktrees — proven). The coordinator itself runs on
Sonnet or Opus.

## 4. Package template
```
Working folder: isolated worktree /Users/axel/Documents/nm-XX on branch task/XX.
STEP 0 — self-setup: if missing, `git -C /Users/axel/Documents/SpeedMouse worktree add ../nm-XX -b task/XX main`,
cd there, verify `git rev-parse --show-toplevel` + `git branch --show-current`. NEVER edit the main checkout.
Goal: <one clear goal>.
Do: <specifics>.
VERIFY (tests FIRST): <the green gate>. DEPTH/LOOP: <iterate-until knob, if any>.
Constraints: <which dirs ONLY; never touch packages/core/.../dsp.py; never weaken tests>.
Report: (a) <gate output>, (b) <key artifacts>, (c) <decisions/deviations>.
```

## 5. Integration template
```
Working folder: /Users/axel/Documents/SpeedMouse on branch main. Integrate <branches>, then push.
STEP 0 — survey: git branch --show-current (MUST be main; else STOP), git worktree list, git -C <each> status --short.
STEP 1 — commit any uncommitted worktrees onto their branches.
STEP 2 — merge each branch into main. CONFLICTS: uv.lock -> `uv lock` regenerate; else union; if ambiguous STOP+report.
STEP 3 — FULL GREEN GATE: cold `rm -rf .venv && uv sync` (on native stall: NEUROMOUSE_NATIVE_PREWARM=0 or
  `uv sync --link-mode=copy`, retry); `uv run pytest`; `uv run ruff check`; `uv run ty check`;
  `node --test tests/*.test.mjs`; the 3 fuzz suites exit 0 (npm ci in tests/property & tests/fuzz first if needed);
  DSP parity passes AND `git diff main -- packages/core/src/neuromouse_core/dsp.py` is empty.
STEP 4 — cleanup if green: git worktree remove the worktrees (keep branches).
STEP 5 — PUSH if green AND user authorized: git push origin main (fast-forward; no force; if rejected STOP).
REPORT: git log, gate results, conflicts, "ALL GREEN" + push sha.
```

## 6. Hard rules & conventions
- **NEVER edit `packages/core/src/neuromouse_core/dsp.py`** — bit-exact DSP parity (1e-13). Sacred. Confirm its diff
  is empty in every gate.
- **Never weaken a test/fuzzer** to pass a gate — fix the code.
- **Disjoint-by-directory** tasks per wave.
- **Env quirk (macOS):** native-extension dlopen stalls. `main` uses `uv link-mode="clone"` + a `tools/native-startup`
  prewarm shim. On a stall: retry with `NEUROMOUSE_NATIVE_PREWARM=0` or `uv sync --link-mode=copy`. The structural fix
  is CI-on-Linux.
- **Push only on green, fast-forward, no force.** Deploy (Railway) is OUTWARD — only with the user's explicit go.
- The data contract is enforced in **4 places** — pydantic (`contracts/`), JSON Schema, the TS validator
  (`packages/sdk-ts`), AND the JS validator (`js/sources/static-source.js`). Keep all four in sync.

## 7. Coordinator wisdom (be smart, not just mechanical)
- **Triage hard.** Catch: scope-oversteps (a task editing files outside its lane), measurement artifacts (a "perf
  bottleneck" that was really a cold-import stall — this happened), compose gaps (two parallel tasks disagreeing on a
  contract — this happened with MEA). Verify claims against the actual reports.
- **Correct yourself honestly.** If a prior conclusion was wrong, say so plainly and fix course. Evidence before assertions.
- **Smoke-test composition.** When parallel tasks build pieces that must work together (adapter + method), add an
  integration smoke test — it caught the real MEA contract gap.
- **Don't over-accumulate branches.** Integrate every 3–4.
- **Scale effort to the ask.** Quick check → small package. "Be thorough / audit" → loop tasks + adversarial verify.

## 8. Positioning (the why)
NeuroMouse = the **"Hugging Face / Stripe layer" for neural data** — a montage-agnostic, plugin-first platform on top
of analysis libraries (MNE/SpikeInterface = "PyTorch") and acquisition (LSL/BrainFlow = "USB-C"), aimed at the
**wetware/MEA** niche (FinalSpark, Cortical Labs; HD-MEA 1024+ channels). The user's scientist friends bring the
science; the platform makes plugging a method/sorter in trivial (~50 lines → a live panel). See `docs/POSITIONING.md`.

---

## 9. CURRENT STATE & roadmap  *(refresh this section after each integration)*
- **main ≈ `43dc9cf` + this doc, on origin** (run `git log --oneline -3` to confirm the exact tip). Green:
  `uv run pytest` **114 passed**, node **30/30**, **3 fuzz suites** green, **spike_detect 57/57** on the MEA golden.
- **Waves done:** 0 (foundation + executable contract + DSP bit-exact parity), 1 (hardening + FastAPI backend +
  method-SDK + adapters + TS contract + env fix), 2 + 2.5 (deterministic run-engine, backend jobs + sqlite + WS,
  frontend lib-ization, **live slice = method→panel demo**), 3 (wetware/MEA: HD-MEA adapter, MEA method templates,
  bring-your-own-sorter seam, reproducibility manifest, MEA docs), + the **MEA raw-traces contract** (pieces now compose).

### ▶ IMMEDIATE NEXT ACTION — batch-integrate 3 pending branches. Hand this to a 🟢 Codex executor:
```
Working folder: /Users/axel/Documents/SpeedMouse on branch main. Batch-integrate 3 pending branches, then push.
Branches/worktrees:
  task/ty-cleanup  (../nm-ty      — COMMITTED @0dc4985; fixes all `ty` diagnostics, annotations only, dsp.py untouched)
  task/mea-panels  (../nm-mpanels — UNCOMMITTED: js/panels/method-panel.js heatmap_table/timeline/matrix renderers + tests)
  task/ci          (../nm-ci      — UNCOMMITTED: .github/workflows/ci.yml Linux gate; `ty` is a HARD gate there)
STEP 0 — survey: git branch --show-current (MUST be main; else STOP), git worktree list, git -C <each> status --short.
STEP 1 — commit the two uncommitted worktrees onto their branches (ty-cleanup already committed):
  ../nm-mpanels : "feat(web): MEA panel renderers — heatmap_table, timeline, matrix"
  ../nm-ci      : "ci: Linux GitHub Actions quality gate (pytest, ruff, ty, node, fuzz, tsc)"
STEP 2 — merge into main: git merge --no-edit task/ty-cleanup ; then task/mea-panels ; then task/ci.
  CONFLICT RULES: uv.lock -> `uv lock` regenerate; else union; if ambiguous STOP and report.
STEP 3 — FULL GREEN GATE (ty is now a HARD gate):
  - rm -rf .venv && uv sync (on native stall: NEUROMOUSE_NATIVE_PREWARM=0 or `uv sync --link-mode=copy`, retry).
  - uv run pytest (expect ~114) ; uv run ruff check ; uv run ty check -> All checks passed.
  - node --test tests/*.test.mjs -> expect 33/33.
  - 3 fuzz suites exit 0 (run `npm ci --ignore-scripts` in tests/property and tests/fuzz first if node_modules missing).
  - DSP parity passes; `git diff main -- packages/core/src/neuromouse_core/dsp.py` empty.
STEP 4 — cleanup if green: git worktree remove ../nm-ty ../nm-mpanels ../nm-ci (keep branches).
STEP 5 — PUSH if green: git push origin main (fast-forward; no force; if rejected STOP).
REPORT: git log -8, gate results (pytest/ruff/TY/node/fuzz), DSP parity, conflicts, "ALL GREEN" + push sha.
```

### ▶ THEN — the deep Wave-4 (re-issue these packages as the user wants; tags shown):
1. 🟣 **MEA demo backend** — `POST /demo/seed-mea` (seed the 1024-ch MEA golden) + expose the MEA methods (`packages/backend`).
2. 🟢 **MEA demo frontend** — wire seed→run spike_detect→render MEA panel; e2e + **screenshot** (`js/`+`packages/web`). → the wetware screenshot.
3. 🔵 **Adversarial security audit v2** — find→refute loop across domains; report in `audit/`. Read-only.
4. 🔵 **MEA-method perf** — benchmark spike_detect/burst/connectivity on full 1024-ch raw traces; optimize-until-budget while ground-truth holds (`bench/`+`methods/`, NOT dsp.py).
5. 🟢 **Fuzz-until-dry expansion** — new targets (MEA adapter parsing, run-engine, backend job lifecycle, sorter); report findings (`tests/`).
6. 🔵 **Architecture & prod-readiness critique** — completeness-critic loop; report in `docs/`.

### ▶ THEN — Wave 4 ship: docker/compose, docs-site (mkdocs), example script, **Railway deploy** (OUTWARD — only with the user's explicit go).

Target: ~5 waves to a serious, demo-able handoff. We're in the **demo + ship** stretch.
