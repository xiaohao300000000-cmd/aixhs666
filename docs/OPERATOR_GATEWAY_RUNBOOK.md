# 妙搭运营网关运行手册

## 目标

为妙搭运营控制台提供真实、只读、可恢复的公网数据入口：

```text
妙搭 React → 妙搭 NestJS BFF → HTTPS 隧道 → 本机 operator gateway → PostgreSQL
```

公网进程只包含：

- `GET /health`
- `GET /operator/api/workbench`，要求 `Authorization: Bearer <OPS_TOKEN>`

原 `/api/leads`、`/ops/api/*`、飞书回调和其他写接口不会注册到该进程。

## 本机服务

- 网关端口：`127.0.0.1:8020`
- 当前固定入口：`https://aixhs-operator-gateway.loca.lt`
- launchd：`com.aixhs.operator-gateway`
- launchd：`com.aixhs.operator-tunnel`
- 日志：`.runtime/operator-gateway*.log`、`.runtime/operator-tunnel*.log`

安装或刷新自动启动：

```bash
./scripts/install_operator_gateway_launchd.sh
```

检查：

```bash
launchctl print gui/$(id -u)/com.aixhs.operator-gateway
launchctl print gui/$(id -u)/com.aixhs.operator-tunnel
curl -fsS http://127.0.0.1:8020/health
curl -fsS https://aixhs-operator-gateway.loca.lt/health
```

## 妙搭线上环境

- `OPERATOR_API_BASE_URL=https://aixhs-operator-gateway.loca.lt`
- `OPERATOR_API_TOKEN` 与本机 `.env` 的 `OPS_TOKEN` 一致，仅保存于妙搭服务端。

严禁在聊天、日志、README 或浏览器响应中展示 token。

## 恢复顺序

1. `pg_isready -h 127.0.0.1 -p 5432` 确认 PostgreSQL。
2. 检查本地 `/health`。
3. 检查公网 `/health`。
4. 检查 launchd 两个服务和 `.runtime` 日志。
5. 公网持续 503 时重载 tunnel launchd；不要修改妙搭 URL，除非固定子域确实失效。

## 已知边界

- 当前数据库与网关仍运行在这台 Mac；机器关机、休眠或网络中断时线上页面进入降级态。
- localtunnel 已通过真实数据闭环，但稳定性弱于 Tailscale Funnel 或云托管。
- Tailscale 已登录，但账号尚未启用 Funnel。启用后应将公网入口升级为稳定 `ts.net`，并更新妙搭线上 `OPERATOR_API_BASE_URL`。
