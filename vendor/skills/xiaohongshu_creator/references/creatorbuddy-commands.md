# CreatorBuddy 调用边界

本 Skill 不实现第二套 CLI。所有评分、内容资产、复盘和策略状态都通过 CreatorBuddy 仓库的 `scripts/creatorbuddy.py` 执行。

## 主链路

```powershell
python scripts/creatorbuddy.py run-daily
python scripts/creatorbuddy.py draft --platform xiaohongshu --topic "具体选题"
python scripts/creatorbuddy.py precheck --platform xiaohongshu --title "标题" --content "正文"
python scripts/creatorbuddy.py add-content --platform xiaohongshu --status published --title "标题" --published-at "2026-08-15T20:00:00"
python scripts/creatorbuddy.py post-review --content-id "xhs-..."
```

## 数据与对标

```powershell
python scripts/creatorbuddy.py collect-platform --platform xiaohongshu --kind owned --json '[...]'
python scripts/creatorbuddy.py collect-platform --platform xiaohongshu --kind xhs-note --file note.html --benchmark-id "bench-1"
python scripts/creatorbuddy.py import-benchmark --platform xiaohongshu --url "https://www.xiaohongshu.com/user/profile/..."
python scripts/creatorbuddy.py segment-benchmark --benchmark-id "bench-1"
python scripts/creatorbuddy.py distill-creator --benchmark-id "bench-1"
```

工作区默认是 `%USERPROFILE%\CreatorBuddy`，也可以通过 `--workspace` 指定。Web 工作台只收集输入并展示结果，不应在浏览器代码中复制评分、预检或复盘逻辑。
