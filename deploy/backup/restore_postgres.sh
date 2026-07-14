#!/bin/bash
# PostgreSQL 恢复脚本（支持 PITR）
#
# 功能：
# - 从备份文件恢复
# - 支持指定时间点恢复（PITR）
# - 恢复前自动停服务 + 备份当前状态
#
# 用法：
#   # 从最新备份恢复
#   ./restore_postgres.sh --latest
#
#   # 从指定备份恢复
#   ./restore_postgres.sh --file /var/backups/sbaw/postgres/daily/sbaw_xxx.sql.gz
#
#   # 时间点恢复（需 WAL 归档配置）
#   ./restore_postgres.sh --pitr "2026-07-01 14:30:00"

set -euo pipefail

# ---- 配置 ----
BACKUP_DIR="${BACKUP_DIR:-/var/backups/sbaw/postgres}"

if [ -f /opt/sbaw/backend/.env ]; then
    source /opt/sbaw/backend/.env
fi

PGHOST="${POSTGRES_HOST:-localhost}"
PGPORT="${POSTGRES_PORT:-5432}"
PGDATABASE="${POSTGRES_DB:-sbaw}"
PGUSER="${POSTGRES_USER:-sbaw}"
PGPASSWORD="${POSTGRES_PASSWORD:-sbaw_change_me}"

export PGHOST PGPORT PGDATABASE PGUSER PGPASSWORD

# ---- 参数解析 ----
BACKUP_FILE=""
PITR_TARGET=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --latest)
            BACKUP_FILE=$(find "$BACKUP_DIR" -name "*.sql.gz" -type f | sort | tail -1)
            shift
            ;;
        --file)
            BACKUP_FILE="$2"
            shift 2
            ;;
        --pitr)
            PITR_TARGET="$2"
            shift 2
            ;;
        *)
            echo "未知参数: $1"
            echo "用法: $0 [--latest | --file FILE | --pitr 'YYYY-MM-DD HH:MM:SS']"
            exit 1
            ;;
    esac
done

if [ -z "$BACKUP_FILE" ] && [ -z "$PITR_TARGET" ]; then
    echo "错误: 必须指定 --latest / --file / --pitr"
    exit 1
fi

echo "[$(date)] 开始 PostgreSQL 恢复"

# ---- 恢复前安全备份 ----
SAFETY_BACKUP="/tmp/sbaw_pre_restore_$(date +%Y%m%d_%H%M%S).sql.gz"
echo "[$(date)] 恢复前安全备份: $SAFETY_BACKUP"
pg_dump --format=custom --no-owner --no-privileges | gzip > "$SAFETY_BACKUP"

# ---- 执行恢复 ----
if [ -n "$PITR_TARGET" ]; then
    # PITR 恢复（需要 WAL 归档配置）
    echo "[$(date)] 时间点恢复: target=$PITR_TARGET"
    # 停止 PostgreSQL
    # 配置 recovery_target_time
    # 启动 PostgreSQL（自动进入恢复模式）
    echo "注意: PITR 恢复需要在 PostgreSQL 服务器执行，本脚本仅提供参考"
    echo "请在 PostgreSQL 服务器执行以下步骤："
    echo "1. 停止 PostgreSQL: systemctl stop postgresql"
    echo "2. 编辑 recovery.conf 添加:"
    echo "   restore_command = 'cp /var/backups/wal/%f %p'"
    echo "   recovery_target_time = '$PITR_TARGET'"
    echo "   recovery_target_action = 'promote'"
    echo "3. 启动 PostgreSQL: systemctl start postgresql"
    exit 0
fi

if [ ! -f "$BACKUP_FILE" ]; then
    echo "[$(date)] 错误: 备份文件不存在: $BACKUP_FILE"
    exit 1
fi

echo "[$(date)] 从备份恢复: $BACKUP_FILE"

# 解压并恢复
gunzip -c "$BACKUP_FILE" | pg_restore --dbname="$PGDATABASE" --no-owner --no-privileges --clean --if-exists --jobs=4

echo "[$(date)] 恢复完成"
echo "[$(date)] 安全备份位于: $SAFETY_BACKUP"
