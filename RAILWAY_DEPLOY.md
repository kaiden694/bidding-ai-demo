# Railway 部署指南

## 架构在 Railway 上的拓扑

```
┌─────────────────────────────────────────────────────────────┐
│                    Railway Project                          │
│                                                             │
│  ┌─────────────┐    ┌─────────────┐    ┌──────────────┐    │
│  │ PostgreSQL  │    │   Redis     │    │   (MinIO    │    │
│  │  + pgvector │    │             │    │    跳过)    │    │
│  └──────┬──────┘    └──────┬──────┘    └──────────────┘    │
│         │                  │                               │
│         │    ┌─────────────┼─────────────┐                 │
│         │    │             │             │                 │
│  ┌──────▼────▼───┐   ┌─────▼─────┐   ┌──▼──────────┐      │
│  │   backend     │   │  worker   │   │  frontend   │      │
│  │ (FastAPI)     │   │ (Celery)  │   │ (Vue3+nginx)│      │
│  │               │   │           │   │             │      │
│  │ PORT=?        │   │           │   │ PORT=80     │      │
│  └───────┬───────┘   └───────────┘   └──────┬──────┘      │
│          │                                   │             │
│          └───────────────────────────────────┘             │
│           (frontend 反代 /api → backend)                   │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

## 前置准备

1. **GitHub 仓库**：[kaiden694/bidding-ai-demo](https://github.com/kaiden694/bidding-ai-demo)（已创建）
2. **Railway 账号**：使用 GitHub 账号登录 [railway.app](https://railway.app)
3. **Railway 免费额度**：$5/月 + 500 小时执行时间（足够 Demo 展示）

## 部署步骤

### Step 1: 创建 Railway 项目

1. 登录 [railway.app](https://railway.app) → **New Project**
2. 选择 **Deploy from GitHub repo** → 授权 → 选择 `kaiden694/bidding-ai-demo`
3. 项目创建后会自动添加一个 service（先删除，后面手动添加三个）

### Step 2: 添加 PostgreSQL + Redis

1. 在项目面板点 **+ New** → **Database** → **PostgreSQL**
   - Railway 会自动创建并注入 `DATABASE_URL` / `PG*` 等变量
2. 再点 **+ New** → **Database** → **Redis**
   - 自动注入 `REDIS_URL`

### Step 3: 启用 PostgreSQL pgvector 扩展

在 PostgreSQL service 的 **Query** 面板执行：

```sql
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS pg_trgm;
```

### Step 4: 添加 Backend Service

1. **+ New** → **GitHub Repo** → 选择 `bidding-ai-demo`
2. 配置 service：
   - **Name**: `backend`
   - **Root Directory**: `backend`
   - **Build**: Railway 自动用 Nixpacks 识别 Python
3. **Variables** 标签 → **Raw Editor** 粘贴：

```env
APP_ENV=prod
APP_LOG_LEVEL=INFO
SECRET_KEY=<替换为一个随机长字符串>
JWT_ALGORITHM=HS256
JWT_ACCESS_EXPIRE_MINUTES=120
JWT_REFRESH_EXPIRE_DAYS=7
ENCRYPTION_KEY=

# PostgreSQL（Railway 自动注入 DATABASE_URL，但应用读取以下变量）
POSTGRES_HOST=${{Postgres.PGHOST}}
POSTGRES_PORT=${{Postgres.PGPORT}}
POSTGRES_DB=${{Postgres.PGDATABASE}}
POSTGRES_USER=${{Postgres.PGUSER}}
POSTGRES_PASSWORD=${{Postgres.PGPASSWORD}}
POSTGRES_POOL_SIZE=5
POSTGRES_MAX_OVERFLOW=10

# Redis（Railway 自动注入 REDIS_URL）
REDIS_HOST=${{Redis.REDISHOST}}
REDIS_PORT=${{Redis.REDISPORT}}
REDIS_PASSWORD=${{Redis.REDISPASSWORD}}

# MinIO 跳过（降级运行，不影响核心功能）
MINIO_ENDPOINT=localhost:9000
MINIO_ACCESS_KEY=minio
MINIO_SECRET_KEY=minio_change_me
MINIO_BUCKET=sbaw-files
MINIO_SECURE=false

# LLM（OpenAI 兼容接口，必填）
LLM_BASE_URL=https://api.siliconflow.cn/v1
LLM_API_KEY=<你的 LLM API Key>
LLM_MODEL=qwen2.5-14b-instruct
LLM_TIMEOUT=120
LLM_MAX_RETRIES=3

