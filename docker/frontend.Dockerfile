# 安全最佳实践: 前端使用多阶段构建，生产环境用 nginx 提供静态文件服务
# 避免在生产环境使用 Vite dev server（暴露源码、无压缩、含开发工具）

# ---- 阶段 1: 构建静态文件 ----
FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci --silent || npm install --silent
COPY . .
# 构建时注入 API 地址(通过 ARG)
ARG VITE_API_BASE=/api/v1
ENV VITE_API_BASE=$VITE_API_BASE
RUN npm run build

# ---- 阶段 2: nginx 提供生产服务 ----
FROM nginx:alpine-slim
# 安全最佳实践: 复制构建产物到 nginx 静态目录
COPY --from=builder /app/dist /usr/share/nginx/html
# 自定义 nginx 配置: SPA 路由回退 + 安全头
RUN cat > /etc/nginx/conf.d/default.conf <<'EOF'
server {
    listen 80;
    server_name _;
    root /usr/share/nginx/html;
    index index.html;

    # SPA 路由: 所有未匹配的路由回退到 index.html
    location / {
        try_files $uri $uri/ /index.html;
    }

    # 静态资源缓存(Vite 构建产物带 hash，可长期缓存)
    location /assets/ {
        expires 1y;
        add_header Cache-Control "public, immutable";
    }

    # 安全头(安全最佳实践: 基础防护)
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;

    # 禁止访问隐藏文件
    location ~ /\. {
        deny all;
    }
}
EOF
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
