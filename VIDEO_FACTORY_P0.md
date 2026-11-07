# AI 视频工厂：隔离验证记录（未上线）

基线：工作台 `7515da767e0c5e5d45ada729568339b33d1add6a`；MPT `8b0206be2c7977e3bc3cf25ff99a2adc3c9c65f9`（MIT）。MPT 独立 Python 3.12 环境，不安装进主站；本地 API 仅监听 127.0.0.1。样例未使用真实用户账号、积分或生产数据库。

可复用：`accounts.create_job`/`reserve_points`/`settle_usage_with_points`/`refund_usage`、Celery、`workbench.provider_overrides`、`image_provider.generate`。现有 `artifacts` 类型约束没有 video；新增视频需迁移和鉴权资产接口。现有异步任务 ID 不等于 MPT task ID，必须持久化映射。

本次仅实现独立适配器和基础技术检查，**未注册路由、任务、菜单或计费，也不可向用户开放**。MPT 本地素材按固定时长拼接并循环，`match_materials_to_script` 只保证顺序，不能保证逐镜对齐；需要独立验证带时间轴的最小渲染方案。MPT 拒绝删除运行中任务，不能冒充取消。创建请求超时的远端结果未知，切勿盲目重发。

第三方参考：book-video-production-skill `c36b50827676096021103d95c5323a91937b7620`（MIT）；history-story-video `d5ba8d457cf3d9223d3e53b285e8240897b6c860`（MIT）；当前未复制这两个仓库的代码或提示词。未使用 jx-booklist-video 源码。

上线前必须完成：合法商用 TTS 和素材授权验证、可靠事实来源、镜头与音频的真实对齐、断点恢复和不可重试的付费调用查单、视频鉴权/存储及清理、成本核算和积分定价、单并发限制、语音/字幕/黑屏/画面质量检查、四个赛道实片和移动端验收。MPT 目前使用 Edge TTS 仅用于本地技术测试，未验证商用许可。

配置建议仅用于后续开发：`VIDEO_FACTORY_ENABLED=false`；独立内部服务地址及密钥由服务端注入，生产前配置访问控制与网络隔离，禁止将测试服务直连公网。现无数据库迁移或生产部署；回滚只需移除本分支文件，独立测试环境单独清理。

本机验证：MPT 上传、创建任务、轮询、中文 TTS、字幕及 MP4 输出可用；测试成片 1080×1920、H.264/AAC，36.62 秒，完整解码成功，但不满足 30 秒目标。脚本和单张测试图片均为人工准备，不代表主题到成片的自动生产。`book_plan` 仅验证模型输出中的来源 URL 是否属于给定列表，不代表核实来源或事实。一次隔离文字模型调用在现有共用地址收到 HTTP 401，未重试；需要可用的服务端 Provider 配置才能验证真实文案和成本。

30 秒复测：调整中文 TTS 语速至 1.2 后，生成 30.53 秒 1080×1920 MP4；完整 FFmpeg 解码通过，SRT 时间戳有效。该片仍是手写脚本及一张自制测试图，不具备经核实的分镜、配乐或素材授权，不能当作验收样片。测试环境峰值仅采到 Python 进程约 357 MiB，未包含子进程，不代表整机峰值。

## 2026-11-07 继续实施

