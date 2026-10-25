# universe-delete-ai-skill

保真优先的中文改稿 Skill：尽量少改，减少机械表达，不把原稿改成另一篇文章。
不承诺朱雀“人工特征100%”；检测结果必须是真实返回，不能替代事实与中文质量。

## 普通用户

对加载此Skill的Agent说：

> 使用 universe-delete-ai-skill 处理这篇文章，尽量保持原文。保留事实、人物关系、数字、引用和立场。

默认minimal；standard须有局部结构问题，deep须明确授权或原文结构严重不可用。
原稿和候选保留，失败回滚，不为检测制造错字、病句、假亲历或漏标点。
需要朱雀结果时，由用户在网页端自行检测并导入绑定文本哈希的记录；Skill不联网、不上传稿件。

## 能力与实际限制

- 精确原稿哈希、保护片段按次数/顺序/位置检查。
- 数字、日期、引用、URL、代码、否定/限定，以及编辑补齐的实体清单。
- 显式编辑计划与输出一致；累计字符/句子/段落修改率，Markdown结构保护。
- 程序检查 + 有证据的语义、立场、因果与可读性复核，缺复核不放行。
- 有限单变量回归、拒绝损伤稿、自动选择原稿或已接受版本，最多3轮。
- 可选手动黑盒反馈：用户自行检测后录入风险值、时间、来源与文本哈希，程序只做版本比较。
- 12份历史样本审计；3份真实文本快照局部校对配对，无真实检测证据。

程序不是通用语义理解模型。实体清单与语义审阅由宿主Agent完成；不把“原稿一致”说成“史实正确”。
当前没有密钥实测成绩，样本不能称正向过检范文。详见[审计](eval/repository-audit.md)。

## 开发与复现

Python 3.10+，标准库，无需安装依赖。Windows建议PYTHONUTF8=1。
脚本必须从仓库根目录运行，保留文件真实换行，不手工标准化后复用旧哈希。

```powershell
python -m unittest discover -s tests -v
python scripts/run_evaluation.py eval/cases
python scripts/audit_repository.py --baseline 18070a3e672f32347503a298f69077071871e5a0
```

原稿 → build_manifest.py → 编辑Plan → preservation.apply_plan → 候选 → semantic_gate.py --review-template
→ 宿主完成真实审阅 → semantic_gate.py --review → revision_workflow.py。

```powershell
python scripts/build_manifest.py original.md --entity 李清照 --entity 张汝舟
python scripts/semantic_gate.py original.md revision.md --manifest manifest.json --plan plan.json --review-template
python scripts/semantic_gate.py original.md revision.md --manifest manifest.json --plan plan.json --review review.json
python scripts/revision_workflow.py original.md --manifest manifest.json --rounds rounds.json --output final.md
```

JSON默认输出stdout。用支持UTF-8且保留换行的宿主保存，不把Windows PowerShell默认UTF-16重定向结果当UTF-8。
rounds.json为包含plan/review对象的数组，样例在eval/cases各目录。不能复制样例PASS到新稿；模板必须重新审阅。
输出文件必须不存在。FAIL/REVIEW_REQUIRED回滚，工作流退出1；配置错误退出2，不覆盖输入。

## 手动检测反馈

本仓库不接入朱雀API、不保存密钥、不自动上传正文，也不操作网页验证码。用户可在网页端自行检测，随后把可见结果记录成JSON：

```powershell
python scripts/revision_workflow.py original.md --manifest manifest.json --rounds rounds.json --baseline-feedback baseline.json --output final.md
```

[手动黑盒回归](references/manual-detector-feedback.md)说明字段、版本绑定和停止条件。没有数值就不伪造数值，没有同条件前后结果就不计算改善率。历史网页公开探针只读取公开演示，不在默认工作流中，也不会提交用户稿。

## 新旧脚本区别

| 脚本 | 用途 |
|---|---|
| preservation.py / build_manifest.py | 保护账、计划执行、diff与版本绑定 |
| semantic_gate.py | 新放行门，PASS/FAIL/REVIEW_REQUIRED |
| revision_workflow.py | 有限回归与自动回滚 |
| manual-detector-feedback.md | 手动反馈格式与同条件比较规则 |
| build_evaluation.py / run_evaluation.py | 真实快照配对、缺测区分 |
| audit_repository.py | 文件清单和入口链接审计 |
| check_ai_tone_signals.py / check_natural_prose.py | 历史启发式，仅定位/观察 |
| check_protected_spans.py / audit_revision.py / verify_minimal_diff.py | 旧版兼容报告，不代替新门 |
| evaluate_corpus.py / ingest_story_sources.py | 旧语料扫描/来源审阅队列，不证明有效或已核验 |

## 参考与样本

[最小编辑](references/minimal-edit.md) · [保真](references/semantic-preservation.md) ·
[中文回读](references/chinese-natural-writing.md) · [评估](eval/README.md) ·
[历史隔离](references/archive-policy.md) · [实验门槛](experimental/README.md)。

旧Prompt和12份approved-works原文保留，但退出默认改稿指令与正向数据集。
本次只修改代码仓库分支，不自动覆盖已安装Skill；安装目录需另行核验同步。

[第三方归属](THIRD_PARTY_NOTICES.md)。上游统计未独立复现，不作为朱雀公式。
