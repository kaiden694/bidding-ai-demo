#!/bin/bash
# 备份验证脚本
#
# 功能：
# - 恢复备份到临时数据库实例
# - 完整性检查（表数 / 记录数 / 关键表）
# - 输出验证报告
#
# 用法：
#   ./backup_verify.sh --file /var/backups/sbaw/postgres/daily/sbaw_xxx.sql.gz

set -euo pipefail

BACKUP_FILE=""
while [[ $# -gt 0 ]]; do
    case $1 in
        --file) BACKUP_FILE="$2"; shift 2 ;;
        *) echo "用法: $0 --file FILE"; exit 1 ;;
    esac
done

if [ -z "$BACKUP_FILE" ]; then
    echo "错误: 必须指定 --file"
    exit 1
fi

if [ ! -f "$BACKUP_FILE" ]; then
    echo "错误: 备份文件不存在: $BACKUP_FILE"
    exit 1
fi

# 临时验证数据库
VERIFY_DB="sbaw_verify_$(date +%s)"
PGHOST="${POSTGRES_HOST:-localhost}"
PGPORT="${POSTGRES_PORT:-5432}"
PGUSER="${POSTGRES_USER:-sbaw}"
PGPASSWORD="${POSTGRES_PASSWORD:-sbaw_change_me}"
export PGHOST PGPORT PGUSER PGPASSWORD

echo "[$(date)] 备份验证开始: file=$BACKUP_FILE"
echo "[$(date)] 临时数据库: $VERIFY_DB"

# ---- 创建临时数据库 ----
createdb "$VERIFY_DB" 2>/dev/null || true

# ---- 恢复到临时数据库 ----
echo "[$(date)] 恢复备份到临时数据库..."
gunzip -c "$BACKUP_FILE" | psql --dbname="$VERIFY_DB" --quiet --set ON_ERROR_STOP=on

# ---- 完整性检查 ----
echo ""
echo "===== 验证报告 ====="

# 1. 表数量
TABLE_COUNT=$(psql --dbname="$VERIFY_DB" --tuples-only -c "
    SELECT count(*) FROM information_schema.tables
    WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
")
echo "表数量: $TABLE_COUNT"

# 2. 各表记录数
echo ""
echo "各表记录数:"
psql --dbname="$VERIFY_DB" --tuples-only -c "
    SELECT relname, n_live_tup
    FROM pg_stat_user_tables
    ORDER BY relname
" | while read -r table count; do
    [ -n "$table" ] && echo "  $table: $count"
done

# 3. 关键表检查
echo ""
echo "关键表检查:"
for table in user role permission project contract document qualification knowledge_base; do
    COUNT=$(psql --dbname="$VERIFY_DB" --tuples-only -c "SELECT count(*) FROM $table" 2>/dev/null || echo "N/A")
    echo "  $table: $COUNT"
done

# 4. 索引检查
INDEX_COUNT=$(psql --dbname="$VERIFY_DB" --tuples-only -c "
    SELECT count(*) FROM pg_indexes WHERE schemaname = 'public'
")
echo ""
echo "索引数量: $INDEX_COUNT"

# ---- 清理 ----
echo ""
echo "[$(date)] 清理临时数据库..."
dropdb "$VERIFY_DB" 2>/dev/null || true

echo "[$(date)] 验证完成"