- `server/video_factory_plan.py`：四赛道共用计划结构、来源引用与长度预检；来源是否真实、陈述是否被支持仍需事实审核。
- `server/video_factory_scene_renderer.py`：按每段实测配音时间拼接图片和音频，合并并烧录 SRT；可为已授权音乐做背景混音。实际检出目标时长与音频偏差过大时拒绝渲染。
- `server/video_factory_pipeline.py`：本地检查点，已完成的生图和配音不重跑；远端创建结果不明时停下等待查单。独占锁为本机文件，进程异常退出后需人工检查清理，不适合直接作为跨机锁。
- 四条草稿已生成于 `D:/Download/video-factory-samples` 的 `book-refined`、`history-refined`、`folklore-refined`、`china-photos-draft`。每条 `final-with-music.mp4` 是配乐版，实际时长分别约 46.34、61.93、58.96、44.16 秒。均通过解码、字幕时间戳和长黑屏/静音检查，但仍需内容与授权审核；桂林是两张 CC0 实拍照片，不是实拍视频，历史图有人物服饰不一致和虚构地图。生成的配图及语音商用授权尚待核对。配乐为 Commons CC0 文件 `Emotional piano.wav`，具体来源见各自 sources.json。
- 配置只读测试发现线上文字和图片 Provider 可用；发生真实供应商测试调用，但没有修改生产数据库或扣真实用户积分。共享调用总用量和9次成功生图记在 `cost_report_overall.json`，图像接口返回零用量，无法推算人民币实际成本。
- 用户可用的 FastAPI、Celery、积分/Artifact、权限和前端后来已在分支接入，详见下一节；仍未完成4条符合内容、素材、配音授权的验收样片。不部署不开放。MPT 无运行中任务取消；逐镜合成虽已实测，但不等于人物一致性、语音同步、质量或版权自动通过。上线至少还需可核对的 TTS 和素材授权、真实价格与成本上限、付费服务查单、可靠的跨机故障恢复、结果与UI实机联调。

## 2026-11-07 工作台接入收口

- 已接入 `/api/video-factory/jobs`、Celery 任务、积分预扣/失败退款、鉴权下载、成果包和 `/video-factory` 页面；`VIDEO_FACTORY_ENABLED=false` 时页面只读、提交返回 503。默认 `VIDEO_FACTORY_POINTS=0`，不能把零积分测试配置当成正式定价。
- `video_factory.run` 使用独立 `video_factory` 队列和 `video-worker`，避免占用普通生图 Worker。数据库 `job_slots` 租约按 `VIDEO_FACTORY_MAX_CONCURRENT`（默认 1）限制跨进程并发，并定期续租；默认 Worker 并发也是 1。
- 远端生图 URL 只允许公网 HTTPS、禁止重定向、限制 24MB，复用现有 `storage.image_ingest._download`；Provider 返回的任意私有地址不会直接请求。
- 渲染前按目标时长限制镜头数和最短旁白时长，避免计划通过但逐镜时长不足造成无效成片。该检查不替代人工音画、事实和授权审核。

### 启动与配置

本地关闭状态下只需正常启动 Web。内部验收需要 MPT 服务端地址、密钥、可用的文字/图片 Provider 和独立 Worker；不要把这些值写进代码或聊天。启动顺序为 `migrate → web/worker/beat → video-worker`，`video-worker` 必须消费 `video_factory` 队列。若使用对象存储，必须配置私有 S3 兼容存储和短期签名；本地存储只适合隔离测试。

试用部署使用同镜像内的 `video-tts` 轻量服务，不再部署完整 MoneyPrinterTurbo。该服务只实现现有适配器需要的 `/api/v1/subtitle`、任务查询、MP3 与 SRT 下载，使用 Edge TTS 7.3.1 和 ffprobe；接口带独立 `VIDEO_TTS_API_KEY`，`video-worker` 通过 Docker 内网访问。真实中文配音验证生成 8.54 秒 MP3、有效 SRT，且现有 `MptRenderer` 下载链路通过。

### 回滚

改回 `VIDEO_FACTORY_ENABLED=false` 即可对用户关闭入口和 API，不删除已有任务或素材。若需停止 Worker，先停止 `video-worker`，再删除/停用独立队列；不要直接清空仍在运行的 MPT 任务。代码回滚应移除本轮视频工厂文件和接入改动，不能删除用户已有对象存储成果。

### 仍未验收

- 未完成一条从新 API 经真实 Provider、真实 MPT 到 MP4 的付费 E2E；底层四赛道样片已验证，不能替代工作台端到端验收。
- 运行中断后的远端生图/配音查单、Cross-machine 检查点锁、成果保留期与清理任务、Provider 实际用量写回和人民币成本仍待完成。
- 四条现存草稿仍有内容、人物一致性、音画同步和素材/配音商用授权问题，不能报告为验收样片或宣称已上线。
