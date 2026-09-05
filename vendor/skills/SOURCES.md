# Vendored Skill Sources

The web application vendors fixed upstream snapshots so production does not depend on absolute local Skill paths.

| Web tab | Upstream | Vendored commit | Runtime integration |
| --- | --- | --- | --- |
| 小红书创作 | https://github.com/Gelen5/xiaohongshu-creator-skill | `99c588702577f03f152acd5f65408ecd2bfb6c8d` | Workflow contract and prompt rules in `server/creator_tools.py` |
| 微信贴图号 | https://github.com/Gelen5/wechat-tie-tu-publisher | `aaa8b42fb0f8bcf34a4389e18c527e77b341b7a0` | Native `toolkit.tie_tu.planner.build_plan` plus Web enrichment |
| 爆文检测 | https://github.com/Gelen5/wechat-hit-detector-skill | `3ee75140a358d661af8f2a0a75c65229e6dcd5ec` | Native `scripts/detector.py` loaded by the FastAPI adapter |

When updating a snapshot, refresh the files, run the upstream tests and `tests/test_creator_api_integration.py`, then update the commit recorded here.

The conversational account analyzer reads `wechat_account_analyzer/SKILL.md`, copied from the locally installed `wechat-account-analyzer` on 2026-09-05; no upstream commit is asserted for this local snapshot. Its executable remains `server/wechat_analyzer.py`.

`morning_blessing/SKILL.md` is a project-owned Web adapter contract distilled from the existing morning generator, not a third-party Skill snapshot. The runtime records the loaded document hashes in each conversation.
