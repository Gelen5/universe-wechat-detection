# 公众号 Skill 的节点写作规则

## 2026-10-26：移除统一框架与审计式正文倾向

排查用户提供的会议纪要教程后，确认 Web 框架提示词仍硬性限制七种框架并以 SCQA 为示例和缺省名；首次成稿也统一要求生活场景开头、人物承载和特定收尾，与文体规则冲突。本次移除这些硬性统一要求，以本篇读者问题、实际材料和用户指定文体设计推进方式。选题类型作为线索传入，口吻不再等同于文体；旧状态恢复也不补上 SCQA 标签。

素材缺口留作编辑记录。普通教程不因缺少实测而自动变成测试计划、审计声明与待填清单；撤回无依据的效果宣称，必要演示明确标注，保留影响读者决策的真实风险和限定。用户明确要求实验设计或合规说明时继续遵守。复核节点可定位重复解释、编辑记录误入正文等阅读问题，但不新增默认全文重写或无上限模型循环。

公众号一键成文的初稿提示词也加载同一份 draft 规则，旧稿、用户提纲、排版、收费与事实门禁保持兼容。此变更不额外增加模型请求、不接入检测器，也没有把格式、句长或内部通过状态当作朱雀检测结果。

## 规则源与加载

用户原始 `反AI检测通用方法论.md` 已存档为 `vendor/skill-extensions/weChat-autoCreate/references/anti-ai-methodology.md`，本次不修改原文。运行时只读同目录的三份短协议：

| 节点 | 文件 | 作用 |
| --- | --- | --- |
| strategy | human-writing-strategy.md | 按文章类型选择表达方式，整理材料与缺口 |
| draft | human-writing-draft.md | 首次成稿具体自然，不编造经历或细节 |
| review | human-writing-review.md | 定位局部问题，按语境处理，保护事实与原意 |

统一加载器位于扩展目录 `node_rules.py`。工作台通过 `server.skill_runtime.node_rules` 加载；Skill 原生 `toolkit.article_workflow._host_request` 通过受控补丁加载同一模块，host request 包含 reference 路径、短规则和 SHA-256。topic/research/delivery 不加载这三份规则。

## 数据与兼容

框架节点在原有一次 JSON 模型请求中返回 `writing_strategy`，包含 article_type、expression_mode、available_materials、material_gaps、forbidden_additions。正文节点读取框架中的该字段，不另请求策略。状态恢复时从 ArticleState 恢复，兼容旧版框架或字段缺失，不为了迁移旧任务额外调用模型。

现有复核轮次、时限、事实保真、篇幅和完整句审计保留。正常破折号、冒号、步骤编号、代码和引语不再被机械判定为必须改写；检测脚本信号仍提供给复核，但需要结合语境解释，不能要求清零。没有人物材料时不补故事；不故意制造病句、方言或随机情绪，不承诺检测器分数。

## 上游更新

原生 Skill 仅有文档登记和一个 host-request 接入点，完整变更记录在 `native-node-rules.patch`。`scripts/sync_vendored_skill.sh wechat` 同步后检查并重放补丁，遇到上游结构冲突则显式退出；保留本仓库的 VENDORED.md 元数据并回写上游版本。补丁之外的规则均在同步目标目录外，避免 rsync --delete 删除。

## 验证范围

```powershell
$env:WECHAT_PUBLISHER_SKILL_DIR=(Resolve-Path vendor/skills/weChat-autoCreate).Path
$env:UNIVERSE_ANTI_AI_SKILL_DIR=(Resolve-Path vendor/skills/universe-delete-ai-skill).Path
python -m pytest tests/test_human_writing_nodes.py tests/test_stage_executors.py tests/test_workbench_pipeline.py tests/test_review_cases.py tests/test_workbench_optimizations.py tests/test_skill_runtime.py tests/test_workflow_api.py tests/test_workflow_tasks.py tests/test_workflow_billing.py tests/test_workflow_repository.py tests/test_stage_context.py -q
```

覆盖两条路径的内容哈希一致、规则按节点隔离、四类文章的策略传递、原有调用次数、旧框架兼容、ArticleState 恢复、原始文档不变、原生无扩展回退，以及补丁撤销后重新应用。模型响应使用受控测试替身；这些测试验证规则加载和流程，不证明实际生成效果或朱雀分数。未接入检测服务、未上传文章。

本轮验证结果：工作台相关 138 项测试与 8 个子测试通过；另外在本地执行 Skill 原生工作流 11 项测试通过，未将其加入平台 CI。同步脚本 Bash 语法检查通过。
