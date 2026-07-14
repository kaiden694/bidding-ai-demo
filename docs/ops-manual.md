# 运维手册

> 智能招投标与合同合规 AI 工作台

## 1. 部署架构

### 1.1 服务清单

| 服务 | 端口 | 说明 |
|------|------|------|
| backend (FastAPI) | 8000 | 后端 API + Swagger UI |
| frontend (Nginx) | 80 | 前端静态资源 |
| postgres (pgvector) | 5432 | 数据库 |
| redis | 6379 | 缓存 + Celery broker |
| minio | 9000/9001 | 对象存储 |
| celery-worker | - | 异步任务执行 |
| celery-beat | - | 定时任务调度 |
| prometheus | 9090 | 指标采集 |
| grafana | 3001 | 监控大盘 |
| alertmanager | 9093 | 告警管理 |
| loki | 3100 | 日志聚合 |

### 1.2 部署方式

#### Docker Compose（开发/测试）
```bash
cd deploy/docker
docker-compose up -d
```

#### K8s（生产）
```bash
# 创建命名空间
kubectl apply -f deploy/k8s/namespace.yaml

# Helm 部署
helm install sbaw ./deploy/k8s/helm/sbaw -n sbaw \
  -f deploy/k8s/helm/sbaw/values-prod.yaml \
  --set secrets.secretKey=<your-secret> \
  --set postgres.password=<your-pg-password>
```

## 2. 配置管理

### 2.1 环境变量
配置通过 `.env` 文件或环境变量注入，参见 `backend/.env.example`。

关键配置项：
- `SECRET_KEY`：JWT 签名密钥（生产必须修改）
- `ENCRYPTION_KEY`：字段级加密密钥（生成：`python -c "from app.core.encryption import generate_encryption_key; print(generate_encryption_key())"`）
- `POSTGRES_PASSWORD`：数据库密码
- `LLM_API_KEY`：LLM 服务密钥
- `MINIO_SECRET_KEY`：MinIO 密钥

### 2.2 K8s ConfigMap + Secret
- 非敏感配置：ConfigMap
- 敏感配置：Secret（base64 编码）
- 生产推荐：sealed-secrets 或 external-secrets

## 3. 日常运维

### 3.1 服务管理
```bash
# Docker Compose
docker-compose ps              # 查看服务状态
docker-compose logs -f backend # 查看后端日志
docker-compose restart backend  # 重启后端
docker-compose down             # 停止全部

# K8s
kubectl get pods -n sbaw                    # 查看 Pod
kubectl logs -f deployment/sbaw-backend -n sbaw  # 查看日志
kubectl rollout restart deployment/sbaw-backend -n sbaw  # 滚动重启
kubectl scale deployment/sbaw-backend --replicas=3 -n sbaw  # 扩缩容
```

### 3.2 日志查看
```bash
# 结构化 JSON 日志（stdout）
docker-compose logs backend | jq .

# Loki 查询（LogQL）
# 查看错误日志
{app="sbaw-backend"} |= "ERROR"
# 按 request_id 查询
{app="sbaw-backend"} | json | request_id="xxx-xxx"
```

### 3.3 数据库操作
```bash
# 连接数据库
docker-compose exec postgres psql -U sbaw -d sbaw

# 查看连接数
SELECT count(*) FROM pg_stat_activity;

# 慢查询
SELECT query, mean_exec_time, calls
FROM pg_stat_statements
ORDER BY mean_exec_time DESC LIMIT 10;

# 表大小
SELECT relname, pg_size_pretty(pg_total_relation_size(relid))
FROM pg_catalog.pg_statio_user_tables
ORDER BY pg_total_relation_size(relid) DESC LIMIT 20;
```

### 3.4 缓存管理
```bash
# 连接 Redis
docker-compose exec redis redis-cli

# 查看缓存
KEYS cache:*
KEYS ratelimit:*
KEYS user_permissions:*

# 清除权限缓存（权限变更后）
FLUSHDB  # 谨慎！清除所有缓存
# 或按模式删除
EVAL "return redis.call('del', unpack(redis.call('keys', ARGV[1])))" 0 "user_permissions:*"
```

### 3.5 LLM 提供商管理
```bash
# 查看提供商列表
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/admin/llm-providers

# 健康检查
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/admin/llm-providers/health

# 用量统计
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/admin/llm-usage/stats
```

