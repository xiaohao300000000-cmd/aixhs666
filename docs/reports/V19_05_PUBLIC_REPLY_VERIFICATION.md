# V19-05 公开回复两步确认验证报告

## 结论

V19-05 自动化与真实 PostgreSQL 非破坏迁移验证完成。系统现在从“推进合格评论客户”开始持久排队生成草稿；草稿编辑、版本确认、最终发送排队和结果恢复均由 PostgreSQL 命令事实控制。第一步“确认话术”不会创建发送任务；第二步再次展示公开渠道、目标、版本和全文，并要求 `confirmed=true` 才创建唯一 `comment_reply_send`。只有 Worker 能构造小红书 sender。

本次没有真实发送小红书、没有写真实 Base、没有创建真实飞书卡，也没有运行 selector probe。原因是没有主控转交的具体目标、最终文本、账号/CDP 就绪证据、只读 probe 条件和用户逐条最终批准；系统停在正确的真实发送门槛。

## RED / GREEN 证据

| 批次 | RED（实现前可复现） | GREEN |
|---|---|---|
| 模型与迁移 | `LeadCommentReply` 无 `draft_revision/approved_revision/queued_at`，无命令幂等表 | `0021_contact_reply_two_step` 与模型测试通过；旧 `approved_text` 回填版本 |
| 版本化命令 | 编辑不使旧确认失效，确认与发送未分离 | edit/approve/send/result/recovery 命令测试通过，同键同请求重放、同键异请求拒绝 |
| 草稿准备 | 推进客户后没有持久 `comment_reply_prepare` | 推进事务只建任务；生成器与飞书只在 Worker 中调用 |
| 飞书两步 | 单按钮会进入发送路径 | 第一步只 `approved`；第二步才 `queued`；回调不构造 sender |
| Operator API | 无联系尝试读写合同 | GET/prepare/edit/approve/send/confirm-not-sent 覆盖 404/409/422/503 |
| 妙搭 | 客户页只显示 V19-05 占位 | BFF、类型、纯视图模型、持久草稿编辑、两步确认和 unknown 恢复通过 |
| 审计返工：结果事实 | `_execute_send_claim` 直接更新状态，客户阶段/跟进/时间线缺失 | sent/failed/result_unknown 统一调用 `record_contact_result`；平台事实事务先提交 |
| 审计返工：重复审批 | 同 revision 新幂等键触发时间线唯一约束 `IntegrityError` | 相同 revision/文本稳定返回，不新增第二个审批事件 |
| 审计返工：fencing | Worker payload revision 未参与领取/完成条件 | `attempt_count + draft_revision` 同时参与 claim/result fencing；陈旧 payload 不调用 sender |
| 投影失败 | 仅状态表测试可假绿 | Base 投影抛错后核心 sent、Lead、Followup、Timeline 仍存在；任务不再领取，sender 只调用一次 |

主要 RED 提交：`2e8c1ad`、`07ce8f2`、`92f69cb`、`0c0a336`、`e39ceb7`、`a4ce6c7`、`fb90466`、`a152f7c`。对应 GREEN 提交：`1f8cded`、`9acba49`、`b476bb0`、`417f115`、`e5d12ef`、`b76f291`、`cefcca3`、`31f2215`。

## 自动化结果

```text
# 开工基线
/Users/xiaohao30000/aixhs666/.venv/bin/pytest -q
594 passed, 7 skipped, 1 warning

cd miaoda-console && npm test -- --runInBand
40 passed（首次因 worktree 无 node_modules 报 jest not found；npm ci 后通过）

# 简报指定 Python 套件
/Users/xiaohao30000/aixhs666/.venv/bin/pytest tests/test_contact_commands.py tests/test_comment_reply_generation.py tests/test_comment_reply_models.py tests/test_comment_reply_workflow.py tests/test_comment_reply_followup_integration.py tests/test_feishu_transport_callbacks.py tests/test_worker_runtime.py tests/test_customer_crm_sync.py tests/test_customer_crm_operator.py tests/test_operator_api.py tests/test_operator_gateway.py tests/test_lead_comment_reply_migration.py -q
188 passed, 1 skipped, 1 warning

# 全量 Python
/Users/xiaohao30000/aixhs666/.venv/bin/pytest -q
612 passed, 7 skipped, 1 warning

# 妙搭
cd miaoda-console && npm test -- --runInBand
48 passed
npm run type:check
server/client passed
npm run lint
eslint/typecheck/stylelint passed
npm run build
production build completed

git diff --check
passed
```

