# =========================================================
# 前端管理后台 Dockerfile（多阶段构建）
# 阶段 1: Node 构建产物
# 阶段 2: nginx 托管静态文件 + 反代 /api → backend:8000
# =========================================================

# ---------- 阶段 1：构建 ----------
FROM node:20-alpine AS builder
WORKDIR /app

# 利用缓存：先装依赖
COPY package.json package-lock.json* ./
RUN npm ci --no-audit --no-fund || npm install --no-audit --no-fund

# 拷贝源码并构建
COPY . .
RUN npm run build

# ---------- 阶段 2：nginx 托管 ----------
FROM nginx:1.27-alpine

# 复制构建产物
COPY --from=builder /app/dist /usr/share/nginx/html

# nginx 配置模板：启动时通过 envsubst 替换 ${BACKEND_HOST}（支持 docker-compose 和 Railway）
# docker-compose: BACKEND_HOST=backend:8000
# Railway: BACKEND_HOST=<backend-service-domain>:80
RUN printf '%s\n' \
    'server {' \
    '    listen 80;' \
    '    server_name _;' \
    '' \
    '    location / {' \
    '        root /usr/share/nginx/html;' \
    '        index index.html;' \
    '        try_files $uri $uri/ /index.html;' \
    '    }' \
    '' \
    '    location /api/ {' \
    '        proxy_pass http://${BACKEND_HOST};' \
    '        proxy_set_header Host $host;' \
    '        proxy_set_header X-Real-IP $remote_addr;' \
    '        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;' \
    '        proxy_set_header X-Forwarded-Proto $scheme;' \
    '        proxy_request_buffering off;' \
    '        proxy_read_timeout 300s;' \
    '        client_max_body_size 100m;' \
    '    }' \
    '' \
    '    gzip on;' \
    '    gzip_types text/plain text/css application/javascript application/json image/svg+xml;' \
    '    gzip_min_length 1024;' \
    '}' \
    > /etc/nginx/templates/default.conf.template

EXPOSE 80

# nginx:1.27+ 会自动执行 envsubst 处理 /etc/nginx/templates/*.template
# 替换 ${VAR} 后输出到 /etc/nginx/conf.d/default.conf
CMD ["nginx", "-g", "daemon off;"]
