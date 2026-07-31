# phase_bootstrap_normal Fixture

`phase_bootstrap_normal` is a recorded real Simulation artifact kept from the
repository's historical runtime output. It is retained because it is the
smallest complete run found with a generated INI, scalar output, and vector
index metadata.

Included files:

- `phase_bootstrap_normal.ini`: generated configuration that requested
  `phase_bootstrap_normal.sca` and `phase_bootstrap_normal.vec`.
- `phase_bootstrap_normal.sca`: OMNeT++ scalar output consumed by the
  production KPI parser.
- `phase_bootstrap_normal.vci`: OMNeT++ vector index metadata that records the
  same run identifier and generated INI path.
- `manifest.json`: file sizes, SHA-256 checksums, expected parser structure,
  and provenance notes.

This fixture is for parser tests and clearly labelled replay/demo paths. It is
not evidence that Simu5G ran during the current startup.

Equivalent output can be regenerated later by running full Simulation mode in
an environment with OMNeT++, INET, and Simu5G installed. Runtime scalar,
vector, vector-index, generated-configuration, and history files are expected
to be produced under `CODE/Simulation/app/scenarios/results` and
`CODE/Simulation/app/scenarios/generated`; those runtime directories are
ignored by Git and should not contain bulk tracked artifacts.

