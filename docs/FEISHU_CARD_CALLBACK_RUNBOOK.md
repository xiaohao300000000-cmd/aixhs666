# 飞书交互卡片回调部署与排障 Runbook

## 1. 文档目的

本文记录 V16 飞书任务中心 `card.action.trigger` 从配置、发卡、HTTP 回调到 PostgreSQL 持久化的真实成功方案。

适用范围：

- 飞书自建应用发送 Card 2.0 交互卡片。
- 用户点击按钮后，由飞书通过 HTTP 回调调用本项目。
- FastAPI 快速持久化 Skill Run，并立即返回飞书认可的卡片响应。
- 后续 DeepSeek、Campaign 判断和飞书同步由独立 Worker 执行。

本文不包含小红书采集、评论发送或私信发送。

## 2. 真实成功记录

最终真实验收时间：`2026-07-15 02:48 CST`。

成功证据：

- 飞书应用 ID：`cli_aac1e28d6a399bfc`。
- 应用名称：`🐽猪猪兽超进化！`。
- 在线版本：`1.0.2`。
- 回调方式：`webhook`。
- 回调地址：`https://three-emus-kick.loca.lt/feishu/callback/llm-review`。
- 已订阅回调：`card.action.trigger`。
- 飞书 P2P chat：`oc_db1d787a662278e05ce8a5c035a66ee0`。
- 成功卡片消息：`om_x100b6a5c096318a4b1ca479dccbd4b8`。
- 飞书服务器真实请求进入 FastAPI，两次访问日志均为 HTTP `200 OK`。
- 真实点击创建 PostgreSQL `Skill Run #8`。
- Run `#8` 状态：`draft`。
- Run `#8` Skill：`screen_historical_leads`。
- Run `#8` 的 `requested_by` 为真实操作人的飞书 `open_id`。
- Run `#8` 正确绑定上述 chat ID 和 message ID。

成功只证明“创建任务 → 参数表单”回调已打通；完整产品验收仍应继续执行预览、确认运行、Worker 进度和结果卡片。

## 3. 最终采用的架构

```text
飞书客户端
  → Card 2.0 按钮 behaviors.callback
  → 飞书开放平台 card.action.trigger
  → localtunnel HTTPS 公网入口
  → 127.0.0.1:8017 FastAPI
  → POST /feishu/callback/llm-review
  → PostgreSQL skill_runs / skill_run_events
  → toast + raw Card 2.0 响应
  → 独立 Worker 后续执行 Skill Run
```

关键边界：

- `lark-cli` 负责以应用身份发送卡片。
- 卡片点击不是由 `lark-cli` 本地监听处理，而是由飞书服务器调用 HTTP 回调。
- HTTP 回调只做校验、幂等、短事务持久化和即时卡片响应。
- DeepSeek 和完整 Skill 流程不得在回调请求中执行。
- PostgreSQL 是事实源，卡片只是交互投影。

## 4. 飞书应用配置

### 4.1 确认当前 lark-cli 应用

```bash
lark-cli auth status --json
lark-cli whoami --json
```

必须确认发卡 Profile/App ID 是：

```text
cli_aac1e28d6a399bfc
```

读取应用配置：

```bash
lark-cli api GET \
  /open-apis/application/v6/applications/cli_aac1e28d6a399bfc \
  --params '{"lang":"zh_cn"}' \
  --as bot \
  --json
```

需要看到：

```json
{
  "callback_info": {
    "callback_type": "webhook",
    "request_url": "https://three-emus-kick.loca.lt/feishu/callback/llm-review",
    "subscribed_callbacks": [
      "card.action.trigger"
    ]
  }
}
```

### 4.2 开发者后台配置

在同一个 App ID 对应的开发者后台中：

1. 打开“事件与回调”。
2. 进入“回调配置”。
3. 订阅方式选择“将回调发送至开发者服务器”。
4. 请求地址填写：

```text
https://three-emus-kick.loca.lt/feishu/callback/llm-review
```

5. 添加“卡片回传交互 / `card.action.trigger`”。
6. 保存配置。
7. 创建并发布新的应用版本。

本次发布版本为 `1.0.2`。只保存回调配置但不发布新版本，不能作为线上生效的验收证据。

