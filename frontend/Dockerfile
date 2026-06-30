# 阶段1：构建
FROM node:20-alpine AS builder

WORKDIR /app

COPY package.json ./
RUN npm install --registry=https://registry.npmmirror.com

COPY . .

# 构建时注入 API 地址（空字符串表示同源，nginx 反向代理到 /api）
ARG VITE_API_BASE=
ENV VITE_API_BASE=$VITE_API_BASE

RUN npm run build

# 阶段2：nginx 运行
FROM nginx:alpine

# 复制构建产物
COPY --from=builder /app/dist /usr/share/nginx/html

# 复制 nginx 配置
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
