# 上线检查清单（Deployment Checklist）

> 智能招投标与合同合规 AI 工作台

## 1. 基础设施检查

### 1.1 计算资源
- [ ] K8s 集群可用，节点资源充足（CPU/Memory/Disk）
- [ ] 命名空间 `sbaw` 已创建
- [ ] StorageClass 可用（用于 PVC）
- [ ] Ingress Controller 已部署
- [ ] HPA 配置正确（min=2, max=10, CPU>70%）

### 1.2 数据库
- [ ] PostgreSQL 16 + pgvector 扩展已安装
- [ ] pg_trgm + uuid-ossp 扩展已创建
- [ ] 数据库密码已修改（非默认值）
- [ ] 连接池大小合理（pool_size=10, max_overflow=20）
- [ ] 备份策略已配置（每日全量 + WAL 归档）
- [ ] 初始迁移已执行（`alembic upgrade head`）

### 1.3 缓存
- [ ] Redis 7 已部署
- [ ] Redis 密码已设置（生产环境）
- [ ] Redis 内存限制合理（maxmemory + maxmemory-policy=allkeys-lru）

### 1.4 对象存储
- [ ] MinIO 已部署
- [ ] MinIO Access Key / Secret Key 已修改
- [ ] Bucket 已创建（`sbaw-files`）
- [ ] 备份策略已配置

### 1.5 网络
- [ ] DNS 解析正确
- [ ] TLS 证书已配置（HTTPS）
- [ ] 防火墙规则正确（仅暴露 80/443）
- [ ] 内部服务间通信不受限（NetworkPolicy）

## 2. 应用配置检查

### 2.1 安全配置
- [ ] `SECRET_KEY` 已修改（非默认值，≥32 字符）
- [ ] `ENCRYPTION_KEY` 已生成并配置
- [ ] `JWT_ALGORITHM=HS256`
- [ ] `JWT_ACCESS_EXPIRE_MINUTES=120`
- [ ] `APP_ENV=prod`（非 dev）
- [ ] Swagger UI 已关闭或受限（`docs_url=None`）
- [ ] CORS_ORIGINS 仅包含可信域名

### 2.2 数据库配置
- [ ] `POSTGRES_HOST` 指向正确的数据库 Service
- [ ] `POSTGRES_PASSWORD` 从 Secret 读取
- [ ] `POSTGRES_POOL_SIZE` 合理（生产建议 20）

### 2.3 LLM 配置
- [ ] `LLM_BASE_URL` 指向正确的 LLM 服务
- [ ] `LLM_API_KEY` 已配置且有效
- [ ] `LLM_MODEL` 指定生产模型
- [ ] `LLM_TIMEOUT` 合理（建议 120s）
- [ ] 多 LLM 提供商已配置（故障切换）

### 2.4 Celery 配置
- [ ] `CELERY_BROKER_URL` 指向正确的 Redis
- [ ] Celery Worker 副本数合理（建议 2+）
- [ ] Celery Beat 定时任务配置正确（资质预警 + 待办提醒 + LLM 健康检查）

### 2.5 监控配置
- [ ] `OTEL_ENABLED=true`（如需链路追踪）
- [ ] `OTEL_EXPORTER_OTLP_ENDPOINT` 指向 Tempo/OTEL Collector
- [ ] Prometheus 采集配置正确（`/metrics`）
- [ ] Grafana 数据源已配置（Prometheus + Loki + Tempo）
- [ ] AlertManager 告警规则已加载
- [ ] 告警通知渠道已配置（邮件/钉钉/企业微信）

## 3. 数据检查

- [ ] 初始数据已导入（权限点 / 角色 / 默认管理员）
- [ ] 默认管理员密码已修改（非 admin123）
- [ ] 知识库初始数据已导入（如需要）
- [ ] 资质台账数据已导入（如需要）

## 4. 安全检查

- [ ] 所有密码非默认值
- [ ] 所有 API Key 非占位符
- [ ] Secret 已加密（sealed-secrets / external-secrets）
- [ ] 速率限制已启用（全局 100/min, 登录 5/min, AI 10/min）
- [ ] 安全响应头已生效（X-Frame-Options / CSP / HSTS）
- [ ] HTTPS 已强制（HSTS + 80→443 重定向）
- [ ] 日志不包含敏感信息（密码 / API Key 已脱敏）
- [ ] 数据库备份已加密（如存储在云存储）

## 5. 性能检查

- [ ] 压测通过（100 并发，P95 < 3s）
- [ ] 数据库索引已创建
- [ ] N+1 查询已检测并修复
- [ ] Redis 缓存已启用（权限点 / 知识库列表）
- [ ] 静态资源已压缩（前端 gzip）
- [ ] CDN 已配置（如需要）

## 6. 备份检查

- [ ] PostgreSQL 备份脚本已部署
- [ ] MinIO 备份脚本已部署
- [ ] 备份定时任务已配置（crontab / K8s CronJob）
- [ ] 备份保留策略已设置（7d/4w/12m）
- [ ] 备份验证脚本已测试
- [ ] 恢复演练已完成

## 7. 文档检查

- [ ] 运维手册已更新（`docs/ops-manual.md`）
- [ ] 应急预案已更新（`docs/emergency-runbook.md`）
- [ ] 联系方式已填写
- [ ] 用户手册已完成
- [ ] 培训已完成

## 8. 上线后验证

- [ ] 健康检查通过（`GET /health`）
- [ ] 登录功能正常
- [ ] 核心 API 可用（项目/合同/比对/知识库/资质）
- [ ] Celery 任务正常（检查资质预警任务）
- [ ] LLM 调用正常（AI 助手/比对/审查）
- [ ] 监控指标正常（Grafana 大盘有数据）
- [ ] 日志正常（Loki 可查询）
- [ ] 告警通道正常（测试告警发送）

## 9. 回滚方案

- [ ] 回滚脚本已准备
- [ ] 数据库回滚迁移已测试
- [ ] 前一版本镜像可用
- [ ] 回滚步骤已文档化

```bash
# K8s 回滚
kubectl rollout undo deployment/sbaw-backend -n sbaw
kubectl rollout undo deployment/sbaw-frontend -n sbaw

# 数据库回滚
cd backend && alembic downgrade -1
```

## 10. 签字确认

| 检查项 | 负责人 | 确认日期 |
|--------|--------|----------|
| 基础设施 | ______ | ______ |
| 应用配置 | ______ | ______ |
| 安全 | ______ | ______ |
| 性能 | ______ | ______ |
| 备份 | ______ | ______ |
| 文档 | ______ | ______ |
