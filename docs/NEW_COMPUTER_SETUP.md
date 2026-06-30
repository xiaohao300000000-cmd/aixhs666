# 新电脑开发环境部署指南

## 1. 推荐用途

新电脑作为：

- 主控 Codex 工作区
- Git 主仓库
- 多个 Git worktree
- Docker 本地开发环境
- Playwright 浏览器调试环境
- 子会话并行开发环境

OCI 继续负责后续长期运行服务，新电脑主要负责开发、测试和管理。

## 2. 基础软件

建议安装：

- Git
- Docker Desktop 或 OrbStack
- Python 3.12
- uv
- Node.js LTS
- Chrome
- VS Code 或 Cursor
- Codex CLI
- GitHub CLI

macOS 可使用 Homebrew 管理基础工具。

## 3. 推荐目录

```text
~/Projects/
├── education-demand-engine/
└── worktrees/
    ├── T01/
    ├── T02/
    ├── T04/
    └── ...
```

主仓库：

```text
~/Projects/education-demand-engine
```

子任务 worktree：

```text
~/Projects/worktrees/TXX
```

## 4. 首次初始化

```bash
git clone <repository-url>
cd education-demand-engine
cp .env.example .env
git checkout main
```

然后把项目启动包中的全部文档提交到仓库。

## 5. 主控会话启动

在主仓库根目录启动 Codex 主控会话。

使用：

```text
MASTER_CODEX_PROMPT.md
```

主控只负责：

- 任务选择
- 简报生成
- 分支和 worktree
- 验收
- 合并
- 项目状态更新

## 6. 子会话启动

每个子会话进入对应 worktree：

```bash
cd ~/Projects/worktrees/TXX
```

然后使用：

```text
WORKER_CODEX_PROMPT.md
```

并指定任务简报：

```text
orchestration/briefs/TXX.md
```

## 7. 电脑资源建议

### 24GB 内存机器

推荐：

- 1 个主控会话
- 2 个执行子会话
- 1 套 Docker 开发环境
- Chrome 调试窗口按需开启

稳定后可尝试 3 个执行子会话。

### 16GB 内存机器

推荐：

- 1 个主控会话
- 1–2 个执行子会话
- 避免多个 Playwright 浏览器同时运行
- Docker 服务按需启动

### 并发采集调试

真实浏览器采集调试时，不要同时让多个子会话启动大量 Chrome 实例。

代码编写可以并发，真实采集测试应串行或严格限流。

## 8. Git 合并流程

子会话完成后：

```bash
git status
git add .
git commit -m "feat(TXX): ..."
```

主控验收后：

```bash
git checkout main
git merge --no-ff task/TXX-short-name
```

合并后运行总测试。

通过后更新：

- TASKS.md
- PROJECT_DASHBOARD.md
- HANDOFF.md
- DECISIONS.md（如需要）

## 9. 新电脑第一天执行顺序

1. 安装基础软件
2. 克隆仓库
3. 验证 Git 和 GitHub 权限
4. 启动 Docker
5. 启动主控 Codex 会话
6. 执行 T01
7. 验收 T01
8. 创建 T02、T04 两个 worktree
9. 开启两个子会话
10. 主控开始管理并发

## 10. 备份

所有重要状态必须提交 GitHub。

不要把以下内容只留在本地或聊天里：

- 任务状态
- 架构决策
- 环境配置说明
- 失败原因
- 子任务报告
- 进度看板

本地电脑可以坏，聊天上下文可以失忆，Git 仓库至少还会老老实实保存人类留下的证据。

## 对话启动方式

- 项目经理对话：在新电脑上开启一次，后续持续管理项目
- 独立执行对话：每个任务都重新新开一个完全独立的对话
- 不从项目经理对话派生执行对话
- 执行对话只接收任务包，不接收项目经理的完整聊天历史
