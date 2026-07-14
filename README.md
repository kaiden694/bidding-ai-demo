# 智能招投标与合同合规 AI 工作台

> Smart Bidding & Contract Compliance AI Workbench
> 基于 大模型 + RAG 的企业级智能工作台。完整深化设计方案见 [`.trae/documents/智能招投标与合同合规AI工作台-深化设计方案.md`](.trae/documents/智能招投标与合同合规AI工作台-深化设计方案.md)

## 技术栈

- **后端**：Python 3.11 + FastAPI + SQLAlchemy 2.0(async) + Pydantic v2
- **数据层**：PostgreSQL 16 + pgvector + Redis 7 + MinIO
- **权限引擎**：Casbin RBAC（rbac_with_domains 模型 + 内存 enforcer + DB 加载）
- **AI 引擎**：OpenAI 兼容接口（vLLM/Ollama/商业 API 均可）+ LlamaIndex + bge-m3
- **异步任务**：Celery + Celery Beat（队列：default / parsing / llm）
- **文档解析**：PyMuPDF + pdfplumber + python-docx + RapidOCR
- **前端**：Vue 3 + Vite + Element Plus + Pinia + Vue Router + TypeScript
- **测试**：pytest + pytest-asyncio（后端）/ Playwright（前端 E2E）
- **部署**：Docker Compose（MVP）→ K8s（企业级）

## 目录结构

```
ai2/
├── smart-bidding-ai-workbench.html   # 设计创意原稿
├── .trae/documents/                  # 深化设计方案文档
├── .trae/specs/                       # Spec 驱动开发文档（spec/tasks/checklist）
├── docker-compose.yml                 # 基础设施 + 后端 + 前端编排
├── docker/postgres/init.sql           # PG 扩展初始化（vector/pg_trgm/uuid-ossp）
├── .env.example                       # 环境变量样例
├── backend/
│   ├── app/
│   │   ├── main.py                    # FastAPI 入口
│   │   ├── core/                      # 配置/DB/安全/Casbin/Celery/MinIO
│   │   ├── api/v1/endpoints/          # REST 端点（92 条路由）
│   │   ├── models/                    # ORM 模型（28 张表）
│   │   ├── schemas/                   # Pydantic 契约
│   │   ├── services/                  # 业务服务
│   │   ├── middleware/                # 中间件（审计日志）
│   │   ├── ai/                        # AI 引擎层
│   │   │   ├── llm/                   # LLM 编排（OpenAI 兼容 + Round-Robin）
│   │   │   ├── embedding/             # 向量化（bge-m3）
│   │   │   ├── parsing/               # 文档解析（多解析器 fallback）
│   │   │   └── rag/                   # RAG 检索（混合检索 + 重排序）
│   │   ├── tasks/                     # Celery 异步任务 + 定时任务
│   │   └── db/                        # 模型聚合 + 种子数据
│   ├── alembic/                       # 数据库迁移
│   ├── tests/                         # pytest 测试套件
│   ├── requirements.txt
│   └── Dockerfile
└── frontend/
    └── admin/                         # Vue3 管理后台
        ├── src/
        │   ├── api/                   # API 封装（axios）
        │   ├── views/                 # 业务页面
        │   ├── layouts/                # 布局组件
        │   ├── router/                 # 路由 + 守卫
        │   ├── stores/                # Pinia store
        │   └── utils/                 # axios 拦截器等
        ├── tests-e2e/                 # Playwright E2E 测试
        ├── Dockerfile                 # 多阶段构建（node → nginx）
        └── package.json
```

## 快速启动

### 1. 准备环境变量
```bash
cp .env.example .env
# 按实际环境修改 .env 中的密码与 LLM 地址
```

### 2. 一键启动（Docker Compose：基础设施 + 后端 + Celery + 前端）
```bash
docker compose up -d
```
启动后服务：
- 前端管理后台: http://localhost:5173 （admin / admin123）
- 后端 API: http://localhost:8000
- API 文档: http://localhost:8000/docs
- MinIO 控制台: http://localhost:9001 (minio / minio_change_me)
- PostgreSQL: localhost:5432
- Redis: localhost:6379

容器编排包含 7 个服务：
| 服务 | 说明 |
|---|---|
| postgres | PostgreSQL 16 + pgvector/pg_trgm/uuid-ossp |
| redis | Redis 7（Celery broker + result backend） |
| minio | MinIO 对象存储 |
| backend | FastAPI 后端 API（uvicorn --reload） |
| celery_worker | Celery Worker（队列 default/parsing/llm） |
| celery_beat | Celery Beat 定时任务（资质预警每日 09:00） |
| frontend | Vue3 管理后台（nginx 托管 + /api 反代） |

### 3. 本地开发（不使用 Docker，仅启动基础设施）
```bash
# 仅启动基础设施
docker compose up -d postgres redis minio

# 后端本地运行
cd backend
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Linux/Mac
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 前端本地运行（另开终端）
cd frontend/admin
npm install
npm run dev
# 访问 http://localhost:5173（dev server 代理 /api → http://localhost:8000）
```

