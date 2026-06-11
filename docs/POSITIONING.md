# NeuroMouse Positioning

NeuroMouse should be explained as the platform layer for neural signal work, not as another
single-purpose analysis library.

The closest analogy is the Hugging Face layer in machine learning:

- PyTorch and TensorFlow are powerful libraries.
- Hugging Face makes models, datasets, pipelines, cards, hosted demos, and reproducible
  usage patterns legible to a wider group.
- NeuroMouse should do that for neural signal data, methods, and interactive collaborator
  artifacts.

For neurotechnology, the lower-level library layer is MNE, SpikeInterface, SciPy, NumPy,
BrainFlow, LSL, and lab-specific acquisition stacks. NeuroMouse sits above that layer as the
contract, method, replay, and presentation surface.

![NeuroMouse landscape map](neuromouse-landscape.svg)

## Short Positioning Statement

NeuroMouse is a platform layer for neural signal datasets and analysis methods. It accepts
EEG, MEA, and wetware-adjacent data from acquisition and analysis tools, normalizes it
through an executable contract, runs declared methods, and renders collaborator-ready
interactive artifacts in the browser.

## What It Is

- A contract-first bridge between acquisition, analysis, service, and UI layers.
- A method SDK and registry for small declared analysis plugins.
- A browser-native replay and inspection surface that does not require collaborators to run
  Python.
- A path from EEG data today toward MEA and wetware data from ecosystems such as FinalSpark
  and Cortical Labs.

## What It Is Not

- Not a replacement for MNE, SpikeInterface, SciPy, or NumPy.
- Not an acquisition protocol competing with LSL or BrainFlow.
- Not only a static EEG dashboard.
- Not a black-box analytics service with hidden data assumptions.

## Landscape

| Layer | Examples | NeuroMouse role |
| --- | --- | --- |
| Acquisition | LSL, BrainFlow, EDF/BDF/CSV exports, lab APIs | normalize into canonical datasets |
| Analysis libraries | MNE, SpikeInterface, SciPy, NumPy | remain the low-level compute substrate |
| Platform layer | NeuroMouse | contract, method SDK, registry, replay, browser artifact |
| Collaborators | researchers, labs, reviewers, wetware teams | inspect, compare, reproduce, and discuss |

The key strategic choice is to stay neutral. NeuroMouse should make upstream tools easier to
use together, not force a new lab stack.

## Span: EEG To MEA And Wetware

The contract is montage-agnostic and channel-major. That lets the same platform language
cover:

- conventional EEG montages with human-readable channel names
- high-density EEG and MEA layouts with hundreds or thousands of channels
- file replay and live streams
- wetware-adjacent datasets from organoid and cultured-neuron systems

The default 4096-channel ceiling is a safety control, not a scientific boundary. It keeps
browser and service paths from accepting unbounded payloads while leaving room for
high-density MEA work.

## Collaborator Message

When showing this to collaborators, lead with the artifact:

1. The viewer already renders canonical datasets in the browser.
2. The contract is executable in Python and consumable in TypeScript.
3. Methods are declared plugins, not hidden scripts.
4. The platform can sit above existing analysis and acquisition tools.
5. The roadmap is EEG now, MEA and wetware next, without locking labs into one stack.
