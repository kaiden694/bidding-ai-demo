#!/bin/bash
# MinIO 恢复脚本
#
# 功能：
# - 从本地备份恢复到 MinIO
# - 支持指定日期恢复
# - 恢复前自动备份当前状态
#
# 用法：
#   # 从最新备份恢复
#   ./restore_minio.sh --latest
#
#   # 从指定日期恢复
#   ./restore_minio.sh --date 2026-07-01

set -euo pipefail

# ---- 配置 ----
BACKUP_DIR="${BACKUP_DIR:-/var/backups/sbaw/minio}"

if [ -f /opt/sbaw/backend/.env ]; then
    source /opt/sbaw/backend/.env
fi

MINIO_ENDPOINT="${MINIO_ENDPOINT:-localhost:9000}"
MINIO_ACCESS_KEY="${MINIO_ACCESS_KEY:-minio}"
MINIO_SECRET_KEY="${MINIO_SECRET_KEY:-minio_change_me}"
MINIO_BUCKET="${MINIO_BUCKET:-sbaw-files}"

RESTORE_DATE=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --latest)
            RESTORE_DATE=$(find "$BACKUP_DIR" -maxdepth 1 -type d -name "20*" | sort | tail -1 | xargs basename)
            shift
            ;;
        --date)
            RESTORE_DATE="$2"
            shift 2
            ;;
        *)
            echo "用法: $0 [--latest | --date YYYY-MM-DD]"
            exit 1
            ;;
    esac
done

if [ -z "$RESTORE_DATE" ]; then
    echo "错误: 必须指定 --latest 或 --date"
    exit 1
fi

BACKUP_PATH="$BACKUP_DIR/$RESTORE_DATE/$MINIO_BUCKET"

if [ ! -d "$BACKUP_PATH" ]; then
    echo "错误: 备份目录不存在: $BACKUP_PATH"
    exit 1
fi

# ---- mc 配置 ----
MC_BIN=$(which mc 2>/dev/null || echo "/usr/local/bin/mc")
$MC_BIN alias set target "http://$MINIO_ENDPOINT" "$MINIO_ACCESS_KEY" "$MINIO_SECRET_KEY" 2>/dev/null

echo "[$(date)] 开始 MinIO 恢复: date=$RESTORE_DATE"

# ---- 恢复前安全备份 ----
SAFETY_DIR="/tmp/sbaw_minio_pre_restore_$(date +%Y%m%d_%H%M%S)"
echo "[$(date)] 恢复前安全备份: $SAFETY_DIR"
mkdir -p "$SAFETY_DIR"
$MC_BIN mirror --overwrite target/$MINIO_BUCKET "$SAFETY_DIR/$MINIO_BUCKET"

# ---- 执行恢复 ----
echo "[$(date)] 从 $BACKUP_PATH 恢复到 $MINIO_BUCKET"
$MC_BIN mirror --overwrite "$BACKUP_PATH" target/$MINIO_BUCKET

echo "[$(date)] 恢复完成"
echo "[$(date)] 安全备份位于: $SAFETY_DIR"
