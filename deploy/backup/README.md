# 备份恢复手册

## 概述

本目录包含智能招投标与合同合规 AI 工作台的备份与恢复脚本。

### 备份策略

| 类型 | 频率 | 保留时间 | 存储 |
|------|------|----------|------|
| PostgreSQL 全量 | 每日 02:00 | 7 天（日）/ 4 周（周）/ 12 月（月） | /var/backups/sbaw/postgres/ |
| MinIO 对象 | 每日 03:00 | 7 天 | /var/backups/sbaw/minio/ |
| WAL 归档 | 持续 | 7 天 | /var/backups/wal/ |

## 脚本说明

### 备份脚本

#### `backup_postgres.sh` — PostgreSQL 全量备份
- 使用 `pg_dump --format=custom` 全量备份
- gzip 压缩 + 时间戳命名
- 自动保留策略（日/周/月三级）
- gzip 完整性验证

```bash
# 手动执行
./backup_postgres.sh

# crontab 定时（每日 02:00）
0 2 * * * /opt/sbaw/deploy/backup/backup_postgres.sh >> /var/log/sbaw-backup.log 2>&1
```

#### `backup_minio.sh` — MinIO 对象备份
- 使用 `mc mirror` 同步到本地目录或远程备份桶
- 支持本地备份 + 远程 MinIO 备份

```bash
# 手动执行
./backup_minio.sh

# 配置远程备份（可选）
export BACKUP_MINIO_ENDPOINT="backup.minio.local:9000"
export BACKUP_MINIO_ACCESS_KEY="backup-key"
export BACKUP_MINIO_SECRET_KEY="backup-secret"
./backup_minio.sh
```

### 恢复脚本

#### `restore_postgres.sh` — PostgreSQL 恢复
```bash
# 从最新备份恢复
./restore_postgres.sh --latest

# 从指定备份恢复
./restore_postgres.sh --file /var/backups/sbaw/postgres/daily/sbaw_xxx.sql.gz

# 时间点恢复（PITR，需 WAL 归档）
./restore_postgres.sh --pitr "2026-07-01 14:30:00"
```

**恢复前安全备份**：恢复脚本会先备份当前数据库状态到 `/tmp/`。

#### `restore_minio.sh` — MinIO 恢复
```bash
# 从最新备份恢复
./restore_minio.sh --latest

# 从指定日期恢复
./restore_minio.sh --date 2026-07-01
```

### 验证脚本

#### `backup_verify.sh` — 备份验证
恢复备份到临时数据库实例，检查完整性：
- 表数量
- 各表记录数
- 关键表检查（user/role/permission/project/contract/document/qualification/knowledge_base）
- 索引数量

```bash
./backup_verify.sh --file /var/backups/sbaw/postgres/daily/sbaw_xxx.sql.gz
```

## 恢复演练

### 演练流程（建议每季度执行一次）

1. **准备测试环境**
   ```bash
   docker run -d --name sbaw-restore-test -p 15432:5432 \
       -e POSTGRES_PASSWORD=test pgvector/pgvector:pg16
   ```

2. **执行恢复**
   ```bash
   export POSTGRES_PORT=15432
   ./restore_postgres.sh --latest
   ```

3. **验证完整性**
   ```bash
   ./backup_verify.sh --file /var/backups/sbaw/postgres/daily/sbaw_xxx.sql.gz
   ```

4. **验证业务可用性**
   - 启动后端指向测试数据库
   - 登录系统验证
   - 检查关键业务数据

5. **清理**
   ```bash
   docker rm -f sbaw-restore-test
   ```

### WAL 归档配置（PITR）

在 `postgresql.conf` 中配置：
```
wal_level = replica
archive_mode = on
archive_command = 'cp %p /var/backups/wal/%f'
archive_timeout = 300
```

## 监控

- 备份失败告警：通过 crontab 邮件或 AlertManager webhook
- 备份大小监控：异常增长可能预示数据问题
- 备份完整性验证：每周自动执行 `backup_verify.sh`

## 故障排查

| 问题 | 原因 | 解决 |
|------|------|------|
| pg_dump 权限不足 | 用户无 SUPERUSER | 授予 pg_dump 所需权限 |
| 备份文件过小 | 备份失败 | 检查日志，重新备份 |
| 恢复后表缺失 | 备份不完整 | 用更早的备份 |
| MinIO 备份超时 | 数据量大 | 增量备份或分批 |
