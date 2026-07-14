-- 启用 pgvector 扩展（向量检索）
CREATE EXTENSION IF NOT EXISTS vector;

-- 启用模糊匹配扩展（关键词混合检索）
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- 启用 UUID 生成
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- 注: 业务表通过 Alembic 迁移管理，这里仅启用扩展
