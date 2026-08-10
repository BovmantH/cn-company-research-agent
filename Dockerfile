# 阶段 1：构建前端
FROM node:20-slim AS frontend-builder
WORKDIR /app/ui
COPY ui/package*.json ./
RUN npm install
COPY ui/ ./
RUN npm run build

# 阶段 2：构建后端
FROM python:3.11-slim AS backend-builder
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 阶段 3：生成最终镜像
FROM python:3.11-slim
WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 复制后端代码和依赖
COPY --from=backend-builder /usr/local/lib/python3.11/site-packages/ /usr/local/lib/python3.11/site-packages/
COPY backend/ ./backend/
COPY application.py .

# 复制前端构建产物
COPY --from=frontend-builder /app/ui/dist/ ./ui/dist/

# 创建报告目录
RUN mkdir -p reports

# 设置环境变量
ENV PYTHONUNBUFFERED=1
ENV PORT=8000

# 暴露服务端口
EXPOSE 8000

# 创建非 root 用户
RUN useradd -m -u 1000 appuser
RUN chown -R appuser:appuser /app
USER appuser

# 启动命令
CMD ["sh", "-c", "python -m uvicorn application:app --host 0.0.0.0 --port ${PORT:-8000}"]
