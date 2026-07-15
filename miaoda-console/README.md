# AI 获客运营控制台

飞书妙搭全栈应用，为 `aixhs666` 提供可视化与操作入口。当前 `V18-01` 已交付“今日工作台”：

- 失败任务、待审核线索、异常 Worker、运行中 Skill Run 的注意力卡片。
- 线索队列、证据摘要、建议下一步、运行进度和系统心跳。
- 后端不可达时的明确降级提示和无虚假数据的结构预览。
- 后续线索审核、任务中心、Campaign 中心和系统健康的稳定导航入口。

## 架构边界

- React 客户端只访问同源 `GET /api/operator/workbench`。
- NestJS BFF 使用服务端环境变量访问现有 FastAPI。
- FastAPI/PostgreSQL/Worker 继续承载核心业务与事实数据；妙搭不复制核心逻辑。
- `OPERATOR_API_TOKEN` 只存在于妙搭服务端，绝不返回浏览器。

## 环境变量

| Key | 说明 |
|---|---|
| `OPERATOR_API_BASE_URL` | 现有 FastAPI 的稳定公网根地址，不带尾部 `/` |
| `OPERATOR_API_TOKEN` | 与 FastAPI `OPS_TOKEN` 一致的服务端凭证 |

缺少变量或后端不可达时，页面进入降级态，但仍保留完整操作台结构以便验收设计。

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

`V18-01` 本地真实联调确认 FastAPI 与 NestJS 返回同一组业务数据；后端停止后 BFF 返回结构化 `503`，响应中不包含服务端 token。
