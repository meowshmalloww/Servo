# Security and Provenance Audit

Audit date: 2026-08-26T22:53:44.781950+00:00

## Secrets: none found in audited source trees

## Local absolute paths in audited source: 4
| file | line | kind |
|---|---|---|
| docs/REALITYCI_BACKEND.md | 117 | user_home_path |
| docs/REALITYCI_BACKEND.md | 124 | repo_drive_path |
| docs/REALITYCI_BACKEND.md | 125 | repo_drive_path |
| docs/REALITYCI_BACKEND.md | 128 | repo_drive_path |

Paths above are runtime-local configuration or documentation of the locked environment; none are embedded in cloud-deployable code under `cloud/`. They must not be committed to the public repository without substitution.

## Dependency licenses (audited set)

| distribution | version | license |
|---|---|---|
| torch | 2.11.0+cu128 | BSD-3-Clause (field) |
| numpy | 1.26.4 | BSD License (classifier) |
| opencv-python | 4.11.0.86 | Apache 2.0 (field) |
| pillow | 12.1.1 | MIT-CMU (expression) |
| pydantic | 2.13.4 | MIT (expression) |
| fastapi | 0.115.0 | MIT License (classifier) |
| uvicorn | 0.32.0 | BSD-3-Clause (expression) |
| starlette | 0.38.6 | BSD-3-Clause (expression) |
| httpx | 0.28.1 | BSD-3-Clause (field) |
| pytest | 9.0.3 | MIT (expression) |
| onnxruntime-gpu | 1.24.4 | MIT License (field) |
| google-genai | 1.65.0 | Apache-2.0 (expression) |
| google-adk | not-installed | - (-) |
| cloudpickle | 3.1.2 | BSD-3-Clause (field) |

## Provenance rules honored by this build
- Background pixels: observed registered frames OR procedural; labeled per scenario.
- Actors: synthetic controllable; never treated as observed data.
- Collision truth: deterministic scenario state only.
- Hidden exams: sealed vault; trainer-side components never receive hidden seeds.
- Generated content would be tagged `generated` and excluded from truth metrics.

## Verdict: RELEASABLE
