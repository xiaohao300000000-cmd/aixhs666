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
- 稳定入口：`https://xiaohao30000macbook-pro.tail9daeec.ts.net`
- launchd：`com.aixhs.operator-gateway`
- Tailscale Funnel：HTTPS 443 → `127.0.0.1:8020`
- 日志：`.runtime/operator-gateway*.log`

安装或刷新自动启动：

```bash
./scripts/install_operator_gateway_launchd.sh
```

检查：

```bash
launchctl print gui/$(id -u)/com.aixhs.operator-gateway
curl -fsS http://127.0.0.1:8020/health
/Applications/Tailscale.app/Contents/MacOS/Tailscale funnel status
curl -fsS https://xiaohao30000macbook-pro.tail9daeec.ts.net/health
```

## 妙搭线上环境

- `OPERATOR_API_BASE_URL=https://xiaohao30000macbook-pro.tail9daeec.ts.net`
- `OPERATOR_API_TOKEN` 与本机 `.env` 的 `OPS_TOKEN` 一致，仅保存于妙搭服务端。

严禁在聊天、日志、README 或浏览器响应中展示 token。

## 恢复顺序

1. `pg_isready -h 127.0.0.1 -p 5432` 确认 PostgreSQL。
2. 检查本地 `/health`。
3. 检查公网 `/health`。
4. 检查网关 launchd、Tailscale 状态和 `.runtime` 日志。
5. Funnel 异常时重新执行 `./scripts/install_operator_gateway_launchd.sh`；稳定 `ts.net` 地址不需要随进程重启修改。

## 已知边界

- 当前数据库与网关仍运行在这台 Mac；机器关机、休眠或网络中断时线上页面进入降级态。
- Tailscale Funnel 已启用并使用稳定 `ts.net` 地址；下一阶段仍应把数据库和网关迁移到持续在线云托管。
