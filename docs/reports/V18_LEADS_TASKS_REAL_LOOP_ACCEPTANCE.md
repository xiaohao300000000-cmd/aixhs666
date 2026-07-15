# V18 线索审核与任务中心真实闭环验收

日期：2026-07-16

## 范围

- 妙搭 `/leads` 从占位页升级为真实审核工作台。
- 妙搭 `/tasks` 从占位页升级为真实 Skill Runtime 操作台。
- NestJS BFF 继续隐藏 `OPERATOR_API_TOKEN`。
- FastAPI Operator Gateway 继续保持最小公网暴露面。

## 自动化

- 后端：`531 passed, 7 skipped, 1 warning in 29.15s`。
- 妙搭：Jest `9 passed`。
- 妙搭：server/client TypeScript 检查通过。
- 妙搭：ESLint、Stylelint、完整 `npm run build` 通过。
- Python/TypeScript 差异检查通过。

## 真实线索写入

1. 从真实 PostgreSQL 队列读取 4 条待审核线索，首条为 `#151`，状态 `needs_enrichment`，意向分 85。
2. 通过真实 Operator API 将 `#151` 写为 `watch`，人工审核字段同步为 `watch`。
3. 按写入前快照恢复 Lead 与最新 Screening 的全部被改字段。
4. 恢复复查：Lead 状态重新为 `needs_enrichment`，未污染运营队列。

## 真实任务执行

- Run `#10`：创建草稿 → 预览 3 条 → 取消；事件数 4，用于验证取消链路。
- Run `#11`：Campaign `education_fuzhou_offline`，最近 30 天，仅内容，数量 1。
- Run `#11` 终态：`succeeded`，进度 1/1，事件覆盖 created、parameters_updated、previewed、queued、stage_started、candidate_screened、succeeded。
- 结果：处理 1，有效需求 0，高意向 0，待确认 0，飞书同步失败 0。
- 该模板不访问小红书，不发送评论，不发送私信。

## 常驻执行

- LaunchAgent：`com.aixhs.skill-run-worker`。
- 入口：`scripts/run_skill_run_worker.sh`。
- 安装：`scripts/install_skill_run_worker_launchd.sh`。
- Worker 仅领取 `skill_run_execute`，与采集/评论/私信 Worker 隔离。

## 公网安全

- `GET /health`：200。
- 未授权 `GET /operator/api/leads`：401。
- 授权 `GET /operator/api/leads`：200。
- 授权 `GET /operator/api/tasks`：200。
- `GET /api/leads`：404。
- `POST /feishu/callback/llm-review`：404。

## 发布

- 妙搭 Git 提交：`38501e4e777689c93d75e70bddec4ee7f0888566`。
- Release：`7662812324507454684`。
- 状态：`finished`。
- 线上入口：`https://tiho2o4ymck.feishuapp.com/app/app_17a4790srtt`。
- 可见范围：`Range`，要求飞书登录，指定用户包含“张兆尊”。

## 真人体验结论

- 工作台的待审核数量可以直接进入线索审核，不需要再去 Base 手工找记录。
- 审核时证据、AI 判断、评分、Campaign 版本与动作同屏，处理后自动进入下一条。
- 任务中心先预览候选范围，再确认执行；运行状态、失败原因、事件和结果在同一页面查看。
- 当前最大剩余产品缺口是单条重新分析、重复客户合并和飞书消息深链；它们已拆为 V18-02B，不影响现有主审核和任务执行闭环。
- 系统仍依赖本机 PostgreSQL、Gateway、Tailscale 和 Worker 在线；持续在线云托管仍是 V18-05 风险。
