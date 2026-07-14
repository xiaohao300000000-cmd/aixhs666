# Feishu Card Callback Protocol Fix Design

## Goal

在不改变现有 HTTP 回调模式、请求地址和发卡应用的前提下，修复 V16 Card 2.0 真实点击的 `200671`，并使回调响应、签名和加密载荷符合飞书官方协议。

## Design

- 对原始请求先验签，再解析明文 JSON 或解密外层 `encrypt`。
- Card 2.0 动作统一兼容 `event.action.value.action` 和 `event.action.name`。
- 任务中心短事务持久化后立即返回 `toast + card(type=raw)`；DeepSeek 和完整 Skill 仍只由 Worker 执行。
- 其他共享卡片动作返回官方 toast，避免 HTTP 200 后因自定义响应体触发格式错误。
- 记录 event ID、action、类型和耗时，不记录 token、签名或加密正文。

## Acceptance

- 真实 Card 2.0 载荷路由到任务中心，不进入 LLM 审核。
- 明文与加密回调测试通过，错误签名拒绝。
- 本地和原公网地址均在 3 秒内返回 HTTP 200 与官方响应结构。
- 不访问小红书，不发送评论或私信。
