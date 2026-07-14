#!/bin/bash
# PostgreSQL 全量备份脚本
#
# 功能：
# - pg_dump 全量备份
# - 压缩 + 时间戳命名
# - 保留策略：7 天日备份 + 4 周周备份 + 12 月月备份
# - 备份完整性验证
#
# 用法：
#   ./backup_postgres.sh
#
# 定时任务（crontab -e）：
#   # 每日 02:00 全量备份
#   0 2 * * * /opt/sbaw/deploy/backup/backup_postgres.sh >> /var/log/sbaw-backup.log 2>&1
#
# 环境变量（从 .env 读取或手动设置）：
#   POSTGRES_HOST / POSTGRES_PORT / POSTGRES_DB / POSTGRES_USER / POSTGRES_PASSWORD

set -euo pipefail

# ---- 配置 ----
BACKUP_DIR="${BACKUP_DIR:-/var/backups/sbaw/postgres}"
RETENTION_DAILY=7       # 日备份保留 7 天
RETENTION_WEEKLY=28     # 周备份保留 4 周
RETENTION_MONTHLY=365   # 月备份保留 12 月

# 从环境变量或 .env 读取数据库配置
if [ -f /opt/sbaw/backend/.env ]; then
    source /opt/sbaw/backend/.env
fi

PGHOST="${POSTGRES_HOST:-localhost}"
PGPORT="${POSTGRES_PORT:-5432}"
PGDATABASE="${POSTGRES_DB:-sbaw}"
PGUSER="${POSTGRES_USER:-sbaw}"
PGPASSWORD="${POSTGRES_PASSWORD:-sbaw_change_me}"

export PGHOST PGPORT PGDATABASE PGUSER PGPASSWORD

# ---- 时间戳 ----
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
DATE=$(date +"%Y-%m-%d")
DAY_OF_WEEK=$(date +"%u")  # 1=Monday
DAY_OF_MONTH=$(date +"%d")

# ---- 创建备份目录 ----
mkdir -p "$BACKUP_DIR/daily" "$BACKUP_DIR/weekly" "$BACKUP_DIR/monthly"

# ---- 备份文件名 ----
BACKUP_FILE="sbaw_${PGDATABASE}_${TIMESTAMP}.sql.gz"

# ---- 确定备份类型 ----
BACKUP_TYPE="daily"
BACKUP_DIR_TARGET="$BACKUP_DIR/daily"

# 每周一做周备份
if [ "$DAY_OF_WEEK" = "1" ]; then
    BACKUP_TYPE="weekly"
    BACKUP_DIR_TARGET="$BACKUP_DIR/weekly"
fi

# 每月 1 号做月备份
if [ "$DAY_OF_MONTH" = "01" ]; then
    BACKUP_TYPE="monthly"
    BACKUP_DIR_TARGET="$BACKUP_DIR/monthly"
fi

BACKUP_PATH="$BACKUP_DIR_TARGET/$BACKUP_FILE"

echo "[$(date)] 开始 PostgreSQL 备份: type=$BACKUP_TYPE file=$BACKUP_PATH"

# ---- 执行备份 ----
pg_dump --format=custom --no-owner --no-privileges | gzip > "$BACKUP_PATH"

# ---- 验证备份 ----
if [ -f "$BACKUP_PATH" ]; then
    FILESIZE=$(stat -c%s "$BACKUP_PATH" 2>/dev/null || stat -f%z "$BACKUP_PATH")
    if [ "$FILESIZE" -lt 1024 ]; then
        echo "[$(date)] 错误: 备份文件过小 ($FILESIZE bytes)，可能失败"
        rm -f "$BACKUP_PATH"
        exit 1
    fi
    echo "[$(date)] 备份成功: $BACKUP_PATH ($FILESIZE bytes)"

    # 验证 gzip 完整性
    if gzip -t "$BACKUP_PATH" 2>/dev/null; then
        echo "[$(date)] gzip 完整性验证通过"
    else
        echo "[$(date)] 警告: gzip 完整性验证失败"
    fi
else
    echo "[$(date)] 错误: 备份文件未创建"
    exit 1
fi

# ---- 清理旧备份 ----
echo "[$(date)] 清理旧备份..."
find "$BACKUP_DIR/daily" -name "*.sql.gz" -mtime +$RETENTION_DAILY -delete
find "$BACKUP_DIR/weekly" -name "*.sql.gz" -mtime +$RETENTION_WEEKLY -delete
find "$BACKUP_DIR/monthly" -name "*.sql.gz" -mtime +$RETENTION_MONTHLY -delete

# ---- 统计 ----
DAILY_COUNT=$(find "$BACKUP_DIR/daily" -name "*.sql.gz" | wc -l)
WEEKLY_COUNT=$(find "$BACKUP_DIR/weekly" -name "*.sql.gz" | wc -l)
MONTHLY_COUNT=$(find "$BACKUP_DIR/monthly" -name "*.sql.gz" | wc -l)

echo "[$(date)] 备份完成: daily=$DAILY_COUNT weekly=$WEEKLY_COUNT monthly=$MONTHLY_COUNT"
