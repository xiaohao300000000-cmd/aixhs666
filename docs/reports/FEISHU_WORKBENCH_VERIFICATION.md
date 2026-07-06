# Feishu Workbench Verification

Date: 2026-07-06

## Target

- Base token: `RVtDb7nGkabAMbsDkA0cvxdOnld`
- Table ID: `tblRSEpG7v0bM0WD`
- Table name: `客户跟进表`
- Transport verified: `lark-cli` user identity

## Schema

The table was configured with these fields:

- `客户`
- `需求`
- `课程/考试`
- `意向程度`
- `为什么推荐`
- `下一步`
- `状态`
- `来源链接`
- `发现时间`
- `负责人`
- `备注`

## Commands

Schema and direct write verification used:

```bash
lark-cli base +table-update --base-token RVtDb7nGkabAMbsDkA0cvxdOnld --table-id tblRSEpG7v0bM0WD --name '客户跟进表' --as user
lark-cli base +field-update --base-token RVtDb7nGkabAMbsDkA0cvxdOnld --table-id tblRSEpG7v0bM0WD --field-id fldpqLaoht --json '{"name":"客户","type":"text"}' --as user --yes
lark-cli base +record-upsert --base-token RVtDb7nGkabAMbsDkA0cvxdOnld --table-id tblRSEpG7v0bM0WD --json '<validation fields>' --as user
```

Project sync used:

```bash
FEISHU_ENABLED=true \
FEISHU_SYNC_DRY_RUN=false \
FEISHU_BITABLE_TRANSPORT=lark_cli \
FEISHU_BITABLE_APP_TOKEN=RVtDb7nGkabAMbsDkA0cvxdOnld \
FEISHU_LEADS_TABLE_ID=tblRSEpG7v0bM0WD \
.venv/bin/python -m apps.cli --json feishu-sync
```

Result:

```json
{"feishu_sync": {"created": 3, "dry_run": 0, "failed": 0, "updated": 0}}
```

Running the same command again after local mappings had remote record IDs returned:

```json
{"feishu_sync": {"created": 0, "dry_run": 0, "failed": 0, "updated": 3}}
```

Feedback pull used:

```bash
FEISHU_ENABLED=true \
FEISHU_SYNC_DRY_RUN=false \
FEISHU_BITABLE_TRANSPORT=lark_cli \
FEISHU_BITABLE_APP_TOKEN=RVtDb7nGkabAMbsDkA0cvxdOnld \
FEISHU_LEADS_TABLE_ID=tblRSEpG7v0bM0WD \
.venv/bin/python -m apps.cli --json feishu-pull-feedback
```

Result:

```json
{"feishu_feedback": {"skipped": 6, "updated": 3}}
```

## Notes

- Open Platform app-token writes had previously failed with `91403 Forbidden`.
- `lark-cli` user identity has the required Base scopes and can write this table.
- Project sync now supports `FEISHU_BITABLE_TRANSPORT=lark_cli`.
- `feishu-pull-feedback` accepts CLI-shaped select values such as `["可跟进"]`.

## AI Screening Workbench

Existing crawled records were screened before writing to Base. The export keeps strict high-intent leads separate from broader review candidates and writes two related tables:

- Customer table: `AI筛选客户线索`, table ID `tblAHiwa7ip0IkxQ`
- Evidence table: `AI筛选证据明细`, table ID `tblWuVvYREtAPHGs`
- Bidirectional link: evidence field `关联客户线索` points to the customer table; customer field `关联证据明细` points back to evidence rows.
- Base URL: `https://my.feishu.cn/base/RVtDb7nGkabAMbsDkA0cvxdOnld`
- Review view: `待人工确认`, view ID `vewpP3G8Vp`
- Follow-up view: `已确认可跟进`, view ID `vew2VrUXAx`
- High-intent view: `高意向`, view ID `vewaFKp6eO`
- Ignored view: `已忽略`, view ID `vewroPd49h`
- Card review view: `待人工确认卡片`, view ID `vewdlqeDmH`

Export result from the current database:

```json
{
  "customer_total": 71,
  "customer_by_layer": {"高意向": 10, "待人工确认": 61},
  "evidence_total": 72,
  "evidence_by_layer": {"高意向": 10, "待人工确认": 62},
  "evidence_linked": 72
}
```

Verification:

```text
High-intent customer records: 10
Review customer records: 61
Evidence records: 72
Evidence links updated: 72
View counts: 待人工确认=61, 高意向=10, 已确认可跟进=0, 已忽略=0
.venv/bin/python -m pytest -q
245 passed, 2 skipped, 1 warning
```

