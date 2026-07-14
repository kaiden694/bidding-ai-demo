# =========================================================
# 根目录 Dockerfile（Railway backend / worker 入口）
# 同时支持 backend API 和 Celery worker（共享镜像）
# =========================================================
# Railway Service 配置：
#   - backend service: 用本 Dockerfile，启动命令默认（uvicorn）
#   - worker service:  用本 Dockerfile，启动命令覆盖为 celery
#   - frontend service: 在 Railway 控制台设置 Root Directory = frontend/admin
# =========================================================

FROM python:3.11-slim

# 系统依赖（PDF 解析需要）
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    libgl1 \
    libglib2.0-0 \
    libmupdf-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 依赖层（利用缓存）
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# 应用代码
COPY backend/ .

EXPOSE 8000

# Railway 会注入 $PORT 环境变量，默认回退到 8000
# worker service 会在 Railway 控制台覆盖启动命令为 celery
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
