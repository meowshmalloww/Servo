# Climate Weather Bundle

`servo.climate-weather/v1` is an immutable sidecar. Required identity includes the base-world hash, dataset hash, source receipt, engine/effect, parameters, coordinate/scale state, readiness, outputs, validation, producer and explicit visual-only physics flags.

Every output is `{ "path": "relative/path", "sha256": "sha256:..." }`. Paths must remain inside the bundle. `bundle_sha256` is the SHA-256 of canonical JSON excluding that identity field. Publication validates staging, copies to a unique temporary sibling, validates again, and atomically renames. Existing destinations are never overwritten.

The verifier rejects missing assets, path escape, hash mismatch, non-finite parameters, unsupported engines/effects, non-generated provenance, and any claim that visual output changed collision geometry, friction, measured water depth, or snow mass.

Base worlds and shared checkpoints are external references and are never deletion targets of this publisher.
