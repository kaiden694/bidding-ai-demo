# Locust 压测脚本

Phase 4 T4 压测与性能调优模块。基于 Locust 模拟多用户并发，验证系统在
递增负载下的 QPS / P95 延迟 / 错误率，识别性能瓶颈。

## 前置准备

### 1. 启动依赖服务

```bash
# PostgreSQL
docker run -d -p 5432:5432 \
    -e POSTGRES_USER=sbaw \
    -e POSTGRES_PASSWORD=sbaw_change_me \
    -e POSTGRES_DB=sbaw \
    postgres:16

# Redis（缓存 + 限流后端）
docker run -d -p 6379:6379 redis:7
```

### 2. 启动后端服务

```bash
cd backend
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### 3. 初始化测试账号

确保 `admin / admin123` 账号存在并已分配所有权限点。
若使用其他账号，修改 `locustfile.py` 中 `on_start` 的登录凭据。

### 4. 安装 Locust

```bash
pip install locust
```

## 运行方式

### 交互模式（推荐调参时使用）

```bash
cd backend
locust -f tests/load/locustfile.py --host=http://localhost:8000
```

打开浏览器访问 <http://localhost:8089>，在 Web UI 中：
- Number of users：用户总数（建议 10 → 50 → 100 递增）
- Spawn rate：每秒新增用户数（建议 10）
- Host：自动填充为 `--host` 参数

### Headless 模式（CI / 自动化压测推荐）

```bash
# 100 用户、10 用户/秒递增、持续 5 分钟、生成 HTML 报告
locust -f tests/load/locustfile.py --host=http://localhost:8000 \
    --headless -u 100 -r 10 -t 5m --html=report.html
```

常用参数：

| 参数 | 含义 |
| --- | --- |
| `-u, --users` | 总并发用户数 |
| `-r, --spawn-rate` | 每秒新增用户数 |
| `-t, --run-time` | 持续时间（如 `5m` `1h`） |
| `--html=report.html` | 输出 HTML 报告 |
| `--csv=result` | 输出 CSV 统计文件 |
| `--only-summary` | 仅输出最终汇总 |
| `--stop-timeout 30` | 停止时等待未完成请求的超时（秒） |

### 阶梯递增压测

按计划递增并发量，定位性能拐点：

```bash
# 阶段一：10 用户
locust -f tests/load/locustfile.py --host=http://localhost:8000 \
    --headless -u 10 -r 5 -t 2m --html=report_10.html

# 阶段二：50 用户
locust -f tests/load/locustfile.py --host=http://localhost:8000 \
    --headless -u 50 -r 10 -t 3m --html=report_50.html

# 阶段三：100 用户
locust -f tests/load/locustfile.py --host=http://localhost:8000 \
    --headless -u 100 -r 10 -t 5m --html=report_100.html
```

## 压测场景

| 任务 | 权重 | 端点 | 说明 |
| --- | --- | --- | --- |
| list_projects | 3 | GET `/api/v1/projects` | 高频读 |
| list_contracts | 2 | GET `/api/v1/contracts` | 高频读 |
| list_knowledge_bases | 2 | GET `/api/v1/knowledge/bases` | 高频读 |
| view_dashboard | 1 | GET `/api/v1/users/me` | 鉴权 + 权限点返回 |
| list_qualifications | 1 | GET `/api/v1/qualifications` | 资质台账 |
| list_audit_logs | 1 | GET `/api/v1/audit-logs` | 审计查询 |
| create_project | 1 | POST `/api/v1/projects` | 写操作 |

每个用户在 on_start 阶段登录一次获取 `access_token`，后续请求携带
`Authorization: Bearer {token}`，请求间隔 1-3 秒（模拟真实操作节奏）。

## 指标解读

### 关键指标

| 指标 | 含义 | 阈值参考 |
| --- | --- | --- |
| **RPS（Requests/s）** | 每秒成功请求数 | 越高越好，反映吞吐量 |
| **P95 延迟** | 95 分位响应时间 | 列表 < 500ms，写操作 < 1s |
| **P99 延迟** | 99 分位响应时间 | 反映长尾，< 2s 为佳 |
| **错误率** | 非 2xx 响应占比 | < 1% 为合格，0% 为优秀 |
| **失败率** | 异常 / 超时占比 | 必须为 0% |

### 性能基线（参考）

| 并发用户 | RPS 目标 | P95 目标 | 错误率 |
| --- | --- | --- | --- |
| 10 | ≥ 8 | < 300ms | 0% |
| 50 | ≥ 30 | < 800ms | 0% |
| 100 | ≥ 50 | < 1500ms | < 1% |

### 性能瓶颈定位

1. **RPS 不随用户数增长**：受后端处理能力限制（DB 连接池 / GIL / 锁）
2. **P95 突增**：触发慢查询或缓存击穿
3. **错误率上升**：检查限流中间件（默认 100 req/min per IP）、DB 连接池耗尽
4. **`/api/v1/users/me` 慢**：检查 Casbin 策略加载、Redis 缓存命中
5. **`/api/v1/audit-logs` 慢**：审计表索引（created_at / user_id）

## 排查常见问题

### Q1：所有请求返回 401

- `admin / admin123` 账号未创建，运行种子脚本：`python scripts/init_data.py`
- 后端未启动或 `--host` 指向错误地址

### Q2：错误率 > 0%，看到大量 429

- 触发限流中间件（`/api/v1/projects` 限 5 req/min per IP）
- 压测环境临时调高 `RateLimitMiddleware.RATE_RULES` 阈值，或注释中间件

### Q3：P95 延迟异常高

- 检查 PostgreSQL 慢查询日志
- 检查 Redis 是否在线（缓存未命中导致 DB 压力激增）
- 启用 N+1 查询检测测试：`pytest tests/test_n_plus_1.py -v`

### Q4：locust 启动报 `ModuleNotFoundError: No module named 'locust'`

```bash
pip install locust
```

## 输出文件说明

- `report.html`：包含 RPS / 延迟分布 / 失败请求汇总的可视化报告
- `result_stats.csv` / `result_stats_history.csv`：CSV 格式统计，便于绘图
- `result_failures.csv`：失败请求明细
