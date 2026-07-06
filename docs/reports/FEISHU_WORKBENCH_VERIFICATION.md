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

Existing crawled records were screened before writing to Base. The export keeps only `push` and `confirm` intent decisions and writes two related tables:

- Customer table: `AI筛选客户线索`, table ID `tblAHiwa7ip0IkxQ`
- Evidence table: `AI筛选证据明细`, table ID `tblWuVvYREtAPHGs`
- Bidirectional link: evidence field `关联客户线索` points to the customer table; customer field `关联证据明细` points back to evidence rows.
- Base URL: `https://my.feishu.cn/base/RVtDb7nGkabAMbsDkA0cvxdOnld`

Export result from the current database:

```json
{"customers": 10, "evidence": 10}
```

Verification:

```text
Customer records created: 10
Evidence records created: 10
Evidence links updated: 10
.venv/bin/python -m pytest -q
225 passed, 2 skipped, 1 warning
```

The AI screening export is implemented in `services/feishu_ai_workbench.py` and covered by `tests/test_feishu_ai_workbench.py`. The tests verify that resource-only comments, guide-style posts, out-of-scope exam noise, and generic price opinions are not imported as customer leads.
