# 手动黑盒回归

本Skill不调用朱雀API、不填写密钥、不自动上传文章，也不操作验证码。
用户在朱雀页面自行检测后，可提供截图、报告或结构化记录。只录入看得见的字段，不从颜色猜句子，不把“疑似AI”当作者身份结论。

用于程序比较的最小JSON：

```json
{
  "text_sha256": "被检测文本的SHA256",
  "risk": 0.74,
  "checked_at": "2026-09-06T20:00:00+08:00",
  "source": "Tencent Zhuque web manual test",
  "comparison_id": "same-page-session-2026-09-06-01",
  "raw_result": {"human": 0.26, "suspected_ai": 0.74, "ai": 0.0},
  "model_version": null,
  "evidence": "用户截图文件名或本地报告路径"
}
```

`risk`是本项目为版本排序而人工录入的可比较风险值，范围0到1；优先使用页面“疑似AI+AI”可见比例之和。若页面只给分类、没有比例，则不伪造risk，保留文字结果，不进入自动数值比较。
原稿与改稿必须使用相同页面条件、排版口径，并分别绑定实际文本SHA256。每组前后检测使用同一个非空`comparison_id`；缺时间、来源、比较编号或哈希不比较。
模型版本页面未提供时填null，不用网页更新时间冒充检测模型版本。

在rounds.json对应轮次添加detector_feedback，并用`--baseline-feedback baseline.json`提供原稿记录：

```powershell
python scripts/revision_workflow.py original.md --manifest manifest.json --rounds rounds.json --baseline-feedback baseline.json --output final.md
```

反馈只能影响通过本地保真门后的版本选择。分数降低但语义、事实、立场或可读性失败，仍回滚。
连续两轮改善不足或达到3轮即停。没有反馈时只接受一轮本地合格修改，不继续猜检测器。