# Embedding（必填，否则向量检索不工作）
EMBEDDING_BASE_URL=https://api.siliconflow.cn/v1
EMBEDDING_API_KEY=<你的 Embedding API Key>
EMBEDDING_MODEL=bge-m3
EMBEDDING_DIM=1024

# Celery
CELERY_BROKER_URL=redis://${{Redis.REDISHOST}}:${{Redis.REDISPORT}}/1
CELERY_RESULT_BACKEND=redis://${{Redis.REDISHOST}}:${{Redis.REDISPORT}}/2

# CORS（部署后会拿到 frontend 域名，回头补充）
CORS_ORIGINS=http://localhost:5173

# RAG
RAG_CHUNK_SIZE=512
RAG_CHUNK_OVERLAP=64
RAG_RETRIEVE_TOP_K=20
RERANKER_MODEL=bge-reranker-v2-m3
RERANKER_TOP_K=5
```

4. **Settings** → **Start Command**: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
5. **Settings** → **Health Check Path**: `/health`
6. 点 **Deploy**，等待构建完成（首次约 5-8 分钟）

### Step 5: 添加 Worker Service（Celery）

1. **+ New** → **GitHub Repo** → 选择 `bidding-ai-demo`
2. 配置：
   - **Name**: `worker`
   - **Root Directory**: `backend`
3. **Variables** → **Clone from** `backend` service（完全相同的环境变量）
4. **Settings** → **Start Command**:
   ```
   celery -A app.core.celery_app worker -l info -Q default,parsing,llm --concurrency=2
   ```
5. 点 **Deploy**

### Step 6: 添加 Frontend Service

1. **+ New** → **GitHub Repo** → 选择 `bidding-ai-demo`
2. 配置：
   - **Name**: `frontend`
   - **Root Directory**: `frontend/admin`
   - Railway 会自动识别 Dockerfile 构建
3. **Variables** 添加：
   ```env
   # 让 nginx 反代到 backend service 的公网域名
   BACKEND_HOST=${{backend.RAILWAY_PUBLIC_DOMAIN}}:80
   ```
   > 注意：Railway 的 `${{backend.RAILWAY_PUBLIC_DOMAIN}}` 会替换为 backend service 的公网域名
4. **Settings** → **Health Check Path**: `/`
5. 点 **Deploy**

### Step 7: 配置公网访问域名

1. 每个 service 默认有一个 `*.up.railway.app` 的域名
2. 在每个 service 的 **Settings** → **Networking** → **Generate Domain**
3. 拿到 3 个域名：
   - backend: `https://bidding-ai-backend.up.railway.app`
   - frontend: `https://bidding-ai-demo.up.railway.app`
   - worker: 无需域名

### Step 8: 更新 CORS_ORIGINS

拿到 frontend 域名后，回到 **backend** 的 Variables：
```
CORS_ORIGINS=https://bidding-ai-demo.up.railway.app
```

保存后 backend 会自动重新部署。

## 验证

1. 访问 `https://<frontend-domain>.up.railway.app` → 应看到登录页
2. 默认账号：`admin` / `admin123`
3. 访问 `https://<backend-domain>.up.railway.app/docs` → API 文档
4. 登录后 → 进入 **AI 服务配置** → 测试 LLM 健康检查
5. 上传一份招标文件 → 触发参数比对 → 验证 RAG + LLM 工作正常

## 常见问题

### Q: 构建失败 "No module named 'rapidocr_onnxruntime'"
A: 这是 OCR 依赖在 Linux 构建时的兼容问题。Worker 已配置 OCR 为可选降级，不影响核心 LLM/RAG 功能。

### Q: backend 启动报 "connection refused postgres"
A: 检查 PostgreSQL service 是否已启动。Railway 的 `${{Postgres.PGHOST}}` 引用需要 PostgreSQL service 先存在。

### Q: 健康检查一直失败
A: 首次启动需要执行 init_db 创建 42 张表，可能需要 60 秒。在 Settings → Health Check → Timeout 调到 120s。

### Q: Celery worker 不工作
A: Worker 不需要公网域名，但要确保 Variables 与 backend 完全一致（特别是 REDIS_HOST 和 POSTGRES_HOST）。

### Q: 免费额度用完
A: $5 免费额度约够 backend + worker + frontend 各运行 500 小时（约 20 天）。参赛期间够用。如需长期展示，可升级到 Hobby Plan（$20/月）。
