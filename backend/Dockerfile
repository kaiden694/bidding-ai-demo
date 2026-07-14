FROM python:3.11-slim

# 系统依赖（OCR/PDF 解析需要）
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    libgl1 \
    libglib2.0-0 \
    libmupdf-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 依赖层（利用缓存）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 应用代码
COPY . .

EXPOSE 8000

# 默认启动命令（docker-compose 会覆盖以支持 --reload）
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