## 4. 监控告警

### 4.1 Grafana 大盘
- 后端概览：http://localhost:3001/d/backend-overview
- LLM 用量：http://localhost:3001/d/llm-usage
- 业务指标：http://localhost:3001/d/business

### 4.2 关键告警
| 告警 | 阈值 | 级别 | 处理 |
|------|------|------|------|
| 5xx 错误率 | > 1% 持续 5min | Critical | 检查后端日志 + 重启 |
| P95 延迟 | > 3s 持续 10min | Warning | 检查 DB 慢查询 + 扩容 |
| DB 连接池 | > 80% | Warning | 扩大连接池或扩容 |
| LLM 熔断 | 触发 | Critical | 检查 LLM 服务 + 切换提供商 |
| 磁盘 | > 85% | Warning | 清理日志 + 扩容 |

### 4.3 Prometheus 指标
```bash
# 查看指标
curl http://localhost:8000/metrics

# 关键指标
http_requests_total           # HTTP 请求总数
http_request_duration_seconds  # HTTP 延迟
db_pool_size                   # DB 连接池
llm_requests_total             # LLM 请求
llm_circuit_breaker_active     # LLM 熔断状态
```

## 5. 故障排查

### 5.1 后端启动失败
```bash
# 查看启动日志
docker-compose logs backend | tail -50

# 常见原因
# 1. 数据库连接失败 → 检查 POSTGRES_HOST/PORT/PASSWORD
# 2. Redis 连接失败 → 检查 REDIS_HOST/PORT
# 3. MinIO 连接失败 → 检查 MINIO_ENDPOINT
# 4. 端口占用 → 检查 APP_PORT
```

### 5.2 LLM 调用失败
```bash
# 检查 LLM 提供商健康状态
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/v1/admin/llm-providers/health

# 常见原因
# 1. LLM 服务不可达 → 检查 LLM_BASE_URL
# 2. API Key 无效 → 更新 LLM_API_KEY
# 3. 熔断器触发 → 等待 30s 自动恢复
# 4. 所有提供商不可用 → 检查网络 + LLM 服务状态
```

### 5.3 数据库性能问题
```bash
# 查看慢查询
docker-compose exec postgres psql -U sbaw -d sbaw -c "
  SELECT query, mean_exec_time, calls
  FROM pg_stat_statements
  ORDER BY mean_exec_time DESC LIMIT 10;"

# 查看连接数
docker-compose exec postgres psql -U sbaw -d sbaw -c "
  SELECT count(*), state FROM pg_stat_activity GROUP BY state;"

# 查看锁等待
docker-compose exec postgres psql -U sbaw -d sbaw -c "
  SELECT * FROM pg_locks WHERE NOT granted;"
```

### 5.4 内存泄漏
```bash
# 查看 Pod 内存使用
kubectl top pods -n sbaw

# 如内存持续增长
# 1. 重启 Pod（短期）
# 2. 增加 memory limit
# 3. 用 py-spy 分析内存
docker exec -it <container> py-spy dump --pid 1
```

## 6. 扩缩容

### 6.1 水平扩容
```bash
# K8s 扩容后端
kubectl scale deployment/sbaw-backend --replicas=5 -n sbaw

# HPA 自动扩容（CPU>70%）
kubectl get hpa -n sbaw
```

### 6.2 垂直扩容
修改 `values.yaml` 中的 resources：
```yaml
backend:
  resources:
    requests:
      cpu: 1000m
      memory: 1Gi
    limits:
      cpu: 2000m
      memory: 2Gi
```

### 6.3 数据库扩容
- 增加 max_connections
- 使用 PgBouncer 连接池
- 读写分离（主从复制）

## 7. 升级流程

### 7.1 滚动升级
```bash
# K8s 滚动升级（maxSurge=1, maxUnavailable=0）
kubectl set image deployment/sbaw-backend \
  backend=sbaw-backend:v1.1.0 -n sbaw

# 查看升级进度
kubectl rollout status deployment/sbaw-backend -n sbaw

# 回滚
kubectl rollout undo deployment/sbaw-backend -n sbaw
```

### 7.2 数据库迁移
```bash
# Alembic 迁移
cd backend
alembic revision --autogenerate -m "description"
alembic upgrade head

# 回滚
alembic downgrade -1
```