既有 warning 为 Starlette `httpx` 兼容弃用提醒和 ts-jest 配置提示；没有新增依赖或因 warning 跳过验证。

## 真实 PostgreSQL 与迁移证据

真实库升级前只读快照：

```text
revision=0020_review_queue_idempotency
lead_comment_replies=0
qualified_leads=12
comment_screenings=50
```

使用真实 `.env` 通过 Alembic Python API执行等价的 `alembic upgrade head`，只修改 schema：

```text
Running upgrade 0020_review_queue_idempotency -> 0021_contact_reply_two_step
revision=0021_contact_reply_two_step
lead_comment_replies=0
contact_command_operations=0
reply_columns=3
approved_revision_backfill_mismatches=0
```

真实基线确实为 0 条回复，因此不能伪造“真实旧回复保留”。另在同一 PostgreSQL 实例创建一次性隔离数据库，升级到 0020 后插入一条无真实目标的迁移夹具，再执行升级、降级一版、重新升级，最后删除隔离数据库：

```text
after_upgrade:   draft='legacy draft', approved='legacy approved', draft_revision=1, approved_revision=1, status=approved_to_send
after_downgrade: draft='legacy draft', approved='legacy approved', status=approved_to_send
after_reupgrade: draft='legacy draft', approved='legacy approved', draft_revision=1, approved_revision=1, status=approved_to_send
```

这证明既有回复文本、审批文本和状态在升级/降级/再升级中保留，且旧审批版本被安全回填。隔离数据库已删除。

## 状态、安全与外部写入边界

- 规范状态：`awaiting_approval → approved → queued → sending → sent|failed|result_unknown`；`cancelled` 为终态。
- 编辑递增 `draft_revision`，旧 `approved_revision` 保留审计但不再可发送。
- `result_unknown` 没有普通重试；必须填写人工核验原因并显式确认平台未发送。
- 同一发送任务 payload 固定 revision；领取和结果均校验 revision 与 attempt。
- 平台结果、Lead 客户阶段、`CustomerFollowupRecord` 和 `CustomerTimelineEvent` 同事务提交；Base/飞书投影在后。
- 妙搭只访问同源 BFF；Python 状态机没有复制到 TypeScript。
- 私信明确显示“尚未接入”，未实现 V19-06 调度或回复检查。
- 未访问 `/Users/xiaohao30000/aixhs666-console`，未推送、合并、发布或修改线上环境。

## 真实发送准备状态

| 门槛 | 状态 |
|---|---|
| 主控点名的受控目标 | 未提供 |
| 最终逐字文本 | 未提供 |
| 指定发送账号与远程 CDP 就绪 | 未提供 |
| 不填写/不提交的 selector probe | 未运行（缺少目标与就绪条件） |
| 用户对该目标和文本逐条最终批准 | 未提供 |
| 真实发送 | 未执行 |

## 已知风险

- 真实库目前仍为 0 条 `lead_comment_replies`；“从无草稿到有草稿”已由持久 prepare 任务、Worker 和模拟外部客户端覆盖，但真实生成/建卡必须留给主控在配置与授权齐备后验收。
- Base/飞书真实投影未写入，本报告只证明事务顺序、失败隔离和自动化合同。
- 保留 legacy 同步回调/CLI 兼容路径；正式 FastAPI 飞书回调已使用两步 enqueue 命令路径。
- 真实发送前仍必须完成专用目标 selector probe，任何唯一选择器不满足都应停止。

