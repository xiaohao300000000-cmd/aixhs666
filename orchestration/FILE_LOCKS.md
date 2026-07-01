# 文件锁登记表

> 由主控会话维护。派发子任务前必须检查。

| 任务 | Worker | 锁定路径 | 模式 | 开始时间 | 释放条件 |
|---|---|---|---|---|---|
| T07 | W1 | `apps/worker/**` | WRITE | 2026-07-02 00:41 CST | T07 ACCEPT、REJECT 或 BLOCK 后释放 |
| T07 | W1 | `collectors/**` | WRITE | 2026-07-02 00:41 CST | T07 ACCEPT、REJECT 或 BLOCK 后释放 |
| T07 | W1 | `storage/snapshots.py`; `storage/__init__.py` | WRITE | 2026-07-02 00:41 CST | T07 ACCEPT、REJECT 或 BLOCK 后释放 |
| T07 | W1 | `tests/test_xhs_search_collection.py`; `orchestration/reports/T07.md` | WRITE | 2026-07-02 00:41 CST | T07 ACCEPT、REJECT 或 BLOCK 后释放 |

模式：

- WRITE：其他任务不得修改
- MIGRATION：禁止其他数据库迁移并行
- INTERFACE：禁止其他任务修改同一公共接口
- READ_SHARED：允许其他任务只读
