# 子任务简报：TXX

## 任务名称

填写任务名称。

## 任务目标

说明本任务必须实现什么。

## 依赖

- 已完成任务：
- 必须存在的接口：
- 必须阅读的文档：

## 分支与工作区

- 分支：`task/TXX-short-name`
- Worktree：可选
- 子会话编号：`worker-TXX`

## 允许修改

- 列出允许修改的目录和文件。

## 禁止修改

- `TASKS.md`
- `PROJECT_DASHBOARD.md`
- `HANDOFF.md`
- `DECISIONS.md`
- `AGENTS.md`
- 其他未列入允许范围的模块

## 输入

列出已有代码、接口、测试数据和配置。

## 输出

列出必须创建或修改的文件。

## 验收条件

1. 条件一
2. 条件二
3. 条件三

## 测试命令

```bash
pytest ...
```

## 必须提交的报告

完成后创建：

```text
orchestration/reports/TXX.md
```

使用 `templates/SUBTASK_REPORT.md`。

## 停止条件

遇到下列情况立即停止并报告：

- 需要修改禁止文件
- 依赖不存在
- 需要重大架构变更
- 需要未经批准的新依赖
- 无法通过验收测试
