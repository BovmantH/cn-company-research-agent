# Render 免费演示部署

本方案仅用于个人试用、开源项目预览和功能演示，不属于正规生产部署。生产环境应使用自有或云服务器，并配置持久化数据库、HTTPS、备份、监控和容量规划。

## 当前演示地址

当前尚未创建公开 Render 演示实例；创建并完成无付费调用验收后，本节会记录实际 HTTPS 地址。

## 一键部署

[在 Render 创建免费演示站](https://render.com/deploy?repo=https://github.com/BovmantH/cn-company-research-agent)

首次使用需要登录 Render，并授权 Render 读取 GitHub 仓库。创建前逐项确认页面没有出现付费资源或付款确认；出现时停止操作。

## 部署配置

仓库根目录的 `render.yaml` 声明一个 Web Service：

| 项目 | 值 |
|---|---|
| Runtime | Docker |
| Plan | Free |
| Region | Singapore |
| Health Check | `/health` |
| Auto Deploy | `main` 有新提交时自动部署 |

现有 Dockerfile 会构建 React 前端并复制进最终 Python 镜像。FastAPI 在同一域名提供页面、API 和 SSE，不需要拆分前后端或额外配置跨域。

演示站不配置部署者模型密钥、MongoDB 或企查查能力。用户仍在网页为单次任务选择模型并填写自己的 Key；Key 只应提交给可信的 HTTPS 部署地址。

## 免费层限制

- 连续约 15 分钟没有入站流量后，免费实例会休眠；下一次访问的冷启动可能接近 1 分钟。
- 文件系统和进程内状态不持久。休眠、重启或重新部署会丢失未持久化的任务、报告和临时 PDF。
- 平台可能重启实例，正在运行的调研任务和 SSE 连接可能中断。
- 免费实例小时、构建分钟或出站流量耗尽后，服务可能暂停。
- 免费规格不适合作为生产服务，也不能承诺永久在线。

## 创建与验收

1. 打开上方一键部署地址，使用 GitHub 登录或完成仓库授权。
2. 确认页面只创建一个 Docker Web Service，套餐为 Free，区域为 Singapore。
3. 确认没有数据库、持久盘、付费实例或 Secret，然后创建服务。
4. 等待 Docker 构建完成；Render 的健康检查必须通过 `/health`。
5. 打开 Render 分配的 HTTPS 地址，确认首页能显示完整的 9 家模型厂商。
6. 分别访问 `/health` 和 `/ai/providers`；前者应返回服务正常，后者应返回 9 家厂商。

验收过程不要填写真实 Key，也不要启动调研任务，避免产生模型或联网检索费用。

## 更新与排障

`main` 每次 push 后，Render 会自动重新构建和部署。排障顺序：

1. 构建失败：先查看 Render Deploy 日志中的第一个明确错误，不要只看最后一行。
2. 端口检测失败：确认容器监听 `0.0.0.0`，并使用 Render 注入的 `PORT`。
3. 健康检查失败：直接访问 `/health`，确认它能在 5 秒内返回 2xx。
4. 进程被终止：检查日志是否显示内存不足；免费规格不足时应停止部署并重新评估，不要静默升级付费套餐。
5. 首次访问很慢：先等待冷启动完成，再判断是否为应用故障。
6. 厂商请求失败：分别核对 Render 出站网络和厂商官方端点；不要把用户错误正文或 Key 写入日志。

Render 官方资料：

- [Docker 部署](https://render.com/docs/docker)
- [免费实例限制](https://render.com/docs/free)
- [Blueprint 规范](https://render.com/docs/blueprint-spec)
- [健康检查](https://render.com/docs/health-checks)

## 停止服务

暂停或删除 Render 服务会立即中止正在运行的任务。删除服务属于不可恢复的外部操作；执行前应确认不再需要演示地址和部署历史。
