# 应急预案（Emergency Runbook）

> 智能招投标与合同合规 AI 工作台

## 1. 数据库故障

### 1.1 数据库不可达
**现象**：API 返回 500，日志显示 `connection refused`

**处理**：
1. 检查 PostgreSQL 容器/Pod 状态
   ```bash
   docker-compose ps postgres
   kubectl get pods -n sbaw | grep postgres
   ```
2. 如 Pod 重启失败，查看日志
   ```bash
   kubectl logs sbaw-postgres-0 -n sbaw
   ```
3. 恢复步骤
   - 磁盘满 → 清理 WAL 归档 → 重启
   - 数据损坏 → 从备份恢复（见 `deploy/backup/restore_postgres.sh`）
4. 通知用户：系统维护中

### 1.2 数据损坏
**现象**：查询返回异常数据，表缺失

**处理**：
1. 立即停止后端服务（避免进一步写入）
2. 创建当前状态快照（用于事后分析）
3. 从备份恢复：`./deploy/backup/restore_postgres.sh --latest`
4. 验证恢复：`./deploy/backup/backup_verify.sh --file <backup>`
5. 重启服务

## 2. LLM 服务故障

### 2.1 LLM 全部不可达
**现象**：AI 功能失败，熔断器触发

**处理**：
1. 检查 LLM 提供商健康状态
   ```bash
   curl -H "Authorization: Bearer $TOKEN" \
     http://localhost:8000/api/v1/admin/llm-providers/health
   ```
2. 检查网络连通性
   ```bash
   curl -v http://<llm-host>/v1/models
   ```
3. 恢复步骤：
   - LLM 服务宕机 → 联系 LLM 服务提供方
   - 网络问题 → 检查 DNS / 防火墙
   - API Key 过期 → 更新 LLM_API_KEY
4. 临时降级：AI 功能返回"服务暂时不可用"

### 2.2 LLM 响应质量下降
**现象**：比对/审查结果异常

**处理**：
1. 检查 LLM 用量统计（可能超限）
2. 切换备用模型
3. 检查 RAG 召回是否正常

## 3. 磁盘满

**现象**：写入失败，日志 `No space left on device`

**处理**：
1. 检查磁盘使用
   ```bash
   df -h
   docker system df
   ```
2. 清理空间
   ```bash
   # 清理 Docker 日志
   docker system prune -a --volumes
   # 清理旧备份
   find /var/backups -mtime +30 -delete
   # 清理 WAL 归档
   find /var/backups/wal -mtime +7 -delete
   # 清理临时文件
   find /tmp -name "sbaw_*" -mtime +1 -delete
   ```
3. 扩容磁盘（如云环境）
4. 调整日志级别（prod 用 INFO，非 DEBUG）

## 4. 安全事件

### 4.1 账号被盗
**现象**：异常登录记录，未授权操作

**处理**：
1. 立即禁用账号
   ```bash
   # 通过 API
   curl -X PATCH -H "Authorization: Bearer $ADMIN_TOKEN" \
     http://localhost:8000/api/v1/users/<user_id> \
     -H "Content-Type: application/json" \
     -d '{"is_active": false}'
   ```
2. 查看审计日志，确定影响范围
   ```bash
   curl -H "Authorization: Bearer $ADMIN_TOKEN" \
     "http://localhost:8000/api/v1/audit-logs?user_id=<user_id>"
   ```
3. 撤销该用户的所有 JWT（如实现了黑名单）
4. 通知用户重置密码
5. 如数据泄露：评估影响 + 上报

### 4.2 SQL 注入
**现象**：审计日志中出现异常 SQL

**处理**：
1. 修复漏洞（参数化查询）
2. 检查数据完整性
3. 审计受影响的表

### 4.3 DDoS 攻击
**现象**：请求量激增，速率限制频繁触发

**处理**：
1. 调整速率限制（降低阈值）
2. 封禁恶意 IP（Nginx / WAF 层）
3. 启用 CDN 防护

## 5. 服务不可用

### 5.1 后端全部宕机
**处理**：
1. 检查 Pod 状态 + 日志
2. 如配置错误 → 回滚配置
3. 如资源不足 → 扩容
4. 如代码 bug → 回滚版本

```bash
# K8s 回滚
kubectl rollout undo deployment/sbaw-backend -n sbaw
```

### 5.2 前端不可达
**处理**：
1. 检查 Nginx 容器
2. 检查 Ingress 配置
3. 检查前端构建产物

## 6. 联系方式

| 角色 | 职责 | 联系方式 |
|------|------|----------|
| 运维负责人 | 基础设施 | <填入> |
| 后端负责人 | API 服务 | <填入> |
| 前端负责人 | 前端页面 | <填入> |
| DBA | 数据库 | <填入> |
| 安全负责人 | 安全事件 | <填入> |

## 7. 事故后复盘模板

每次事故后填写：
- 事故时间：YYYY-MM-DD HH:MM
- 影响范围：<受影响的服务/用户>
- 持续时间：<XX 分钟>
- 根本原因：<分析>
- 处理步骤：<时间线>
- 改进措施：<action items>
