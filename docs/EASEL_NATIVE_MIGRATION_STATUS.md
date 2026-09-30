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
  `EASEL_NATIVE_ENABLED=1` while real-provider acceptance is pending.
- Existing Conversation, Run, RunEvent, billing and Artifact paths remain in
  charge. No separate Easel process, provider config or session store.
- No OpenClaw Harness, Gateway, CLI, runtime container or fallback code.

## Not yet production ready

- No `creator_profiles` table exists in this codebase; Native currently accepts
  a profile object from conversation metadata. Database-backed profile storage,
  authorization and memory retrieval remain future work.
- Live hotspot search, media, browser and publisher adapters are not exposed.
  Static Skill instructions alone do not make these capabilities functional.
- The ten text Skills have been exercised with a deterministic fake provider,
  not a paid live model. Output quality and real-world tool equivalence are
  not verified.
- A real no-OpenClaw hotspot -> topic -> article -> Artifact test, SSE reconnect
  and multi-user production deployment test have not yet passed.

Production decision: **NOT READY** for the full Easel workflow. Existing
Universe functionality remains unchanged when `EASEL_NATIVE_ENABLED=0`.
