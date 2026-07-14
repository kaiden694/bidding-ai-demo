#!/bin/bash
# MinIO 备份脚本
#
# 功能：
# - 用 mc mirror 同步到备份桶
# - 支持本地目录 + 远程 MinIO 备份桶
# - 保留策略：7 天日备份
#
# 用法：
#   ./backup_minio.sh
#
# 定时任务：
#   # 每日 03:00 备份
#   0 3 * * * /opt/sbaw/deploy/backup/backup_minio.sh >> /var/log/sbaw-backup.log 2>&1

set -euo pipefail

# ---- 配置 ----
BACKUP_DIR="${BACKUP_DIR:-/var/backups/sbaw/minio}"
RETENTION_DAYS=7

# 从 .env 读取 MinIO 配置
if [ -f /opt/sbaw/backend/.env ]; then
    source /opt/sbaw/backend/.env
fi

MINIO_ENDPOINT="${MINIO_ENDPOINT:-localhost:9000}"
MINIO_ACCESS_KEY="${MINIO_ACCESS_KEY:-minio}"
MINIO_SECRET_KEY="${MINIO_SECRET_KEY:-minio_change_me}"
MINIO_BUCKET="${MINIO_BUCKET:-sbaw-files}"

# 备份目标（可选：备份到另一个 MinIO 实例）
BACKUP_MINIO_ENDPOINT="${BACKUP_MINIO_ENDPOINT:-}"
BACKUP_MINIO_ACCESS_KEY="${BACKUP_MINIO_ACCESS_KEY:-}"
BACKUP_MINIO_SECRET_KEY="${BACKUP_MINIO_SECRET_KEY:-}"
BACKUP_MINIO_BUCKET="${BACKUP_MINIO_BUCKET:-sbaw-backup}"

TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
DATE=$(date +"%Y-%m-%d")

# ---- 安装 mc（如未安装）----
MC_BIN=$(which mc 2>/dev/null || echo "")
if [ -z "$MC_BIN" ]; then
    echo "[$(date)] mc 未安装，正在下载..."
    curl -fsSL https://dl.min.io/client/mc/release/linux-amd64/mc -o /usr/local/bin/mc
    chmod +x /usr/local/bin/mc
    MC_BIN="/usr/local/bin/mc"
fi

# ---- 配置 mc alias ----
$MC_BIN alias set source "http://$MINIO_ENDPOINT" "$MINIO_ACCESS_KEY" "$MINIO_SECRET_KEY" 2>/dev/null

echo "[$(date)] 开始 MinIO 备份: bucket=$MINIO_BUCKET"

# ---- 备份到本地目录 ----
mkdir -p "$BACKUP_DIR/$DATE"
echo "[$(date)] 备份到本地: $BACKUP_DIR/$DATE"
$MC_BIN mirror --overwrite source/$MINIO_BUCKET "$BACKUP_DIR/$DATE/$MINIO_BUCKET"

# ---- 备份到远程 MinIO（如配置）----
if [ -n "$BACKUP_MINIO_ENDPOINT" ]; then
    $MC_BIN alias set backup "http://$BACKUP_MINIO_ENDPOINT" "$BACKUP_MINIO_ACCESS_KEY" "$BACKUP_MINIO_SECRET_KEY" 2>/dev/null
    # 确保备份桶存在
    $MC_BIN mb --ignore-existing backup/$BACKUP_MINIO_BUCKET
    echo "[$(date)] 备份到远程 MinIO: $BACKUP_MINIO_ENDPOINT/$BACKUP_MINIO_BUCKET"
    $MC_BIN mirror --overwrite source/$MINIO_BUCKET "backup/$BACKUP_MINIO_BUCKET/$DATE"
fi

# ---- 清理旧备份 ----
echo "[$(date)] 清理 $RETENTION_DAYS 天前的本地备份..."
find "$BACKUP_DIR" -maxdepth 1 -type d -mtime +$RETENTION_DAYS -exec rm -rf {} \;

# ---- 统计 ----
LOCAL_SIZE=$(du -sh "$BACKUP_DIR/$DATE" 2>/dev/null | cut -f1)
echo "[$(date)] 备份完成: date=$DATE local_size=$LOCAL_SIZE"
