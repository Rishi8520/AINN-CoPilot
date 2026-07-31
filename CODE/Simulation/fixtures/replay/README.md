# Simulation Replay Fixtures

This directory contains small, recorded Simulation artifacts retained for
parser tests and replay/demo development. These files are real artifacts that
already existed in the repository before Batch 2 cleanup.

They are not live simulation results from the current startup, and they must
not be presented as proof that Simu5G or OMNeT++ ran during quickstart. Any UI
or API path that replays these files should label them as recorded/replayed.

Runtime Simulation output belongs under `CODE/Simulation/app/scenarios/results`
and runtime generated INI files belong under
`CODE/Simulation/app/scenarios/generated`. Those runtime directories are
ignored by Git except for their README and `.gitkeep` files.

To regenerate equivalent output later, run the full Simulation mode in an
environment with OMNeT++, INET, and Simu5G available. The generated INI should
write scalar output to a runtime `.sca` file and vector output to a runtime
`.vec` file. After validating the new run, copy only the minimal real artifacts
needed for parser or replay tests into a dedicated fixture subdirectory and
record their provenance and checksums in a manifest.

