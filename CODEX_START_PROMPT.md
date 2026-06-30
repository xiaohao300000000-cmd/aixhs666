你是一名资深 Python 后端工程师、数据工程师和采集系统架构师。

这是单会话执行模式。如果要使用主控会话管理子会话，请改用 `MASTER_CODEX_PROMPT.md`。

你现在接手一个名为“AI 教育需求发现与获客效率系统”的 GitHub 仓库。

不要依赖当前聊天上下文。开始工作前，必须按顺序完整阅读：

1. README.md
2. docs/PRD.md
3. docs/ARCHITECTURE.md
4. docs/DATA_MODEL.md
5. docs/ORCHESTRATION.md
6. TASKS.md
7. PROJECT_DASHBOARD.md
8. DECISIONS.md
9. HANDOFF.md
10. AGENTS.md

必须遵守 AGENTS.md 中的全部规则。

本次只执行 TASKS.md 中的 T01：仓库骨架。

T01 目标：

- 建立 Python 3.12 项目
- FastAPI
- PostgreSQL
- SQLAlchemy 2.x
- Alembic
- pytest
- Docker Compose
- `.env.example`
- `/health` 接口
- 基础 README 运行说明
- 基础 CI 测试配置
- 合理的目录结构

约束：

- 不实现真实平台采集
- 不实现 T02 及后续任务
- 不引入 Redis、Kafka、Kubernetes
- 不把密钥写入仓库
- 代码必须有类型标注
- 健康检查和基础启动必须有测试
- 必须确保 `docker compose up` 的配置合理
- 必须保留现有项目文档，不得覆盖其内容

开始前先输出：

1. 你对 T01 的理解
2. 准备新增或修改的文件
3. 测试计划

完成后必须：

1. 运行测试
2. 报告测试结果
3. 把 TASKS.md 中 T01 改为 DONE
4. 更新 HANDOFF.md
5. 如有新技术决策，更新 DECISIONS.md
6. 停止，等待下一步指令

不得继续执行 T02。
