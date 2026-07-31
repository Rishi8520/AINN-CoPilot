# Final Submission Checklist

Items are marked truthfully based on verified repository evidence. Unverified or
manual-pending items are left unchecked.

## Repository and Source

- [ ] Repository pushed to remote (final release commit + tag)
- [x] Source present (Agent, RAG, Simulation, UI, Gateway)
- [x] Root README.md
- [x] One-click deployment (`deploy.ps1`, `deploy.sh`, `docker compose up -d --build`)
- [x] Prerequisites and expected outcomes documented

## Licensing and Documentation

- [x] LICENSE (Apache 2.0)
- [x] Third-party notices (THIRD_PARTY_NOTICES.md)
- [x] Technical report source (TECHNICAL_REPORT.md)
- [x] Technical report PDF (TECHNICAL_REPORT.pdf)
- [x] Demo video link (Google Drive folder in README)

## CI and Testing

- [x] GitHub Actions workflow (.github/workflows/ci.yml)
- [x] Tests present and runnable (test.ps1 / test.sh / offline matrix)
- [x] E2E scenarios (8/8 passed — Batch 9)
- [x] Failure injection and recovery validated

## Hygiene and Git State

- [x] Final hygiene (PASS=37, WARN=12, FAIL=0)
- [x] Clean Git state at submission prep (no stray tracked artifacts)
- [ ] Release tag `submission-v1.0` created
- [ ] ZIP archive built (dist/AINN-CoPilot-submission.zip)
- [ ] SHA-256 checksum file generated
- [ ] EvalAI upload completed
- [ ] Final submission verification completed
