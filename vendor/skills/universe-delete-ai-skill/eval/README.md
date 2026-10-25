# 可复现评估

12份历史源稿清单在archive/index.json，保留approved-works原文件不移动；缺少历史原稿/检测证据，不是正向样本。
cases/有3份基于真实历史文本快照的新局部校对配对。它们不是追回的历史改写前后版本。
metadata记录体裁、长度、来源、检测结果/时间/模型（缺失为null）、范围、人工确认、事实损伤、通过状态。
复核记录是本次宿主LLM审阅，不是人类确认。来源稿中未经核验的叙述不成为事实依据。

运行：

```powershell
python -m unittest discover -s tests -v
python scripts/run_evaluation.py eval/cases
```

build_evaluation.py仅首次建库，用exclusive写入，重复执行不覆盖。不要自动重建并覆盖审阅结论。
tests包含合成反例，它们不是用户真实稿或检测成功样本。回滚测试数与真实改稿回滚数分别报告。
只有保真/事实/可读门通过且证据完整，才允许讨论positive；当前全部detector未知，不宣称改善。
指标在results/保存。平均/中位数/方差/改善率无有效检测配对时为null，不是0%效果。
真实检测受账号、时间、产品版本影响；网页与API结果不直接拼接。模型版本缺失无法严格同版本比较。