不要为了这个闭环：

- 切换成长连接。
- 更换其他机器人或应用。
- 修改为旧的随机回调域名。
- 把群成员名称误认为回调应用名称。

## 5. 本地服务启动顺序

### 5.1 启动 FastAPI

在仓库根目录执行：

```bash
.venv/bin/python -m uvicorn apps.api.main:app \
  --host 127.0.0.1 \
  --port 8017
```

本地健康检查：

```bash
curl -i http://127.0.0.1:8017/health
```

### 5.2 启动 localtunnel

另开一个持续运行的终端：

```bash
npx -y localtunnel \
  --port 8017 \
  --subdomain three-emus-kick
```

必须看到：

```text
your url is: https://three-emus-kick.loca.lt
```

本次最终成功的关键操作是：**保持同一个 URL，不修改飞书后台地址，只停止并重新启动 localtunnel 进程。**

旧 localtunnel 会话虽然能被本机 `curl` 访问，但飞书真实点击没有到达 FastAPI。重新建立同一 subdomain 的隧道连接后，下一张新卡的真实点击立即到达 API 并返回 HTTP 200。

因此：

- 本机公网探针成功不等于飞书服务器一定能够通过当前隧道会话访问。
- 遇到飞书点击无 API 日志时，优先重启隧道进程，而不是改业务代码。
- 重启时保持同一个 `--subdomain three-emus-kick`，避免反复修改开发者后台。

## 6. 发送任务中心卡片

确保 FastAPI 和 localtunnel 已经运行，然后执行：

```bash
FEISHU_LARK_CLI_AS=bot \
.venv/bin/python -m apps.cli --json \
  feishu-task-center \
  --chat-id oc_db1d787a662278e05ce8a5c035a66ee0
```

返回示例：

```json
{
  "task_center": {
    "chat_id": "oc_db1d787a662278e05ce8a5c035a66ee0",
    "message_id": "om_xxx"
  }
}
```

每次验收只点击最新发送的卡片，记录 message ID，避免同时存在多张旧卡时误判。

## 7. Card 2.0 必须使用的字段

普通按钮：

```json
{
  "tag": "button",
  "name": "skill_create_screen_historical_leads",
  "behaviors": [
    {
      "type": "callback",
      "value": {
        "action": "skill_create_screen_historical_leads"
      }
    }
  ]
}
```

表单提交按钮：

```json
{
  "tag": "button",
  "name": "skill_preview_8",
  "form_action_type": "submit"
}
```

真实普通按钮回调的动作位于：

```text
event.action.value.action
```

表单提交仍需兼容：

```text
event.action.name
event.action.form_value
```

代码必须同时兼容两种动作结构。

## 8. HTTP 回调响应合同

任务中心需要立即更新当前卡片时，返回：

```json
{
  "toast": {
    "type": "success",
    "content": "任务已受理"
  },
  "card": {
    "type": "raw",
    "data": {
      "schema": "2.0"
    }
  }
}
```

不得返回：

```json
{
  "code": 0,
  "msg": "accepted"
}
```

后者是项目自定义 API 风格，不是飞书卡片回调响应合同。

回调必须在 3 秒内完成。DeepSeek、Campaign 执行和完整飞书 Base 同步必须留给 Worker。

## 9. 签名与加密

如果以后在飞书后台启用加密策略：

```text
signature = SHA256(timestamp + nonce + encrypt_key + raw_body).hexdigest()
```

外层存在：

```json
{"encrypt":"..."}
```

时，需要：

1. Base64 解码。
2. 前 16 字节作为 AES-CBC IV。
3. `SHA256(encrypt_key)` 的二进制摘要作为 AES key。
4. 解密剩余密文。
5. 校验并移除 PKCS#7 padding。
6. 再解析内部 JSON。

当前真实成功环境中：

- `FEISHU_ENCRYPT_KEY` 未设置。
- `FEISHU_VERIFICATION_TOKEN` 未设置。
- 飞书应用查询结果中没有启用加密策略。

代码仍保留启用加密后的兼容能力。

## 10. 验收步骤

### 10.1 公网协议探针

使用与真实按钮一致的动作结构：

