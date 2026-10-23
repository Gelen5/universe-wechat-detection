# 部署手册（给任何 agent / 任何人）

线上：`https://yuzoudiyigongzuotai.cn/` · 服务器 `116.62.241.51` · 用户 **admin** · compose 项目 `908c31a`

---

## 一、登录

唯一可用的密钥（本机已有，任意进程用同一 Windows 账号即可读）：

```
C:\Users\16972\.ssh\universe_deploy
```

```bash
ssh -i "C:\Users\16972\.ssh\universe_deploy" admin@116.62.241.51
```

- 用户名是 `admin`。**没有 `gelen` 这个用户**。
- `admin` 拥有 `NOPASSWD: ALL` 的 sudo。

---

## 二、部署（唯一入口）

```bash
# 1. 取最新提交号（本地或服务器都可以）
git ls-remote https://github.com/Gelen5/universe-wechat-detection.git refs/heads/main | cut -c1-7

# 2. 部署该提交
sudo -n bash /opt/universe-deploy/deploy.sh <短sha>

# 不带参数 = 部署当前 main
sudo -n bash /opt/universe-deploy/deploy.sh

# 回滚
sudo -n bash /opt/universe-deploy/deploy.sh --rollback <短sha>
```

脚本做的事：

```
codeload 下载指定提交的 zip（不依赖 git 协议，服务器 git 拉取经常超时）
→ 解到 /opt/universe-wechat-detection-releases/<sha>（永远新建，不覆盖旧目录）
→ .env 软链到 /etc/universe-wechat-detection.env
→ 给当前运行的镜像打 <旧sha> 标签（回滚用）
→ docker compose build web worker beat migrate
→ docker rm -f 908c31a-migrate-1
→ up -d --no-deps web worker beat
→ 等 /health/ready（45×2s）
→ 验收：intent / 真搜索 / 进度卡 / 书架 + 版本号 + /bookshelf
→ 打印线上 sha 与回滚命令
```

正常耗时 **1～2 分钟**（镜像缓存热的情况下）。

---

## 三、部署后自检

```bash
curl -fsS http://127.0.0.1:8000/health/ready
curl -s -o /dev/null -w "home=%{http_code}\n"   https://yuzoudiyigongzuotai.cn/
curl -s -o /dev/null -w "market=%{http_code}\n" https://yuzoudiyigongzuotai.cn/market
curl -s https://yuzoudiyigongzuotai.cn/api/market/meta | head -c 120
sudo -n docker ps --format '{{.Names}} | {{.Status}}' | grep 908c31a
```

AI 超市页面是否内嵌在工作台里：`curl -s https://yuzoudiyigongzuotai.cn/market | grep -c 'id="market"'` 应为 `1`。

---

## 四、不要这样做（今天线上被回退两次的原因）

```bash
# ❌ 会在旧目录里 fast-forward 失败，或把旧代码重新构建上线
sudo git -C /opt/universe-wechat-detection-releases/a1939d1 pull --ff-only origin main
sudo docker compose -p 908c31a --project-directory .../a1939d1 ... up -d --build web worker beat
```

两个具体故障：

1. `a1939d1` 目录的 git 已分叉（`## main...origin/main [ahead 5]`），`pull --ff-only` 直接报
   `fatal: Not possible to fast-forward, aborting`，代码根本没更新。
2. `up -d --build` 会重建一次性 `migrate` 服务，撞上残留容器名：
   `Conflict. The container name "/xxx_908c31a-migrate-1" is already in use`。

如果坚持手动部署，至少这样：

```bash
cd /opt/universe-wechat-detection-releases/<新目录>
sudo docker rm -f 908c31a-migrate-1
sudo docker compose -p 908c31a --env-file /etc/universe-wechat-detection.env \
  up -d --no-deps --build web worker beat
curl -fsS http://127.0.0.1:8000/health/ready
```

---

## 五、日常排查

```bash
sudo -n docker logs --tail 100 908c31a-web-1
sudo -n docker logs --tail 100 908c31a-worker-1
sudo -n docker inspect -f '{{index .Config.Labels "com.docker.compose.project.working_dir"}}' 908c31a-web-1
sudo -n ls -1dt /opt/universe-wechat-detection-releases/* | head -5
```

- AI 超市数据快照：`/opt/universe-data/output/market/{skills.json,meta.json,custom.json}`
- 每日同步：Celery beat `market-sync-daily`（04:10），手动触发见 `POST /api/admin/market/sync`
---

## 六、已授权的密钥

`/home/admin/.ssh/authorized_keys` 当前三把：

| 指纹 | 备注 |
|---|---|
| `SHA256:HG6WeHa/...` | swas-imported-key（早期，ECDSA） |
| `SHA256:iuUfLjQb...` | codex-universe-deploy（ED25519） |
| `SHA256:GHSl8BMmtYODTkRLgWxgRzgyX1wROJR4/eVkm4TYBig` | **window3-deploy**（ED25519） |

短命令已安装在服务器：

```bash
universe-deploy              # 部署当前 main
universe-deploy <sha>        # 部署指定提交
universe-deploy --rollback <sha>
```

（内部是 `sudo -n bash /opt/universe-deploy/deploy.sh "$@"`）