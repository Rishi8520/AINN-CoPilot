# Simulation Modes

TelcoMind Simulation has two explicit execution modes: `replay` and `live`.
They are intentionally separate so callers cannot confuse recorded fixture
output with a newly executed Simu5G/OMNeT++ run.

## Mode Comparison

| Capability | `replay` | `live` |
| --- | --- | --- |
| Default for submission quickstart | Yes | No |
| Requires OMNeT++/INET/Simu5G | No | Yes |
| Requires Docker, GPU, network, or model downloads | No | No GPU/model requirement; live Simu5G dependencies must exist |
| Uses production KPI parser | Yes, against recorded `.sca` fixture | Yes, against live runner outputs when a phase completes |
| Can report `completed` | Yes, after manifest/checksum validation and parser success | Only after a real runner phase succeeds and parsed output is non-empty |
| Silent fallback | Never | Never falls back to replay |

## Environment Variables

```env
SIMULATION_DEFAULT_MODE=replay
SIMULATION_REPLAY_FIXTURE=phase_bootstrap_normal
SIMULATION_REPLAY_STRICT_CHECKSUMS=true
SIMULATION_LIVE_ENABLED=false
```

Mode precedence is:

1. Valid request `mode`
2. `SIMULATION_DEFAULT_MODE`
3. Safe default `replay`

Only `replay` and `live` are accepted modes.

## Replay Mode

Replay mode reads the approved fixture:

`CODE/Simulation/fixtures/replay/phase_bootstrap_normal`

Supported replay scenario aliases are:

- `baseline`
- `normal`
- `normal_operation`
- `bootstrap_normal`
- `phase_bootstrap_normal`

Replay validates `manifest.json`, verifies listed files and SHA-256 checksums
when strict mode is enabled, identifies the scalar output by manifest role, and
uses `app.simulator.kpi_parser.KPIParser.parse_sca_file`.

Replay responses include `live_simulation: false`, `mode_label:
recorded_replay`, fixture id, source artifact names, checksum status, parser
identity, and manifest-relative result references. Requested `ue_count`,
`cell_id`, `slice_type`, and `seed` do not alter the recorded fixture and are
reported as unsupported parameters rather than applied parameters.

Replay proves parser compatibility, stable KPI extraction, and traceable
provenance for one recorded healthy bootstrap run. It does not prove current
live Simu5G execution, fault/degraded behavior, Docker startup, live vector
polling, or dynamic request-parameter application.

## Live Mode

Live mode uses the existing `TimelineRunner` and requires
`SIMULATION_LIVE_ENABLED=true`. Before serving live requests, readiness checks
probe the configured `opp_run`, working directory, INET/Simu5G libraries, NED
path entries, scenario assets, runtime result directories, and runner object.

If live mode is disabled or prerequisites are missing, `POST /simulate` returns
a structured failure/unavailable response and does not use replay data. Stale
cached metrics do not make a stopped or failed live runner appear completed.

## API Examples

Replay request:

```json
{
  "scenario": "baseline",
  "ue_count": 20,
  "cell_id": "cell-1",
  "slice_type": "eMBB",
  "mode": "replay"
}
```

Live request:

```json
{
  "scenario": "baseline",
  "ue_count": 20,
  "cell_id": "cell-1",
  "slice_type": "eMBB",
  "mode": "live"
}
```

The older query-parameter form remains available for compatibility, but JSON is
canonical. When both JSON and query parameters are supplied, the JSON body wins.

## Liveness And Readiness

- `GET /health` reports FastAPI process liveness only.
- `GET /ready` reports replay readiness, live readiness, configured default
  mode readiness, fixture validation, and missing live prerequisites. It returns
  `200` when the configured default mode can serve requests and `503` when it
  cannot.
- `GET /capabilities` returns the same mode capability details without using
  HTTP status as the readiness signal.

Full live mode can later be enabled in an environment with OMNeT++, INET, and
Simu5G installed by setting `SIMULATION_LIVE_ENABLED=true` and configuring the
existing live runner environment variables such as `OPP_RUN_BIN`,
`SIMU5G_NED_PATH`, `INET_LIB`, `SIMU5G_LIB`, and `OPP_RUN_CWD`.