### 4. 启动 Celery（异步解析/向量化/定时预警）
```bash
# Worker
cd backend
celery -A app.core.celery_app worker -l info -Q default,parsing,llm

# Beat（定时任务：资质预警每日 09:00 扫描）
celery -A app.core.celery_app beat -l info
```

## LLM 配置（OpenAI 兼容）

系统通过 `LLM_BASE_URL` 接入任意 OpenAI 兼容服务：

**本地部署（推荐，数据不出内网）：**
```env
# vLLM 部署 Qwen
LLM_BASE_URL=http://vllm:8000/v1
LLM_API_KEY=not-required-for-local
LLM_MODEL=qwen2.5-14b-instruct
EMBEDDING_MODEL=bge-m3
```

**商业 API：**
```env
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=sk-xxx
LLM_MODEL=gpt-4o-mini
```

## 数据库迁移

```bash
cd backend
# 生成迁移
alembic revision --autogenerate -m "init schema"
# 执行迁移
alembic upgrade head
# 回滚
alembic downgrade -1
```

> 开发环境（APP_ENV=dev）启动时自动建表 + 种子数据（6 角色 + 41 权限点 + 角色-权限分配），无需手动迁移。

## 测试

### 后端测试（pytest）
```bash
cd backend

# 运行全部测试
python -m pytest tests/ -v

# 仅权限隔离测试（100+ 用例）
python -m pytest tests/test_rbac_isolation.py -v

# 仅审计日志测试
python -m pytest tests/test_audit_log.py -v

# LLM 相关测试（需 LLM 服务可用，否则自动 skip）
SBAW_RUN_LLM_TESTS=1 python -m pytest tests/test_qualification_extract.py tests/test_feedback_loop.py -v
```

### 前端 E2E 测试（Playwright）
```bash
cd frontend/admin

# 首次安装浏览器
npx playwright install --with-deps

# 运行 E2E（需后端 + 前端 dev server 运行）
npm run e2e

# 有头模式
npm run e2e:headed

# 交互式 UI 模式
npm run e2e:ui
```

## 默认账号

| 用户名 | 密码 | 角色 | 说明 |
|---|---|---|---|
| admin | admin123 | admin | 系统管理员（拥有所有权限） |

其他角色（presales/legal/procurement/pm/compliance）需在管理后台创建用户并分配角色。

## 核心 API

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/v1/auth/login` | 登录（返回 JWT + 权限点） |
| GET | `/api/v1/auth/me` | 当前用户信息 + 权限点 |
| POST | `/api/v1/documents/upload` | 上传文档到 MinIO |
| POST | `/api/v1/documents/{id}/parse` | 解析文档并切块入库 |
| POST | `/api/v1/projects` | 创建招投标项目 |
| POST | `/api/v1/comparison` | 创建参数偏离比对任务（支持规格书 / 产品选型） |
| POST | `/api/v1/contracts/{id}/review` | 合同风险扫描 |
| POST | `/api/v1/knowledge/search` | 历史知识库语义检索 |
| POST | `/api/v1/knowledge/bases/{id}/import` | 知识库批量导入（ZIP） |
| POST | `/api/v1/knowledge/bases/{id}/reindex` | 索引重建 |
| GET | `/api/v1/qualifications/expiring` | 资质即将过期列表 |
| POST | `/api/v1/qualifications/{id}/extract` | 资质 OCR+LLM 字段提取 |
| POST | `/api/v1/feedback` | 提交专家修正（语义反馈闭环） |
| GET | `/api/v1/feedback/stats` | 反馈统计 |
| GET | `/api/v1/audit-logs` | 审计日志查询（多维筛选） |
| GET | `/api/v1/audit-logs/export` | 审计日志导出 CSV |

## 系统模块

**业务模块（前台服务界面）**
1. 招投标项目管理（10 状态机）
2. 智能参数偏离比对（支持规格书 + 产品选型两种方式）
3. 合同风险扫描（规则 + LLM 双引擎）
4. 企业资质台账（有效期预警 + OCR+LLM 字段提取）
5. 历史知识库（RAG + 反馈闭环）
6. 产品中心：分类管理 + 技术参数表 + 向量库 + 关联资质/检测报告 + 比对选型
7. 通用知识库：企业资料/政策法规/行业标准向量化检索（visibility 前后台分层）
8. AI 助手：前台/后台共用咨询问答（RAG 增强 + 会话历史 + 证据引用）
9. 语义反馈闭环：专家修正向量化入库 → 相似场景召回 → LLM few-shot 提升准确率

**后台管理模块（Vue3）**
- 用户/角色/组织/权限管理、审计日志查询导出、知识库管理、资质台账管理、产品中心管理、通用知识库管理

## 阶段路线（与深化设计方案对齐）

- **Phase 1 MVP**：文档导入 + 解析 + 参数偏离比对 + 合同风险扫描 + 报告导出
- **Phase 2**：知识库 + 多角色权限 + 资质台账 + 语义反馈闭环 + 前端管理后台
- **Phase 3**：项目状态机 + 多 LLM 负载均衡 + SSO
- **Phase 4**：K8s 部署 + 监控 + 安全加固 + 现有系统集成

## 团队分工建议

详见设计方案 §9：架构师 / 后端(4-5) / AI算法(2) / 前端(2) / 测试(1) / DevOps(1) / PM(1)
