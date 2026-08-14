# FLUX Studio

基于 **FLUX.2-dev** 的图像生成平台,支持纯文生图与多图融合(图生图)。提供上传图片、设置提示词/步数/引导强度/输出尺寸、提交任务、实时查看进度、取消与删除任务等完整 workflow。

项目采用前后端分离 + 异步任务队列的架构,GPU 推理与 Web 服务解耦——模型常驻在单独的 GPU 服务器上,Web 平台本身不需要 GPU。

## 架构

```
┌────────────┐   /api/*   ┌──────────┐  enqueue   ┌───────┐  pop task   ┌────────┐  HTTP multipart  ┌───────────┐
│  Frontend  │ ─────────> │ Backend  │ ─────────> │ Redis │ ─────────> │ Worker │ ───────────────> │ Model API │
│ (React+Vite)│            │ (FastAPI)│            │       │            │        │                  │  (GPU)    │
└────────────┘ <────────── └──────────┘ <────────── └───────┘ <────────── └────────┘ <─────────────── └───────────┘
                 poll tasks     ↑ 写状态 pub/sub      ↑ 写结果               ↑ 推理/进度/取消
                                 │                     │                       │ Flux2Pipeline (常驻显存)
                          ┌──────┴──────┐       ┌───────┴────┐
                          │ PostgreSQL  │       │  持久化文件 │
                          └─────────────┘       └────────────┘
```

| 组件 | 目录 | 说明 |
| --- | --- | --- |
| **Frontend** | `frontend/` | React 19 + Vite + TypeScript + HeroUI + Tailwind。负责上传、参数、任务列表,轮询进度。 |
| **Backend** | `backend/` | FastAPI。接收上传/生成请求,落库,入队,后台监听 worker 状态 pub/sub、轮询 model-api 进度并写回 DB。 |
| **Worker** | `worker/` | 纯 HTTP 客户端,**不需要 GPU**。从 Redis 弹任务,把图片 multipart 上传给 model-api,保存返回的 PNG,发状态事件。 |
| **Model API** | `model-api/` | 部署在 **GPU 服务器**上,**不在此 compose 内**。加载 FLUX.2-dev 4-bit 模型常驻显存,提供推理(`mix-generation-pro`)、进度查询(`progress`)、取消(`cancel`)接口。 |
| **Redis** | — | 任务队列 `flux:tasks` + 状态频道 `flux:status`。 |
| **PostgreSQL** | — | 任务与图片元数据持久化。 |

### 数据流

1. 前端上传图片 → backend `POST /api/upload` → 落盘 + DB
2. 前端提交生成 → backend `POST /api/generate` → DB 建任务(置 `queued`)→ Redis 入队
3. Worker 弹任务 → 置 `running` → 把图片上传给 model-api → 调 `mix-generation-pro`
4. model-api 用 `Flux2Pipeline` 推理,步进回调写进度,返回 PNG
5. Worker 保存 PNG → 发 `completed` 事件 → backend 写回 DB 与 output 文件名
6. 前端轮询 `/api/tasks` 展示进度与结果;可 `cancel` / `delete`

### 取消机制

针对任务所处的不同阶段,采用组合策略保证取消可见且不产生孤儿状态:
- **队列中未弹出**:Redis 预置 cancel flag,worker `pop` 后预检即直接置 `cancelled`。
- **已在 model-api 推理**:backend 经 HTTP 调 `model-api/v1/cancel/{task_id}`,model-api 的步进回调检测到 cancel event 即在下个 step 抛异常中止推理。
- **已终态**(completed/failed/cancelled):幂等返回当前状态,不再重复发事件。

## 环境要求

- Docker + Docker Compose
- 一台 **GPU 服务器**,已部署 `model-api/app.py`(需 CUDA、`diffusers`、FLUX.2-dev 4-bit 模型)

> Web 平台本身的四组件(frontend/backend/worker/redis/db)无需 GPU,部署在普通服务器即可。

## 快速开始

### 1) 准备配置

```bash
cp .env.example .env
# 编辑 .env,重点修改:
#   MODEL_API_URL   —— 指向你单独部署的 GPU 模型服务,如 http://192.168.1.50:8000
#   DB_PASSWORD     —— 生产环境请改强密码
#   FRONTEND_PORT / BACKEND_PORT / DATA_DIR —— 按服务器实际调整
```

### 2) 部署 GPU 模型服务(独立,不在 compose 内)