```bash
curl -sS \
  -H 'content-type: application/json' \
  --data '{
    "schema":"2.0",
    "header":{"event_id":"manual-probe"},
    "event":{
      "operator":{"open_id":"ou-probe"},
      "context":{},
      "action":{
        "value":{
          "action":"skill_create_screen_historical_leads"
        }
      }
    }
  }' \
  https://three-emus-kick.loca.lt/feishu/callback/llm-review
```

预期：

- HTTP `200`。
- 返回 `toast`。
- `card.type=raw`。
- `card.data.schema=2.0`。

### 10.2 真实点击

1. 记录新卡 message ID。
2. 点击最新卡的“创建任务”。
3. FastAPI 日志出现来自飞书服务器的 `POST /feishu/callback/llm-review`。
4. HTTP 状态为 `200 OK`。
5. 原卡片替换为参数填写卡。
6. PostgreSQL 新增一个 `skill_runs` 记录。
7. 记录中的 `feishu_chat_id` 和 `feishu_message_id` 与点击卡片一致。

查询最近运行：

```bash
.venv/bin/python - <<'PY'
from runtime_env import load_dotenv
load_dotenv()
from sqlalchemy import select
from storage.database import SessionLocal
from storage.models import SkillRun

with SessionLocal() as session:
    run = session.scalar(select(SkillRun).order_by(SkillRun.id.desc()).limit(1))
    print(run.id, run.status, run.skill_key, run.feishu_chat_id, run.feishu_message_id)
PY
```

## 11. `200671` 排障矩阵

### 11.1 API 有请求并返回 400/401/500

说明公网链路已通，检查：

- 是否只读取了 `event.action.name`，漏掉 `event.action.value.action`。
- verification token 是否一致。
- 是否启用了加密但服务端没有解密。
- 数据库事务或业务校验是否抛异常。
- 回调是否误路由到其他业务处理器。

本次曾经出现的直接错误是：

```text
skill_create_screen_historical_leads
→ 被误送入 LLM review handler
→ HTTP 400
→ 飞书显示 200671
```

### 11.2 API 完全没有请求

说明业务代码没有机会执行，检查顺序：

1. 卡片是否由配置回调的同一个 App ID 发出。
2. 是否订阅 `card.action.trigger`。
3. 是否已创建并发布新应用版本。
4. 是否点击最新卡片。
5. localtunnel 进程是否仍在运行。
6. 重启同一个 localtunnel subdomain。
7. 重启后重新发送新卡再点击。

本次最终成功属于这一类：重启同一个 localtunnel 连接后恢复。

### 11.3 HTTP 200 但飞书仍报响应格式错误

检查是否返回飞书支持的：

- `{}`
- `toast`
- `toast + card(type=raw)`

不要返回项目内部的 `code/msg/type/run_id` JSON。

## 12. 运行维护要求

当前方案仍是开发/验收入口，不是长期生产入口：

- FastAPI 进程停止，回调立即不可用。
- localtunnel 进程停止，公网入口立即不可用。
- localtunnel 会话可能出现“本机 curl 正常、飞书服务器无法投递”的状态。
- 电脑休眠、网络切换和终端关闭都会影响回调。

短期操作要求：

- 保持 FastAPI 和 localtunnel 两个进程持续运行。
- 每次电脑或网络恢复后先重启两个进程并跑公网探针。
- 验收只发送一张新卡，记录 message ID。
- 先看 API 是否收到请求，再决定排查业务代码还是公网入口。

长期建议：

- 使用固定域名和稳定托管的 HTTPS 服务替换临时隧道。
- 使用进程守护工具运行 API 和 Worker。
- 增加外部健康检查和回调访问日志。
- 切换正式入口时一次性修改飞书回调地址并发布应用版本，禁止在多个临时域名之间反复切换。

## 13. 禁止事项

- 不因单次 `200671` 直接切成长连接。
- 不在没有证据时更换机器人或应用。
- 不把飞书群成员名称当作发卡应用身份。
- 不用本机构造的 `curl` 代替真实飞书点击验收。
- 不在回调请求中运行 DeepSeek。
- 不在本 Runbook 验收中访问小红书。
- 不运行 live selector probe。
- 不发送真实评论或私信。
