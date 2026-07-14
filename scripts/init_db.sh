#!/bin/bash
# 通过 Docker 容器初始化 PostgreSQL 数据库
# 容器实际 superuser：tb_user（POSTGRES_USER），密码 tb_password，默认库 tb_db
# 创建独立 sbaw 用户与 sbaw 库（与现有业务隔离），并启用 pgvector + pg_trgm 扩展
# 不使用 set -e：每条命令已用 || 兜底，便于一次性跑完全部步骤
DB_USER=tb_user
DB_NAME=tb_db
NEW_USER=sbaw
NEW_PASS=sbaw_change_me
NEW_DB=sbaw

docker exec param-compare-postgres psql -U ${DB_USER} -d ${DB_NAME} -v ON_ERROR_STOP=0 -c \
  "CREATE USER ${NEW_USER} WITH PASSWORD '${NEW_PASS}' CREATEDB SUPERUSER;" 2>&1 || echo "USER_EXISTS"

docker exec param-compare-postgres psql -U ${DB_USER} -d ${DB_NAME} -v ON_ERROR_STOP=0 -c \
  "CREATE DATABASE ${NEW_DB} OWNER ${NEW_USER};" 2>&1 || echo "DB_EXISTS"

docker exec param-compare-postgres psql -U ${NEW_USER} -d ${NEW_DB} -c \
  "CREATE EXTENSION IF NOT EXISTS vector; CREATE EXTENSION IF NOT EXISTS pg_trgm;" 2>&1

echo "DONE"
