# Easel OpenClaw Decoupling Audit

Source snapshot: local Easel archive labelled `4b9c03c`; the archive has no
`.git` metadata, so its exact commit identity is not independently verified.
This is a source audit, not an end-to-end migration certificate. Re-run the
inventory with `python scripts/audit_easel_dependencies.py <Easel checkout>`.
The generated [Skill matrix](EASEL_SKILL_COMPATIBILITY.csv) contains all 114
`skills/openclaw/*/SKILL.md` files and their references/scripts inventory.

## A. Portable assets

`SKILL.md` instructions, Markdown references, content templates, most Python
and media scripts, and `skills/shared/` business utilities are files, not a
Gateway API. They can be loaded or called by Universe once their particular
tools, credentials, filesystem assumptions, and side effects have been vetted.
The directory name `skills/openclaw` is not by itself a runtime dependency.

## B. Scheduling logic to migrate

- `easel/commands/skill.py::_list_all_skills`, `_find_skill`, `cmd_skill`:
  discovery and input resolution are reusable; `cmd_skill` currently appends
  `persona_prefix` and delegates execution to `_run_via_openclaw`.
- `web/app.py::get_skills`, `_parse_skill_md`: listing/metadata extraction is
  reusable, but prompt composition and execution are mixed with the CLI path.
- `easel/persona.py::persona_prefix`, `chat_turn_message`: useful profile
  scoping policy; the actual file read from `profiles/<name>` and references
  to `AGENTS.md`/OpenClaw memory must become database-backed run context.
- `AGENTS.md`, `SOUL.md`, `CONTEXT.md`: creator policy and workflow guidance
  need selective extraction into Universe prompt layers; do not inject them
  wholesale or use absolute file paths in Native mode.

## C. Direct OpenClaw/Gateway dependencies

| File/function | Current call path | Native replacement |
|---|---|---|
| `easel/commands/skill.py::_run_via_openclaw` | `cmd_skill` -> `openclaw_base_cmd` -> `subprocess.run(openclaw --profile easel agent ...)` | Universe run/tool loop |
| `web/app.py::run_agent_sync` | chat endpoint -> OpenClaw CLI agent subprocess | Universe Conversation/Run |
| `web/app.py::_gateway_http_ready`, `check_gateway` | web endpoint -> Gateway health | Native provider/worker health |
| `easel/gateway_questions.py::GatewayClient`, `pending_questions_for_session` | Gateway WebSocket `question.*` RPC and device signature | Universe waiting_input/decision |
| `easel/gateway_endpoint.py` | OpenClaw profile config -> Gateway URL/port | none |
| `easel/openclaw_workspace.py::workspace_dir` | `openclaw status --json`/config -> workspace path | scoped RunContext paths |
| `easel/commands/ping.py::cmd_ping` | Gateway health -> OpenClaw agent PONG | Native harness health |
| `easel/commands/gateway.py::cmd_gateway` | CLI -> Gateway process | none |
| `web/app.py::_sync_openclaw_chat` | model settings -> OpenClaw provider config | Universe provider settings |

`web/app.py` also manages OpenClaw session healing, question bridging and
legacy output-directory browsing. None of these paths belong in Universe.

## D. Do not migrate

`easel/openclaw_cmd.py`, `easel/openclaw_workspace.py`, Gateway startup and
device-pairing code, `openclaw/openclaw.json5`, `openclaw/sync.sh`,
`scripts/gateway.*`, `scripts/session_heal.py`, OpenClaw memory indexing,
and CLI wrapper setup are not migrated. Universe already owns sessions,
profiles, run events, storage, billing and providers.

## Skill matrix interpretation

The matrix is a **conservative static triage**, not proof of execution.
`PORTABLE` means no static adapter signal, not tested functional equivalence.
`ADAPTER_REQUIRED` includes ordinary network links, script commands and profile
mentions; some are documentation-only. `OPENCLAW_SPECIFIC` requires an explicit
CLI/Gateway reference in Skill text, not merely the directory name. No row may
be promoted to native-ready without a real run and a tool/side-effect review.

Current snapshot: 114 scanned; 6 preliminary `PORTABLE`, 108
`ADAPTER_REQUIRED`, 0 `OPENCLAW_SPECIFIC`, 0 `UNSUPPORTED` under these
heuristics. This does **not** mean 108 Skills require OpenClaw: they need
individual tool or path analysis. Forty Skill instructions mention OpenClaw,
Gateway or prompt-stack filenames, often only as setup guidance.

## Production gate

Universe contains no Easel OpenClaw process, HTTP adapter, or fallback. The
first ten text-only Skills are behind `EASEL_NATIVE_ENABLED`; their local
database/provider integration is tested. Do not enable the complete Easel
workflow in production until hotspot -> topic -> WeChat article -> Artifact,
profile isolation, SSE, and billing are verified with real providers.
