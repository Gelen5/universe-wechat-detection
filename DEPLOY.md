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

## 二点五、本地开发：改代码不用重建镜像

本地机器**没有 Docker**（只有 Python 3.14），所以本地开发不走容器，直接用热重载：

```powershell
powershell -File scripts\start-local.ps1          # 热重载开启，默认 8000 端口
powershell -File scripts\start-local.ps1 -Port 8812   # 换端口（8000 被占用时）
powershell -File scripts\start-local.ps1 -NoReload    # 关闭热重载
```

行为：

- **改 `server/*.py`** → 自动重启，1 秒内生效，**不需要重建镜像**
- **改 `static/*`（HTML/CSS/JS）** → `StaticFiles` 每次请求都从磁盘读，**刷新浏览器即可**，连重启都不用
- **改 `vendor/` 下 Skill 文本** → 调用时才读，下次调用自然生效
- **只有改 `requirements.txt` / `Dockerfile`** 才需要真的重建镜像

热重载只监听 `server/`，刻意不监听 `static/`、`vendor/`、`output/`、`tests/`：
把这几万个文件纳入监听会拖慢启动，并让保存一个测试文件就触发无意义的重启。

> ⚠️ 本地 `start-local.ps1` 用的是 SQLite（`data/creator_accounts.db`）且没有 Redis，
> 所以 `/health/ready` 会返回 `redis:false`。这是本地环境的正常现象，不代表代码有问题；
> 线上自检请看第三节，那边要求 `database/redis/better_auth` 全为 `true`。

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

## 五点五、磁盘与镜像保留策略（必须遵守）

这台机器只有 **40G 盘 / 1.6G 内存**，磁盘堆满会让构建被 OOM 杀掉，历史上出现过 80 分钟的冷构建。
2026-10-31 清理时 160 个镜像 + 9.4GB 构建缓存把盘占到 **74%**，清理后降到 **55%**。

**保留规则：**

| 对象 | 保留 | 说明 |
|---|---|---|
| `908c31a-*` 镜像 | **最近 2 个 sha 标签 + `latest`** | 当前线上版本 + 上一个可回滚版本 |
| Build Cache | **约 2～4GB** | 必须保住 `fonts-noto-cjk` 和 `pip install` 两层 |
| 基础镜像 | 全留 | `python:3.12-slim`、`node:24.18.0-bookworm-slim`、`postgres:16-alpine`、`redis:7-alpine` |
| releases 目录 | 全留 | 体积小，回滚要用 |

**清理命令（每次部署 5～10 次后跑一次）：**

```bash
# 1. 看当前线上 sha 和它的上一个（日志「回滚:」那行就是上一个）
sudo -n grep -E '^  线上:|^  回滚:' /var/log/universe-deploy.log | tail -2

# 2. 只留最近 2 个 sha + latest，其余删掉（把下面两个变量换成上一步的值）
KEEP_NOW=421774a; KEEP_PREV=ffdd2f0
sudo -n docker images --format '{{.Repository}}:{{.Tag}}' | grep '^908c31a-' \
  | grep -vE ":($KEEP_NOW|$KEEP_PREV|latest)$" \
  | while read -r ref; do sudo -n docker rmi "$ref" >/dev/null 2>&1; done
sudo -n docker image prune -f

# 3. 构建缓存只保 2GB 最近使用的
sudo -n docker builder prune -f --keep-storage 2GB
```

**清理后必须验证缓存还热**（不清空就等于白清空，且别把 pip 层删掉）：

```bash
df -h /
sudo -n docker compose -f docker-compose.yml -p 908c31a \
  --env-file /etc/universe-wechat-detection.env build web 2>&1 | grep -A1 'RUN pip install'
```

`RUN pip install` 下一行必须是 `CACHED`。若不是 `CACHED`，说明依赖层被清掉了，
下次部署会重跑 `apt-get fonts-noto-cjk`（56.7MB）和 `pip install`，**在 1.6G 内存上很容易 OOM**。

**不要做的事：**

- ❌ `docker builder prune -a -f`（不带 `--keep-storage`）——会把 pip/字体层一起清空
- ❌ `docker system prune -a --volumes` —— 会删掉 postgres/redis 的数据卷
- ❌ 清理时删掉 `latest` 标签 —— 正在跑的容器会失去镜像引用

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