# 保真门：程序 + 语义回读

先运行build_manifest.py original.md --entity 李清照 --entity 张汝舟。
编辑补齐人物、组织、地点、产品、术语；程序不假装识别全部中文实体。
自动锁数字、汉字数词+量词、时间、URL、引号原话、代码、引用块、链接、否定与限定。
记录每次出现的位置和原字面，重复数字/同名实体不去重，检查数量、顺序和新增。

## 复核记录

semantic_gate.py original.md revision.md --manifest manifest.json --plan plan.json --review-template
输出模板默认REVIEW_REQUIRED，不自动填写PASS。
审阅者填写reviewer、reviewer_type（llm/human）、reviewed_at、entities_complete及各维度证据：

- theme/claims：原结论全保留，不能把“不心疼而纳闷”改反。
- facts/entities：谁对谁做什么；仅保留姓名不够。新增孩子/博物馆等无据事实即FAIL。
- causality/time_order：原因、结果、条件、顺序是否变了。
- stance/negation：怀疑变确定、可能变一定、部分变全部是否发生。
- quotes：原话及引用人对应，不把转述编成对白。
- readability/naturalness：句法、指代、标点、承接和声音是否退化。

每个diff片段在change_reviews写具体reason，必须读上下文，不能机械填写“意思一样”。
复核绑定原稿、候选、manifest、plan四个哈希；任何内容修改后重新审阅。
没有改字也不证明原文事实准确，基线仍须可读性审阅。
运行semantic_gate.py带--review review.json，PASS退出0，否则1。
工作流自动选择合格稿或原稿，写全新文件，不覆盖输入。

## 边界

哈希防版本误用，不是签名认证；恶意手填PASS无法识别。只接受可信执行者真实审阅。
当前没有额外调用独立语义模型，宿主Agent负责LLM回读；不可称“机器已证明语义100%一致”。
主体互换、因果反转、事实真实性不能只靠正则。高风险稿建议独立编辑二审。
正则会漏识别/过保护（复杂Markdown、词素不、单引号等），不得靠删词表让测试变绿。
模板含原文片段，只本地保存；工作流正常日志只输出哈希、比率、状态和安全错误码。