Manual review uses the `状态` select field. Keep unreviewed candidates as `待确认`; change qualified candidates to `可跟进`; change rejected candidates to `已忽略`. The filtered views move records based on this status.

The strict AI screening export is implemented in `services/feishu_ai_workbench.py` and covered by `tests/test_feishu_ai_workbench.py`. The tests verify that resource-only comments, guide-style posts, out-of-scope exam noise, and generic price opinions are not imported as strict customer leads.

## System Control Panel

The Base now includes a human-triggered control table. It does not run automatically; the local command only checks once and exits.

- Table: `系统控制台`, table ID `tblpqsBvrDMWhaiW`
- Main view: `Grid View`, view ID `vewmXNa34q`
- Ready view: `准备执行`, view ID `vewwu7dpln`
- Completed view: `已经完成`, view ID `vewxelCCMG`
- Error view: `出错了`, view ID `vewWxrGtL3`
- URL: `https://my.feishu.cn/base/RVtDb7nGkabAMbsDkA0cvxdOnld?table=tblpqsBvrDMWhaiW`

User-facing fields avoid implementation terms:

- `指令名称`
- `我要做什么`
- `开始执行`
- `现在状态`
- `要找什么`
- `最多看多少条`
- `结果`
- `哪里出错了`
- `开始时间`
- `完成时间`
- `系统记录编号`

Execution command:

```bash
FEISHU_CONTROL_PANEL_BASE_TOKEN=RVtDb7nGkabAMbsDkA0cvxdOnld \
FEISHU_CONTROL_PANEL_TABLE_ID=tblpqsBvrDMWhaiW \
python -m apps.cli --json run-control-panel-once
```

Verification used the sample row `查看系统状态（示例）`. With `开始执行=否`, the command returned no work. After setting `开始执行=是，开始`, one command run completed one record and wrote:

```text
系统正常。现在有 163 篇内容、516 条评论、641 个用户。
```

## LLM Review Callback Acceptance

Date/time: 2026-07-07 02:41-02:50 CST

Scope: only the completed LLM screening review results were accepted through Feishu callback. No unattended mode or new acquisition module was added.

Public HTTPS endpoint:

```text
https://soft-trains-prove.loca.lt/feishu/callback/llm-review
```

Feishu Open Platform configuration:

- App: `cli_aac1e28d6a399bfc`
- Callback event: `card.action.trigger`
- Request URL: `https://soft-trains-prove.loca.lt/feishu/callback/llm-review`
- App version published: `1.0.1`
- Publish result visible in Feishu: `应用审批通过，已发布成功`

The first click attempt on older cards opened `该应用不存在` and did not post back to FastAPI. Root cause was that the card used the old action payload shape. The card builder was minimally changed to Feishu Card 2.0 with button callback `behaviors`, then the three pending cards were resent.

Resent review cards:

```text
id=2 message_id=om_x100b6b8b226fd0a0b3bb325753227a5
id=3 message_id=om_x100b6b8b22755ca4b15a8242fc9d1de
id=5 message_id=om_x100b6b8b221faca0b2adeec32f61761
```

Real click results:

```text
id=2 clicked 有效 -> human_review_status=valid, feishu_card_status=processed
id=3 clicked 无效 -> human_review_status=invalid, feishu_card_status=processed
id=5 clicked 暂时观察 -> human_review_status=watch, feishu_card_status=processed
callback_events=3
reviewer=ou_2e31580f74e91be75997d4f6ac1c7cea
```

The original Feishu cards were updated to `LLM 客户线索审核 - 已处理`; the processed cards no longer expose the three review buttons. The backend idempotency test also verifies that a repeated callback for the same screening result writes only one `feishu_llm_review_callback` event.

Failure-log check:

```text
POST /feishu/callback/llm-review with screening_result_id=999999
HTTP 400 {"detail":"screening result not found: 999999"}
server log: Feishu LLM review callback rejected: screening result not found: 999999
```

Verification commands:

```bash
.venv/bin/pytest tests/test_feishu_llm_review.py
```

Result:

```text
7 passed, 1 warning
```

Signature status:

```text
FEISHU_ENCRYPT_KEY_set=False
FEISHU_VERIFICATION_TOKEN_set=False
```

The route and tests support Feishu signature and verification-token checks when `FEISHU_ENCRYPT_KEY` and `FEISHU_VERIFICATION_TOKEN` are set. This real acceptance run did not enable those secrets in the running environment, so the live clicks validate the callback loop, database update, idempotency guard, card update, and failure logging, but not live signature enforcement.
