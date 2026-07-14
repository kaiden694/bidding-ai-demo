# 端到端样例验证脚本（T7，Phase 1 MVP）

`e2e_demo.py` 覆盖"上传 → 解析 → 比对 / 审查 → 导出"完整业务闭环，用于 Phase 1 MVP 的端到端联调验证。

## 一、环境准备

脚本依赖后端服务正常运行，请先完成以下准备。

### 1. 基础设施

| 组件 | 用途 | 默认地址 |
| --- | --- | --- |
| PostgreSQL（含 pgvector / pg_trgm / uuid-ossp 扩展） | 文档/切块/比对/合同/向量存储 | `localhost:5432` |
| MinIO | 原始文档与导出报告对象存储 | `localhost:9000` |
| Redis（可选，Phase 2 异步任务用） | Celery broker | `localhost:6379` |
| LLM 服务（OpenAI 兼容，如 vLLM/Ollama） | 参数比对 / 合同风险语义分析 | `LLM_BASE_URL` |
| Embedding 服务（OpenAI 兼容） | 文档切块向量化 | `EMBEDDING_BASE_URL` |

### 2. 后端配置

在 `backend/` 目录下准备 `.env`（参考 `app/core/config.py` 中的默认值）：

```dotenv
APP_ENV=dev
APP_HOST=0.0.0.0
APP_PORT=8000

# 数据库
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=sbaw
POSTGRES_USER=sbaw
POSTGRES_PASSWORD=sbaw_change_me

# MinIO
MINIO_ENDPOINT=localhost:9000
MINIO_ACCESS_KEY=minio
MINIO_SECRET_KEY=minio_change_me
MINIO_BUCKET=sbaw-files
MINIO_SECURE=false

# LLM / Embedding（按实际部署填写）
LLM_BASE_URL=http://localhost:8000/v1
LLM_API_KEY=not-required-for-local
LLM_MODEL=qwen2.5-14b-instruct
EMBEDDING_BASE_URL=http://localhost:8000/v1
EMBEDDING_MODEL=bge-m3
EMBEDDING_DIM=1024

SECRET_KEY=dev-only-change-me
```

### 3. 安装依赖

```bash
cd backend
pip install -r requirements.txt
```

### 4. 启动后端

```bash
cd backend
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

启动后访问以下地址确认服务就绪：

- 健康检查：<http://localhost:8000/health>
- API 文档：<http://localhost:8000/docs>

> 说明：Phase 1 认证为占位实现（`app/api/deps.py` 中无 token 时返回匿名管理员放行），脚本在未提供用户名时自动以匿名方式调用。

## 二、数据准备

准备 3 类样例文件（脚本会按 `doc_type` 上传并解析）：

| 参数 | 文件类型 | 说明 |
| --- | --- | --- |
| `--tender` | 招标文件（PDF / DOCX） | 包含技术参数要求，作为比对基准 |
| `--spec` | 规格书（PDF / DOCX / TXT） | 包含响应参数，与招标文件比对 |
| `--contract` | 合同文件（PDF / DOCX，可选） | 用于合同风险扫描 |

建议样例文件包含：

- **招标文件**：技术参数表（功率、容量、尺寸、接口等数值/文本参数）。
- **规格书**：与招标参数对应的响应值，便于观察"一致 / 偏离 / 缺失"判定。
- **合同**：包含付款、交付、违约责任、争议解决、效期等条款，便于观察风险识别。

> 可使用项目内已有的样例文件，或自行准备任意符合上述特征的文件。

## 三、运行步骤

在 `backend/` 目录下执行（确保已激活虚拟环境）：

```bash
# 仅比对流程（上传→解析→比对→结果→导出）
python scripts/e2e_demo.py \
    --tender path/to/tender.pdf \
    --spec   path/to/spec.docx

# 完整闭环（含合同审查与风险报告导出）
python scripts/e2e_demo.py \
    --tender   path/to/tender.pdf \
    --spec     path/to/spec.docx \
    --contract path/to/contract.docx
```

### 常用参数

| 参数 | 环境变量 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `--base-url` | `E2E_BASE_URL` | `http://localhost:8000` | 后端服务地址 |
| `--username` | `E2E_USERNAME` | （空） | 登录用户名，留空则匿名放行 |
| `--password` | `E2E_PASSWORD` | （空） | 登录密码 |
| `--timeout` | `E2E_TIMEOUT` | `600` | HTTP 超时（秒，LLM 调用可能较慢） |
| `-v` / `--verbose` | — | 关闭 | 打印每条请求的状态码 |

也可全部用环境变量配置后直接运行：

```bash
export E2E_BASE_URL=http://localhost:8000
python scripts/e2e_demo.py --tender tender.pdf --spec spec.docx --contract contract.docx
```

### 已知 API 缺口（合同创建）

当前 `contracts` 端点仅提供 `review` / `risks` / `export`，缺少 `POST /contracts` 创建端点。
为走通合同审查闭环，脚本在 `ensure_contract_record` 中复用后端 DB 会话直接写入 `Contract`
记录（`document_id` 关联已解析的合同文档），并明确标注为兜底逻辑。待后续补齐创建端点后，
可将该步骤替换为标准 HTTP 调用。

## 四、预期输出

脚本按步骤顺序打印状态与耗时，成功时输出形如：

```
>>> [健康检查] 开始 ...
    服务：smart-bidding-ai-workbench env=dev version=0.1.0
<<< [健康检查] 完成（0.05s）

>>> [登录获取 Token] 开始 ...
    未提供用户名，Phase 1 匿名放行
<<< [登录获取 Token] 完成（0.00s）

>>> [上传文档 [tender] tender.pdf] 开始 ...
    doc_id=... 解析状态=pending 大小=...
<<< [上传文档 [tender] tender.pdf] 完成（0.42s）

>>> [解析文档 [招标文件] ...] 开始 ...
    解析完成：页数=5 切块数=12
<<< [解析文档 [招标文件] ...] 完成（8.31s）

...

>>> [导出偏离报告（Docx）] 开始 ...
    file_key=reports/comparison/.../....docx
    download_url=http://localhost:9000/sbaw-files/...
<<< [导出偏离报告（Docx）] 完成（0.18s）

============================================================
端到端验证汇总
============================================================
  ✔ 健康检查        smart-bidding-ai-workbench 0.1.0
  ✔ 登录           匿名放行（Phase 1 占位）
  ✔ 上传[tender]    id=...
  ✔ 上传[spec]      id=...
  ✔ 解析[招标文件]   页数=5 块数=12
  ✔ 解析[规格书]    页数=3 块数=8
  ✔ 创建比对       task_id=...
  ✔ 比对结果       共6条 分布={'match': 4, 'deviation': 2}
  ✔ 导出偏离报告     file_key=reports/comparison/.../....docx
  ✔ 上传[contract]  id=...
  ✔ 解析[合同文件]   页数=4 块数=10
  ✔ 创建合同记录     contract_id=...（兜底）
  ✔ 合同审查       共3条 分布={'high': 1, 'medium': 2}
  ✔ 导出风险报告     file_key=reports/risk/.../....docx
============================================================
共 14 步，全部通过 ✓
```

- 每步会打印关键标识（`doc_id` / `task_id` / `contract_id` / `file_key`）与统计分布。
- 任一步失败时，脚本打印 `[FATAL]` 错误信息并以非零码退出。
- 解析 / 比对在 Phase 1 为同步执行；脚本仍内置轮询兜底以兼容 Phase 2 异步化。

## 五、语法校验

```bash
cd backend
python -m compileall scripts
```
