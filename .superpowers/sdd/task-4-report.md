# Task 4 Report: Feishu Workbench Mapping and Idempotent Sync

## Status
DONE

## What changed
- Added `owner_name`, `operator_note`, and `last_feedback_at` to `Lead`.
- Added `FeishuBitableRecord` to `storage/models.py` with the required uniqueness and sync tracking fields.
- Added migration `alembic/versions/0008_feishu_bitable_sync.py` to create the new columns and table.
- Added `services/feishu_workbench.py` with:
  - `FeishuWorkbenchSyncResult`
  - `build_workbench_fields(row)`
  - `sync_workbench_rows(session, client, rows)`
- Extended `tests/test_feishu_bitable_sync.py` with:
  - human-readable field mapping coverage
  - idempotent dry-run sync coverage backed by SQLite

## Verification
- `./.venv/bin/python -m pytest tests/test_feishu_bitable_sync.py::test_workbench_fields_are_human_readable -q`
- `.venv/bin/python -m pytest tests/test_feishu_bitable_sync.py -q`
- `.venv/bin/alembic upgrade head`
- `.venv/bin/python -m pytest tests/test_feishu_bitable_sync.py tests/test_core_data_models.py -q`
- `.venv/bin/python -m pytest -q`

## Commit
- `a4ebc7e feat: sync leads to feishu workbench`

## Concerns
- None.

## Follow-up Fix
- Removed placeholder Feishu identifiers from Task 4 sync code and tests.
- Changed `sync_workbench_rows()` so credential-missing dry-runs return counts only and do not create `FeishuBitableRecord` rows.
- Added explicit no-network coverage for dry-run sync paths and kept mapping persistence only for real non-empty `app_token` / `table_id` values.

## Verification
- `.venv/bin/alembic upgrade head`
- `.venv/bin/python -m pytest tests/test_feishu_bitable_sync.py tests/test_core_data_models.py -q` -> `16 passed in 0.30s`
- `.venv/bin/python -m pytest -q` -> `210 passed, 2 skipped in 23.85s`
