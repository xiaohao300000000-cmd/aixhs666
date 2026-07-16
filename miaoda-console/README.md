# AI 获客运营控制台

飞书妙搭全栈应用，为 `aixhs666` 提供可视化与操作入口。`V19-04` 在既有工作台上完成运营闭环呈现：

- `/`：以真实审核进度、客户状态和阻塞异常决定“今天最重要的事”。
- `/tasks?run_id=<id>`：展示人类业务结论、漏斗、候选分层、数据去向和审核深链。
- `/leads`：恢复每日审核批次与当前项，连续展示证据、动作后果和幂等人工审核入口。
- `/customers`、`/customers/:id`：展示客户阶段、下一步、时间线和真实 Base CRM 深链。
- `/system-health`：集中展示 Worker、阻塞/非阻塞异常和安全脱敏的恢复信息。
- 后端不可达、字段缺失、空队列和未接入能力均明确降级，不使用演示数字冒充真实状态。

## 架构边界

- React 客户端只访问同源 `/api/operator/**`，不接触 Operator token。
- NestJS BFF 使用服务端环境变量代理既有 FastAPI Operator API，并安全翻译上游错误。
- FastAPI/PostgreSQL/Worker 继续承载核心业务与事实数据；妙搭不复制核心逻辑。
- `OPERATOR_API_TOKEN` 只存在于妙搭服务端，绝不返回浏览器。

## 环境变量

| Key | 说明 |
|---|---|
| `OPERATOR_API_BASE_URL` | 现有 FastAPI 的稳定公网根地址，不带尾部 `/` |
| `OPERATOR_API_TOKEN` | 与 FastAPI `OPS_TOKEN` 一致的服务端凭证 |

缺少变量或后端不可达时，页面进入可行动降级态，不渲染静态演示数据。

## 本地开发

```bash
npm install
OPERATOR_API_BASE_URL=http://127.0.0.1:8018 \
OPERATOR_API_TOKEN=<server-only-token> \
npm run dev
```

开发入口由妙搭脚手架输出，当前应用 ID 为 `app_17a4790srtt`。

## 验证

```bash
npm test -- --runInBand
npm run type:check
npm run lint
npm run build
```

`V19-04` 本地真实只读联调覆盖工作台、Run 报告、每日审核队列、客户列表/详情/时间线和系统健康；生产发布、环境变量、可见范围与线上验收由主控在合并后执行。