在 GPU 服务器上运行 `model-api/app.py`。它会加载 FLUX.2-dev 4-bit 模型并监听 `0.0.0.0:8000`:

```bash
cd model-api
pip install -r requirements.txt
# 需预先准备:diffusers 的 Flux2Pipeline + FLUX.2-dev 4-bit 模型权重
python app.py
# 服务 Ready 后,确保 MODEL_API_URL 指向该机器的可达地址
```

### 3) 启动 Web 平台

在仓库根目录:

```bash
./scripts/deploy.sh
# 或手动:
docker compose up -d --build
```

启动后:
- 前端:`http://<服务器IP>:<FRONTEND_PORT>`(默认 8080)
- API 文档:`http://<服务器IP>:<BACKEND_PORT>/docs`(默认仅绑 `127.0.0.1:8081`,从外网访问需 SSH 隧道或反向代理)

## 本地开发

**前端**

```bash
cd frontend
pnpm install      # 或 npm install
pnpm dev          # 默认 5173,自动代理 /api 到本机 8081
```

**后端 / worker**:需本地可达 PostgreSQL 与 Redis(可用 compose 仅起这两个服务:`docker compose up -d redis db`)。

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8081   # 需设置 DATABASE_URL / REDIS_URL / MODEL_API_URL 等环境变量

cd ../worker
python main.py     # 同样需 REDIS_URL / MODEL_API_URL / OUTPUT_DIR / UPLOAD_DIR
```

## API 速览

| 方法 | 路径 | 功能 |
| --- | --- | --- |
| POST | `/api/upload` | 上传图片(最多 8 张,单张 ≤ 20MB) |
| POST | `/api/generate` | 提交生成任务(提示词、步数、引导强度、尺寸、图片列表) |
| GET | `/api/tasks` | 列出最近 50 条任务 |
| GET | `/api/tasks/{id}` | 查询单个任务状态/进度 |
| POST | `/api/tasks/{id}/cancel` | 取消任务(幂等) |
| DELETE | `/api/tasks/{id}` | 删除任务(含磁盘文件) |
| GET | `/api/images/{id}` | 按 id 下载图片 |
| GET | `/api/images/by-name/{filename}` | 按文件名下载 |

Model API(由 GPU 服务器提供):`POST /v1/mix-generation-pro`、`GET /v1/progress/{task_id}`、`POST /v1/cancel/{task_id}`。

## 主要环境变量

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `MODEL_API_URL` | (必填) | GPU 模型服务地址,worker 与 backend 都依赖它 |
| `DB_USER` / `DB_PASSWORD` / `DB_NAME` | `flux` / `flux` / `flux` | PostgreSQL 账号 |
| `FRONTEND_PORT` | `8080` | 前端对外端口 |
| `BACKEND_PORT` | `127.0.0.1:8081` | 后端对外端口(默认仅绑回环) |
| `DATA_DIR` | `./data` | uploads/outputs/pg 数据库的宿主路径 |
| `PROGRESS_POLL_INTERVAL` | `1.0` | backend 轮询 model-api 进度的间隔(秒) |
| `MAX_INPUT_IMAGES` | `8` | 单任务最多输入图片数 |
| `MAX_UPLOAD_BYTES` | `20971520` | 单文件上传上限 |

完整项见 `.env.example`。

## 目录结构

```
.
├── frontend/        # React + Vite 前端
├── backend/         # FastAPI 后端(app/api, app/services, app/models, app/queue)
├── worker/          # 任务执行 HTTP 客户端(无 GPU)
├── model-api/       # GPU 推理服务(Flux2Pipeline,独立部署)
├── redis/           # Redis 数据卷挂载点
├── data/            # uploads / outputs / pg 数据(gitignored)
├── scripts/deploy.sh
├── docker-compose.yml
└── .env.example
```

## 说明

- `model-api` 不在 `docker-compose.yml` 中——GPU 与依赖环境各异,需在 GPU 服务器上按实际情况单独部署,compose 中的 backend/worker 通过 `MODEL_API_URL` 调用它。
- Docker 镜像构建时使用 TUNA(清华)PyPI/Debian 镜像源以加速国内构建,如需更换可在各 Dockerfile 中调整。
- `.env` 不会进入 git(已 gitignore);`.env.example` 是配置模板。
- `data/`、`redis/`、`node_modules`、构建产物等均已 gitignore。
