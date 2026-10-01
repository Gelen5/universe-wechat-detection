# Easel Native Migration Status

Easel is integrated as Skill files and references, not as an OpenClaw service.
The project vendors only the first ten approved text Skill directories under
`vendor/easel/skills/openclaw` with the upstream Apache-2.0 license. The
directory name is retained to match the upstream package; it does not start
or install OpenClaw. The 114-Skill matrix audits the local upstream snapshot,
not 114 deployed Skills.

## Implemented

- Full 114-Skill static inventory: `EASEL_SKILL_COMPATIBILITY.csv`.
- YAML-based loader with path checks, Markdown instructions and references.
- Native execution using Universe ModelService and existing Tool Loop.
- Ten explicitly selected text-only Skills in the Universe registry, gated by
  `EASEL_NATIVE_ENABLED=1`. They are selectable in the conversation workbench.
- Existing Conversation, Run, RunEvent, billing and Artifact paths remain in
  charge. No separate Easel process, provider config or session store.
- No OpenClaw Harness, Gateway, CLI, runtime container or fallback code.

## Verified on 2026-10-01

- Production runs commit `dc109aa` with `EASEL_NATIVE_ENABLED=1`; public
  `/workbench` and `/health/ready` returned HTTP 200 after deployment.
- A direct paid-provider call and an approved text Skill invocation succeeded.
- `scripts/acceptance_easel_native_http.py` passed against the public HTTPS
  domain: two users ran simultaneously, each finished with one Artifact and
  seven events, each wallet changed from 30 to 20 points, and cross-user
  run, event and Artifact requests were rejected.
- The project test suite passed: 183 tests and seven subtests.

## Not yet production ready

- No `creator_profiles` table exists in this codebase; Native currently accepts
  a profile object from conversation metadata. Database-backed profile storage,
  authorization and memory retrieval remain future work.
- Live hotspot search, media, browser and publisher adapters are not exposed.
  Static Skill instructions alone do not make these capabilities functional.
- The ten text Skills share a verified native execution path, but only the
  tested examples have passed live-provider acceptance. Output quality across
  all ten Skills and real-world tool equivalence remain unverified.
- A real hotspot -> topic -> article -> publisher workflow and browser-level
  SSE reconnect acceptance have not passed.

Production decision: **NOT READY** for the full Easel workflow. Existing
Universe functionality remains unchanged when `EASEL_NATIVE_ENABLED=0`.
