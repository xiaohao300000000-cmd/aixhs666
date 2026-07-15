# 当前交接状态

## 当前阶段

2026-07-09 当前主线已经从“本地看板/采集框架”推进到“DeepSeek 筛选 + Campaign 资格判断 + 飞书人工审核/话术审批工作台”。当前正式分支为 `main`，已推送到 GitHub：

```text
https://github.com/xiaohao300000000-cmd/aixhs666/tree/main
```

最近关键提交：

```text
f4e24c9 fix: defer outreach sending after approval
bab7d35 feat: allow xhs browser engine selection
4d3be93 feat: add feishu-approved outreach sending
d54f793 feat: harden xhs location evidence workflow
8abcfc6 fix: map mediacrawler public ip regions
8623c66 feat: add feishu system control panel
9cbd6d0 docs: record feishu manual review views
60c04f6 feat: export ai-screened leads to feishu base
081e214 feat: support lark cli feishu workbench sync
```

最新完整测试：

```text
.venv/bin/pytest -q
305 passed, 4 skipped, 1 warning
```

GitHub 更新规则已调整：后续默认在 `main` 上提交和推送，除非明确需要新功能分支。当前工作区只允许保留本地未跟踪笔记，不得把密钥、cookie、Webhook、数据库密码或完整用户隐私数据提交到仓库。

当前真实飞书 Base：

```text
Base token: RVtDb7nGkabAMbsDkA0cvxdOnld
Base URL: https://my.feishu.cn/base/RVtDb7nGkabAMbsDkA0cvxdOnld
```

已创建并验证的飞书表：

| 表 | Table ID | 用途 |
|---|---|---|
| `客户跟进表` | `tblRSEpG7v0bM0WD` | 旧的 lead 同步/反馈表 |
| `AI筛选客户线索` | `tblAHiwa7ip0IkxQ` | 客户汇总、人类审核、状态确认 |
| `AI筛选证据明细` | `tblWuVvYREtAPHGs` | 原始抓取文本、AI 判断、推荐原因 |
| `系统控制台` | `tblpqsBvrDMWhaiW` | 人工发指令让系统执行一次 |

当前飞书 AI 筛选结果：

```json
{
  "customer_total": 71,
  "customer_by_layer": {"高意向": 10, "待人工确认": 61},
  "evidence_total": 72,
  "evidence_linked": 72
}
```

重要视图：

| 视图 | URL |
|---|---|
| 待人工确认卡片 | `https://my.feishu.cn/base/RVtDb7nGkabAMbsDkA0cvxdOnld?table=tblAHiwa7ip0IkxQ&view=vewdlqeDmH` |
| 待人工确认表格 | `https://my.feishu.cn/base/RVtDb7nGkabAMbsDkA0cvxdOnld?table=tblAHiwa7ip0IkxQ&view=vewpP3G8Vp` |
| 高意向 | `https://my.feishu.cn/base/RVtDb7nGkabAMbsDkA0cvxdOnld?table=tblAHiwa7ip0IkxQ&view=vewaFKp6eO` |
| 已确认可跟进 | `https://my.feishu.cn/base/RVtDb7nGkabAMbsDkA0cvxdOnld?table=tblAHiwa7ip0IkxQ&view=vew2VrUXAx` |
| 已忽略 | `https://my.feishu.cn/base/RVtDb7nGkabAMbsDkA0cvxdOnld?table=tblAHiwa7ip0IkxQ&view=vewroPd49h` |
| 系统控制台 | `https://my.feishu.cn/base/RVtDb7nGkabAMbsDkA0cvxdOnld?table=tblpqsBvrDMWhaiW` |

当前筛选链路包含规则初筛、DeepSeek 主筛选和 Campaign 资格判断。旧的飞书 Base 工作台仍保留规则型 AI 结果；`lead_screening_results` 是当前 LLM/审核/资格判断/发送编排的主记录。

## 当前目标

当前目标是把本地 `/leads` 和飞书固化成“普通人能用的获客工作台”：

1. 人在 `AI筛选客户线索` 里审核候选客户。
2. 看 `需求摘要` 和 `关联证据明细`，把 `状态` 改成 `可跟进` 或 `已忽略`。
3. 人在 `系统控制台` 里发指令，系统只在本机执行一次，不自动后台运行。
4. 对 `有效` 线索生成跟进话术审批卡；人工在飞书里确认话术。
5. 本地 `/leads` 用“立即处理 / 今日内处理 / 可观察 / 信息不足 / 过期低优先级”承接线索判断，避免普通用户进入 `/ops`。
6. 后续需要补：把 AI 筛选同步挂入系统控制台或 worker、把卡片视图进一步优化为“需求摘要为主标题”的审核表、恢复可控的小红书真实发送。

代码侧已具备 MediaCrawler 主采集器、Worker、数据库并发/幂等修复、飞书 lark-cli transport、飞书 Base 写入、运行诊断、`/ops` 控制台、Pipeline Runner、`/leads` 获客页面、AI 筛选导出、飞书系统控制台。

2026-07-06 已新增“规则辅助 + LLM 主筛选”手动流程：`python -m apps.cli --json leads-llm-screen` 会读取数据库帖子和评论，默认上下文包含帖子标题、正文、当前评论、父评论，把 LLM 的是否有价值、需求类型、意向强度、判断证据、置信度写入 `lead_screening_results`，并将有价值或不确定结果写入 `leads` / `lead_evidence`。不确定结果使用 `needs_review`。

2026-07-06 已新增飞书 LLM 审核闭环：`python -m apps.cli --json feishu-send-llm-reviews --chat-id <oc_xxx> --limit 1` 会把 `lead_screening_results.review_status=needs_review` 的结果发送为飞书交互卡片，保存 `feishu_message_id` 和 `feishu_chat_id`；`POST /feishu/callback/llm-review` 会在配置 `FEISHU_ENCRYPT_KEY` / `FEISHU_VERIFICATION_TOKEN` 后校验飞书签名和 token，幂等处理按钮点击，更新 `human_review_status`，并用回调 token 把原卡片更新为“已处理”。

2026-07-07 已完成真实飞书回调验收：公网地址 `https://soft-trains-prove.loca.lt/feishu/callback/llm-review`，飞书应用版本 `1.0.1` 已发布，真实点击 `id=2 有效`、`id=3 无效`、`id=5 暂时观察` 后数据库分别写入 `valid`、`invalid`、`watch`，三张原卡片均更新为“已处理”，`feishu_llm_review_callback` 事件数为 3。失败请求 `screening_result_id=999999` 会在日志输出具体原因。当前真实运行环境没有设置 `FEISHU_ENCRYPT_KEY` / `FEISHU_VERIFICATION_TOKEN`，所以这次 live click 未验证签名密钥生效；测试已覆盖启用密钥时的验签路径。详细记录见 `docs/reports/FEISHU_WORKBENCH_VERIFICATION.md`。

2026-07-07 已新增最小统一流程编排，不新建业务表，复用 `lead_screening_results` 作为每条帖子/评论的流程记录。新增状态 `pending_llm -> screening -> llm_done -> pending_feishu -> sending -> sent -> reviewed`，并记录 `attempt_count` / `last_error`。推荐入口是 `python -m apps.cli --json lead-flow-once --source comment --limit 1 --chat-id <oc_xxx>`：每次只推进当前应该做的一步，不做无人值守调度；LLM 先领取为 `screening`，完成后只写 `llm_done`，飞书发送先把 `pending_feishu` 领取为 `sending`，普通发送失败恢复为 `pending_feishu`，不确定发送结果写为 `send_uncertain`，回调写 `reviewed`。`lead-flow-once` 的 `limit` 表示实际 LLM 处理数量，已有且非 `pending_llm` 的记录不占用 limit。`attempt_count` 只在真正领取飞书发送时增加。覆盖测试为 `tests/test_lead_screening_flow.py`、`tests/test_feishu_llm_review.py`、`tests/test_postgres_task_claiming.py` 和 `tests/test_ops_console.py`。真实库验收使用 `comments.id=1`，生成 `lead_screening_results.id=8`，状态流转为 `llm_done -> pending_feishu -> sent -> reviewed`，最终 `human_review_status=watch`，重复回调事件数保持 1。已知风险：当前只通过领取态 + PostgreSQL `FOR UPDATE SKIP LOCKED` 避免并发重复领取；飞书发送成功但数据库提交前进程崩溃时，仍需人工核对。

2026-07-07 已修复统一流程编排的可靠性风险：`lead-flow-once --limit 1` 不再让已处理记录占用实际处理名额；LLM 和飞书发送在 PostgreSQL 下使用领取态和 `FOR UPDATE SKIP LOCKED`；`/ops/api/lead-screening/diagnostics` 可只读查看 stale `sending`、长期 `pending_llm`、高 `attempt_count` 和 `send_uncertain`；`POST /ops/api/lead-screening/{id}/recover` 可在人工确认后恢复，并写入 `lead_screening_manual_recovery` 事件。相关测试和完整测试当时通过，结果为 `255 passed, 4 skipped, 1 warning`。当前最新测试结果见 2026-07-09 小节。

2026-07-07 已完成真实小批量验收：使用本机 PostgreSQL 真实评论和 DeepSeek 测试 key 跑 `leads-llm-screen --source comment --limit 20`，实际尝试 20 条（跳过/过滤不占 limit），18 条成功、2 条 LLM 内容非 JSON 失败；随后只推进 `needs_review` 到 `pending_feishu`，并通过 `lark-cli` 用户态向真实飞书群发送 3 张审核卡片。发送行 `id=11,15,16` 均写入 `sent`、唯一 `feishu_message_id`、`attempt_count=1`，无重复领取或异常发送态。失败重试后剩 1 条 `pending_llm`，错误为 `LLM returned invalid JSON content: ''`，属于带错误信息的可重试状态。`lead-flow-once` JSON 输出现在包含 `workflow_counts` 和 `review_counts`，覆盖 `pending_llm`、`llm_done`、`pending_feishu`、`sending`、`sent`、`reviewed`、`failed` 等统计。

2026-07-07 已新增可配置线索资格层：`platform_config/` 定义 `CampaignConfig`、`QualificationPolicy`、`LocationPolicy`、位置证据和可解释资格结果；新增三份配置 `education_fuzhou_offline`、`ielts_nationwide_online`、`automotive_xiamen_local`。成功的 LLM 筛选会在保持原有 `review_status` 和工作流状态不变的前提下，读取默认教育 Campaign 并写入独立 `qualification_*` 字段；`services/qualification.py` 也可在不重新调用 DeepSeek、不发送飞书的情况下，对已保存 `lead_screening_results` 做离线资格判断。IP/地区审计见 `docs/QUALIFICATION_ARCHITECTURE_AUDIT.md`：当前主库 `public_profiles.region_text=0/641`、`contents.region_text=0/163`，历史评论此前没有 `region_text` 字段；本次新增可空 `comments.region_text` 和迁移 `0013_comment_region_text`，未来适配器提供公开 IP 属地时可结构化保存，历史空值不会被当作外地。离线验证结果已生成到 `.runtime/qualification-validation-result.json`，只含聚合计数不含真实评论全文或个人信息；福州线下教育配置结果为 `total_records=28, qualified=0, rejected=12, needs_review=16, location_unknown=27, location_not_matched=1`，全国线上雅思配置结果为 `total_records=28, qualified=5, rejected=12, needs_review=11, location_not_required=28`。

2026-07-09 已完成当前主线整理和发送链路降风险：`feat/v15-agent-neutral-runtime` 已快进合并到 `main` 并推送；CLI/API 入口支持加载本地 `.env`，测试进程默认跳过本机 `.env` 避免环境污染；飞书跟进话术审批卡的“发送”按钮现在只审批入库为 `approved_to_send`，不再在飞书回调线程里直接打开小红书发送。真实小红书发送被隔离到 `send_approved_outreach()`，后续应由独立 worker 或人工触发入口处理。当前小红书私信真实发送因本机浏览器/网络环境无法稳定打开小红书页面而搁置，用户明确要求不要改 Clash；不要为了完成发送而恢复回调内直接发送或修改系统代理配置。

2026-07-09 已新增正式飞书 AI 筛选工作台增量同步命令：`python -m apps.cli --json feishu-ai-review-sync`。该命令读取 `lead_screening_results` 中 DeepSeek 已产出的 `accepted` / `needs_review`，增量写入 `AI筛选客户线索` 和 `AI筛选证据明细` 两张飞书表；复用 `feishu_bitable_records` 保存映射，重复执行会更新原记录，不重复创建。默认表 ID 为 `tblAHiwa7ip0IkxQ` 和 `tblWuVvYREtAPHGs`，可用 `FEISHU_AI_REVIEW_CUSTOMER_TABLE_ID` / `FEISHU_AI_REVIEW_EVIDENCE_TABLE_ID` 覆盖。为兼容现有 Base 字段，DeepSeek、Campaign 和地区信息写入现有字段，不要求先新增字段。

2026-07-09 已把本地 `/leads` 从“线索列表”升级为“客户判断工作台”：API 返回业务摘要、为什么推荐、来源角色、证据上下文、新鲜度、SLA 建议、优先级桶和人工判断动作；页面按 `新鲜度 + 意向 + 可行动性` 分为 `立即处理`、`今日内处理`、`可观察`、`信息不足`、`过期/低优先级`，支持 `有效`、`无效`、`观察`、`信息不足`、`重复`、`已联系` 六类人工判断。`/api/leads` 会先按业务优先级排序再分页，避免过期高分线索挤掉真正该处理的线索。

2026-07-09 已优化飞书 AI 筛选同步的字段顺序：客户表优先写 `需求摘要`、`意向程度`、`下一步`、`状态`、`证据数量`、`为什么推荐`，证据表优先写 `证据标题`、`抓取原文`、`证据类型`、`AI判断`、`置信度`、`为什么推荐`；`客户`、平台 ID、内容 ID、评论 ID 等技术字段后移，便于普通运营先看业务判断。

2026-07-09 已把 `/ops` 明确降级为管理员控制台：页面文案提示普通运营使用 `/leads` 或飞书表，采集、恢复、重试、创建任务等危险操作增加显式风险提示和确认。普通运营不应直接使用 `/ops` 做日常审核。

2026-07-09 已接通一台 Tailscale Windows 主机作为远端浏览器环境：主机地址 `100.124.24.8`，SSH 用户 `10579`，本机使用专用 key `~/.ssh/aixhs_100_124_24_8` 可登录。远端通过计划任务 `AIXHS Chrome CDP` 在交互式用户会话中启动 Chrome CDP，本机已验证 Playwright 可通过 `http://100.124.24.8:19223` attach 并打开 `https://www.xiaohongshu.com/explore`，标题为“小红书 - 你的生活兴趣社区”。本机 `.env` 已设置 `MEDIACRAWLER_CDP_CONNECT_EXISTING=true`、`MEDIACRAWLER_CDP_HOST=100.124.24.8`、`MEDIACRAWLER_CDP_DEBUG_PORT=19223`。远端 `19223` 是用户态 relay 到 Chrome 本机 `127.0.0.1:9222`，防火墙只允许本机 Tailscale 地址访问；不要把 CDP 端口开放到公网。

本机普通用户入口：

```text
~/Desktop/打开AIXHS看板.command
```

双击后会运行 `scripts/open_dashboard.command`，默认使用：

```text
WORKER_ADAPTER=mediacrawler
OPS_TOKEN=secret
```

该脚本会检查 `third_party/MediaCrawler/.venv`，缺失时自动创建并安装依赖；未检测到小红书持久登录态时，会启动 `python -m scripts.mediacrawler_login` 让用户扫码登录。扫码完成后需要在终端按回车，脚本会继续启动 API 服务并打开：

```text
http://127.0.0.1:8000/ops
```

产品主页面：

```text
http://127.0.0.1:8000/leads
```

历史数据回填潜在客户：

```bash
python -m apps.cli --json leads-backfill
```

飞书系统控制台执行一次：

```bash
FEISHU_CONTROL_PANEL_BASE_TOKEN=RVtDb7nGkabAMbsDkA0cvxdOnld \
FEISHU_CONTROL_PANEL_TABLE_ID=tblpqsBvrDMWhaiW \
python -m apps.cli --json run-control-panel-once
```

这条命令只检查一次 `系统控制台` 表，不会常驻，也不会自动循环。只有记录的 `开始执行` 被人工改成 `是，开始` 才会处理；处理后会自动改回 `否`。

## 已确认范围

- 第一阶段平台：小红书
- 第一阶段重点：稳定采集、上下文、去重、增量、新词发现
- 保留少量高价值信号飞书预警
- 暂不做自动私信、自动评论、CRM 和多平台

## 需要主控 Codex 完成的下一件事

1. 先不做新的小红书采集；继续用旧数据验证 DeepSeek、Campaign、飞书审核和话术审批闭环。
2. 把 `feishu-ai-review-sync` 挂到飞书 `系统控制台` 或后续 worker，让它可以被普通用户显式触发。
3. 为 `approved_to_send` 增加受控发送入口或 worker，但在浏览器/网络问题解决前不要真实触发小红书发送。
4. 把 `AI筛选客户线索` 的主字段从 `客户` 优化为更适合卡片展示的字段，或新建一张“客户审核卡片表”，让卡片标题直接显示 `需求摘要`。
5. 对 61 条 `待人工确认` 做人工审核，标记 `可跟进` / `已忽略`，记录误判类型。
6. 用 `系统控制台` 执行一次非破坏性真实指令，例如 `查看系统状态`，确认普通用户流程可复现。
7. 更新 `docs/reports/FEISHU_WORKBENCH_VERIFICATION.md`，补充 2026-07-09 之后的真实点击和审批状态。

子会话不得直接修改本文件或把任务改为 DONE。

## 当前已知风险

- 飞书 Base 旧工作台里仍有规则型 AI 结果；61 条待人工确认里有噪音。
- `AI筛选客户线索` 当前主字段仍是 `客户`，很多行显示 `未知用户`；同步 payload 已把 `需求摘要` 前置，但 Base 主字段/卡片标题仍需继续调整。
- `feishu-ai-review-sync` 已做成正式命令；当前还需要本机命令显式触发，尚未挂入飞书系统控制台或常驻 worker。
- `系统控制台` 是人工触发的一次性命令；没有后台自动轮询，符合用户要求，但需要有人在本机运行命令。
- `找新客户` 会触发真实采集，仍受小红书登录态、平台风控和 MediaCrawler 运行状态影响；当前用户要求先不做采集。
- 小红书真实私信发送暂时搁置：Safari/Chrome/Playwright 在当前 VPN/网络环境下无法稳定打开小红书，用户要求不要改 Clash。飞书话术审批按钮只能写入 `approved_to_send`，不能伪造成已发送。
- Docker 未安装，当前使用本机 Homebrew PostgreSQL。
- `pytest -m live` 因未启用 live 登录环境仍为 skipped。

这些风险直接影响“无人值守全自动获客”验收，但不影响当前“飞书人工工作台 + 人工发指令执行一次”的能力。


## 2026-07-09 今日已完成

- GitHub 主线已调整为 `main`，并推送到 `origin/main`。
- 最新提交：`f4e24c9 fix: defer outreach sending after approval`。
- CLI/API 入口加载本地 `.env`；pytest 进程默认跳过本机 `.env`，避免真实配置污染单元测试。
- 飞书话术审批卡“发送”按钮改为审批入库，不再在回调线程里直接执行小红书发送。
- 新增 `send_approved_outreach()` 作为后续独立发送入口；发送失败会记录 `failed`、`last_error` 和 `attempt_count`。
- 新增 `feishu-ai-review-sync`，DeepSeek 新结果可增量同步到 `AI筛选客户线索` / `AI筛选证据明细`。
- `/leads` 升级为客户判断工作台，增加业务摘要、为什么推荐、证据展开、SLA/新鲜度和完整人工判断动作。
- 飞书 AI 筛选同步字段按运营视角重排，业务字段前置，技术字段后移。
- `/ops` 明确为管理员控制台，危险操作增加角色边界和确认提示。
- 全量测试通过：`305 passed, 4 skipped, 1 warning`。

## 2026-07-06 今日已完成

- 飞书真实 Base 已作为人工获客工作台接通，Base token：`RVtDb7nGkabAMbsDkA0cvxdOnld`。
- 新增并验证 `AI筛选客户线索`：71 个客户，其中 `高意向=10`、`待人工确认=61`。
- 新增并验证 `AI筛选证据明细`：72 条证据，全部关联回客户线索。
- 新增 `待人工确认卡片` 视图，优先展示 `需求摘要`，供普通用户人工审核。
- 新增 `系统控制台` 表，字段使用普通话：`我要做什么`、`开始执行`、`现在状态`、`结果`、`哪里出错了`。
- 新增 `run-control-panel-once` 命令，符合用户要求：不自动跑、不常驻，只在人为设置 `开始执行=是，开始` 后执行一次。
- 真实验证系统控制台：`开始执行=否` 时不执行；改成 `是，开始` 后执行一次，写回 `已完成` 和结果文字。
- 当时全量测试通过：`275 passed, 4 skipped, 1 warning`。
- 当时分支已推送到 GitHub：`feat/v15-agent-neutral-runtime`，最新提交 `8623c66`；2026-07-09 已合并到 `main`。

## 2026-07-03 今日已完成

- 提交并推送增量分析修复：Pipeline Runner 不再每轮读取全部 `contents` 和 `comments` 重算。
- 新增 `analysis_processing_states`，用 `analysis_version`、文本指纹和处理记录判断是否需要重新分析。
- 新增有限历史上下文策略，避免聚类和候选词发现脱离历史，也避免全库扫描。
- 新增 `/ops` 运维看板，提供状态、查询、运行记录、洞察和启动一轮流程。
- 新增 macOS 桌面启动图标：`~/Desktop/打开AIXHS看板.command`。
- 新增 `scripts/open_dashboard.command`，可自动启动本机 API 并打开网页。
- 看板界面、按钮反馈和状态文本改为中文。
- “启动一轮”无启用查询时，会自动创建默认真实查询 `KET PET 二刷`。
- 桌面启动器默认 `WORKER_ADAPTER=mediacrawler`，不再默认 mock。
- 启动器会检查项目内 `third_party/MediaCrawler`，并自动创建 `third_party/MediaCrawler/.venv` 安装依赖。
- 启动器未检测到小红书持久登录态时，会自动启动 MediaCrawler 登录流程。
- 修复扫码登录后脚本停住的问题：扫码后在终端按回车，脚本会清理登录浏览器并继续启动主服务和网页。
- 所有上述代码当时已推送到 GitHub 分支 `feat/v15-agent-neutral-runtime`；当前主线见 2026-07-09 小节。
- 本次文档补充也需要提交并推送，具体 HEAD 以 `git log` 和 GitHub 分支历史为准。
- 新增 AI 自动获客最小闭环代码和页面：`services/lead_generation.py`、`/api/leads`、`/leads`、`leads-backfill`。
- 新增 lead 相关测试，当时完整测试已通过：`184 passed, 2 skipped, 1 warning`。当前最新测试结果见 2026-07-06 小节。
- 已收紧 lead 规则：排除攻略、老师、机构、推广和明确无需求内容；评论只保留报课、课程、机构、价格、试听、老师是否带课等跟进相关问题。
- 用户人工点击已处理的 3 个 lead 已确认是可跟进真实家长，并已调整为 `qualified`：`请问PET阅读怎么提高呢？`、`老师，线上带PET吗？`、`请问考完pet您给孩子报什么课程了么？`
- 已重新执行 `leads-backfill --rebuild`，自动队列中的广告/无需求候选已清空；当前 `/api/leads/summary` 为 `qualified=3`、`needs_enrichment=0`、`handled=0`。


## 新电脑与并发计划

- 项目将在新电脑上启动
- 第一轮 T01 已完成
- T01、T02、T03、T04、T05 已完成
- T06 查询管理 API 已完成，独立执行对话：019f1c0d-46a0-7f81-aa27-ffd46120ec90
- T07 小红书搜索采集已完成，提交：84b47e4
- T08 小红书详情采集已完成，提交：e1d33fb
- T09 小红书评论采集已完成，提交：a76cb0d
- T10 断点续传与部分成功已完成，提交：3940496
- T11 高价值内容池已完成，提交：e4d0631
- T12 评论区动态预算已完成，提交：6f36f95
- T13 查询与来源评分已完成，提交：8699b21
- T14 文本处理与低信息标记已完成，提交：8b25692
- T15 语义聚类与新词发现已完成，提交：243181d
- T16 飞书新词审核已完成，提交：cbc43bc
- T17 事件日历已完成，提交：514e8b9
- T18 需求事件链已完成，提交：4d9ef37
- T19 信号新鲜度与飞书预警已完成，提交：e2809b7
- T20 数据看板已完成，提交：fbb8e44
- T21 内容洞察输出已完成，提交：46a1b13
- T22 第二平台评估已完成，提交：9bf7f40
- 默认启用 W1、W2 两个 Worker
- 稳定后可增加 W3
- W4 仅在低冲突阶段启用
- 具体规则见 `docs/CONCURRENCY_POLICY.md`


## AI 工具接手方式

- Codex 主控入口：`MASTER_CODEX_PROMPT.md`
- Claude Code 主控入口：`CLAUDE_MASTER_PROMPT.md`
- Claude Code 持久规则：`CLAUDE.md`
- 两种工具交接：`docs/AGENT_HANDOFF.md`

## 对话启动方式

- 项目经理对话持续保留
- 每个任务单独新开一个独立执行对话
- 独立执行对话不从项目经理对话派生
- 所需上下文由项目经理写入任务包
- 2026-07-12 Task 7 评论回复文档与安全验收合同已完成自动化侧整理：新增 `docs/COMMENT_REPLY_OPERATIONS.md` 和默认跳过的 `tests/test_comment_reply_live_contract.py`。当前不得宣称真实小红书评论发送成功；live acceptance 仍阻塞于一个明确准备的测试帖子/评论、只读 selector probe 通过，以及飞书人工对最终文本和本次单条发送的明确批准。`result_unknown` 禁止盲目重试，只能人工核对平台后处理。

## 2026-07-13 评论回复真实验收推进

- 已修复评论 sender 未读取远程 CDP 配置的问题：`COMMENT_REPLY_BROWSER_MODE=remote_cdp` 时使用 Playwright `connect_over_cdp` 复用 Windows Chrome 现有 context，不在 Mac 启动浏览器。
- 已修正真实页面交互顺序：先点击目标评论“回复”，再等待并定位编辑框和提交按钮；selector probe 只展开回复控件，不填写、不提交。
- 已把飞书评论回调改为快速审批入队：状态写为 `approved_to_send`，创建 `comment_reply_send` 持久任务并立即返回；独立 Worker 才执行浏览器发送、飞书结果卡片和客户跟进同步。
- 相关定向回归测试已通过；完整测试结果以本次最终验证记录为准。
- 真实验收仍未完成：2026-07-13 从 Mac 连接 `100.124.24.8:19223` 时 TCP 可建立，但 DevTools HTTP 返回 empty reply、Playwright 报 socket hang up；SSH 22 端口也被远端立即关闭。当前 `.env` 同时缺少 live test URL/comment ID/content ID/最终批准文本和客户跟进 Base token/table ID。不得宣称真实评论已发送。

## 2026-07-14 评论回复中断恢复与自动化验收

- 已同步 `docs/COMMENT_REPLY_OPERATIONS.md`：飞书回调只写入 `approved_to_send` 并创建 `comment_reply_send`，Worker 独立通过 Windows Chrome CDP 发送，不再描述同步回调发送。
- diff 审查发现并修复一个安全缺口：评论发送 Worker 现在强制要求 `COMMENT_REPLY_BROWSER_MODE=remote_cdp` 和非空 `COMMENT_REPLY_CDP_URL`；配置遗漏时任务失败且回复保留 `approved_to_send`，不会在 Mac 启动本地浏览器。
- 全量测试首次收集发现 `integrations.feishu.comment_replies` 顶层导入 `scheduler` 导致循环依赖；已把 `create_task` 改为入队函数内延迟导入，并用 `tests/test_agent_runtime.py` 和评论入队测试验证。
- 定向测试：`84 passed, 3 skipped, 1 warning`。全量测试：`494 passed, 7 skipped, 1 warning`。
- 本次没有运行 live selector probe 或真实评论发送。Windows CDP/SSH、专用测试目标、最终批准文本和客户跟进 Base live 配置仍是外部阻塞，Task 7 保持 `DONE_AUTOMATED / LIVE_BLOCKED`。

## 2026-07-14 V16 飞书任务中心与 Skill Runtime

- 分支：`feat/v16-task-productization`。
- 新增唯一 Skill `screen_historical_leads / 历史线索智能筛选`，使用现有 PostgreSQL 历史数据、DeepSeek、Campaign 资格判断和 `feishu-ai-review-sync`。
- 飞书回调只持久化/入队并返回 `accepted`；独立 Worker 执行并 PATCH 同一消息卡片。
- 支持预览、进度事件、Worker 断点恢复、安全取消、明确失败重试、结果、复制和可选“任务运行记录”Base 投影。
- 本轮未运行 live selector probe，未访问小红书，未发送评论或私信。
- 最终自动化证据见 `docs/reports/V16_TASK_PRODUCTIZATION_VERIFICATION.md`。
- 最终全量测试：`504 passed, 7 skipped, 1 warning in 25.81s`；Alembic head 为 `0016_skill_runs`；`git diff --check` 与编译检查通过。
- 2026-07-14 已完成真实安全验收：Run `#1`/Task `#357` 处理 3 条历史评论，结果为有效需求 1、待确认 3；飞书消息 `om_x100b6a569a7d60a4b04c75cc36b0d05` 同卡片更新成功，AI 审核 Base 新增客户 1、证据 1。按钮公网回调仍待开发者后台 URL/token 配置。
- 2026-07-15 修正飞书可见性验收：旧 chat 是单人私群，用户未实际看到；已改用 bot P2P `oc_db1d787a662278e05ce8a5c035a66ee0`，并重新发送任务中心和 Run #1 完成卡。后续不得把“API 可读”直接等同于“用户已收到”。
- 2026-07-15 用户真实点击返回 `200671`。Card 2.0 字段已修；`lulu大王` 只是旧私群成员，不能推断为历史回调应用，此前复用它的判断已撤回。当前唯一证实的发卡应用是 `cli_aac1e28d6a399bfc`；在读取其开发者后台现有配置前，不再建议切换回调模式。V16 按钮闭环保持未验收，本机配置和后台进程已恢复。

## 2026-07-15 V16 Card 2.0 回调协议修复

- 从重启前 API 真实日志确认 `200671` 的直接根因：飞书真实按钮事件把动作放在 `event.action.value.action`，旧代码只识别 `event.action.name`，导致 `skill_create_screen_historical_leads` 被误送入 LLM 审核处理并返回 HTTP 400。
- `services/feishu_task_center.py` 现兼容 Card 2.0 普通按钮 `action.value.action` 与表单提交 `action.name`；不改开发者后台 HTTP 模式，不改原回调地址，不引入其他应用。
- `POST /feishu/callback/llm-review` 现对任务中心立即返回官方 `toast + card(type=raw)`，其他卡片动作返回官方 toast；不再返回自定义 `code/msg/accepted` 包装。
- 修正飞书签名算法为 `SHA256(timestamp + nonce + encrypt_key + raw_body)`，并新增外层 `encrypt` AES-CBC 解密；新增依赖 `pycryptodome`。
- 自动化：`509 passed, 7 skipped, 1 warning in 25.97s`；编译与 `git diff --check` 通过。
- 协议探针：本地原路由 HTTP 200 / 0.05 秒，公网原地址 HTTP 200 / 0.81 秒，响应为官方 `toast + raw Card 2.0`；固定事件创建幂等测试 Run `#6`。这证明地址、隧道、路由和响应协议当前可用，但最终按钮闭环仍需用户在飞书中进行一次真实点击复验。

## 2026-07-15 飞书任务中心“创建任务”真实点击成功

- 用户已发布应用版本 `1.0.2`；App ID 仍为 `cli_aac1e28d6a399bfc`，HTTP 回调地址仍为 `https://three-emus-kick.loca.lt/feishu/callback/llm-review`，订阅仍为 `card.action.trigger`。
- 发布后第一次新卡点击仍没有进入 API。确认应用、版本、订阅、发卡身份和加密策略无误后，停止并使用相同 `--subdomain three-emus-kick` 重启 localtunnel，没有修改飞书后台地址。
- 重启隧道后发送新卡 `om_x100b6a5c096318a4b1ca479dccbd4b8`；用户点击“创建任务”成功，API 真实收到飞书服务器 POST 并返回 HTTP 200。
- PostgreSQL 创建 `Skill Run #8`：`status=draft`、`skill_key=screen_historical_leads`，真实 `requested_by`、chat ID 和 message ID 均正确持久化。
- 完整配置、启动顺序、Card 2.0 字段、响应合同、签名/加密、验收命令和 `200671` 排障矩阵已写入 `docs/FEISHU_CARD_CALLBACK_RUNBOOK.md`。
- 此节点当时只完成“创建任务 → 参数表单”的真实验收；后续完整结果见下一节。

## 2026-07-15 Run #8 全流程真实完成

- Run `#8` 的参数表单第一次只显示 toast，是因为 Card 2.0 `select_static` 使用了非法 `label`；飞书 PATCH 明确返回 `200621 unknown property label`。已改为 `placeholder`。
- 表单首次点击预览没有请求，是因为提交按钮只有 `form_action_type=submit`，缺少 `behaviors.callback`。两者同时配置后，预览和确认运行均真实回调成功。
- localtunnel 会话中途再次直接返回 HTTP 503；保持同一 subdomain 重启后恢复。该入口不能作为长期生产方案。
- Run `#8` 实际参数为全部历史数据、帖子和评论、50 条、`education_fuzhou_offline`；预览 50 条，确认后创建 Worker task `#358`。
- Worker task `#358` 完成 50/50，Run 状态 `succeeded`；有效需求 0、高意向 0、待确认 50，飞书同步为 dry-run，失败 0。
- Worker 首次没有更新进度卡，是因为专用入口未加载 `.env`，且消息 PATCH 继承 `FEISHU_LARK_CLI_AS=user`。现已让 Worker 入口加载 `.env`，并将应用消息 PATCH 固定为 bot 身份；无额外环境变量的新进程已成功更新 Run `#8` 最终完成卡。
- 最终自动化：`510 passed, 7 skipped, 1 warning in 26.29s`；编译、`git diff --check` 和公网 `/health` HTTP 200 通过。

## 2026-07-15 Run #8 结果详情与 Base 真实同步修复

- 用户点击“查看结果”后无明显变化的根因：`skill_result_<id>` 旧实现仍调用 `build_skill_run_card()`，只是重复渲染完成摘要。
- 新增独立“任务结果详情”卡，展示运行参数、处理统计、同步状态、客户线索表入口、证据明细表入口和复制任务按钮。
- dry-run 现在明确显示“未写入多维表格”和预演条数，不再伪装成成功的 0/0/0。
- 本机已切换为已验证的 `lark_cli` Base 写入配置；Run `#8` 未重跑 DeepSeek，复用 screening `51-100` 完成真实同步。
- 远端实际新增客户 50、证据 50；PostgreSQL 已恢复 100 条映射，Run `#8` 同步摘要为新增 100、失败 0、dry-run 0。
- 飞书消息 `om_x100b6a5c096318a4b1ca479dccbd4b8` 已直接更新为“任务结果详情”。公网 `/health` 当前 HTTP 200。
- 最终全量验证：`513 passed, 7 skipped, 1 warning in 26.51s`；编译检查与 `git diff --check` 通过。

## 2026-07-15 Founder Copilot 与人工审核工作台约定

- 用户要求把多维表格从结果展示页升级为人工审核工作台，通过卡片、审核动作和工作流完成有效、无效、待二审、重新分析和进入跟进。
- 正式设计见 `docs/FOUNDER_COPILOT.md`；后续 Codex 必读的专用交接见 `docs/FOUNDER_COPILOT_HANDOFF.md`。
- Founder Copilot 应在完成真实任务时静默观察表达完整性、产品建立、决策推进和协作需要。
- 默认约每 2–3 天反馈一次，具体时机由 Codex 根据有效证据判断；没有新证据、正在处理线上事故或反馈会干扰执行时可以延后。
- 反馈一次只指出一个高杠杆改进点，并提供具体事实和可直接复用的表达示例；不得进行心理诊断或空泛评价。
- 当前只有设计与交接，Base 审核字段、审核记录表和工作流尚未实施，已列入 V17。

## 2026-07-15 V18-01 妙搭“今日工作台”发布完成

- 正式设计：`docs/superpowers/specs/2026-07-15-feishu-miaoda-operations-console-design.md`。
- 实施计划：`docs/superpowers/plans/2026-07-15-v18-01-miaoda-today-workbench.md`。
- 后端新增受 `OPS_TOKEN` 保护的 `GET /operator/api/workbench`，聚合待审核线索、运行中 Skill Run、失败任务和 Worker 心跳，不新增表或迁移。
- 妙搭仓库新增 NestJS BFF 和 React 今日工作台；浏览器只访问同源 API，token 仅在服务端环境变量中使用。
- 真实本地联调：FastAPI 与 NestJS 业务载荷一致；验收时读取 4 条待审核、6 个失败任务、8 个过期 Worker；停止 FastAPI 后 BFF 返回结构化 `503` 且无 token 泄露。
- 自动化：后端 `520 passed, 7 skipped, 1 warning`，编译和差异检查通过；妙搭 `6 passed`，类型检查、ESLint、Stylelint 和完整生产构建通过。
- 妙搭发布 ID `7662655014494768100`，发布提交 `4bbcd63c7c860293b81e6f08af3e934c950bfc16`，线上入口 `https://tiho2o4ymck.aiforce.cloud/app/app_17a4790srtt`。
- 当前线上指定范围可见且要求登录。由于没有稳定公网 FastAPI，未配置线上 `OPERATOR_API_BASE_URL` / `OPERATOR_API_TOKEN`，页面会明确显示降级态和完整结构预览；不得改用 localtunnel 冒充生产入口。
- 下一推荐任务：`V18-02` 线索审核写操作；稳定公网后端、在线环境变量和权限审计统一在 `V18-05` 完成。
- 浏览器自动验收受宿主内置浏览器信任桥拒绝；已改用 HTTP、CSRF、BFF 数据一致性、降级响应和生产构建验证，不宣称完成视觉截图验收。

## 2026-07-15 V18-05A 妙搭真实数据连接完成

- 新增独立 `apps.operator_gateway` 进程，只注册 `/health` 和受 token 保护的 `/operator/api/workbench`；原线索写接口、管理员接口和飞书回调均未暴露。
- 公网固定入口为 `https://aixhs-operator-gateway.loca.lt`；公网与本地业务载荷逐字段一致，验收快照为待审核 4、失败任务 6、Worker 8、运行中 Skill Run 0。
- 妙搭 online 环境已设置 `OPERATOR_API_BASE_URL` 和 `OPERATOR_API_TOKEN`，并完成 release `7662664425467481056`，状态 `finished`。
- 新增 `scripts/install_operator_gateway_launchd.sh`，通过 `com.aixhs.operator-gateway` 和 `com.aixhs.operator-tunnel` 自动启动及异常拉起。
- 运行与恢复手册：`docs/OPERATOR_GATEWAY_RUNBOOK.md`；真实闭环和真人体验验收：`docs/reports/V18_MIAODA_REAL_CONNECTION_ACCEPTANCE.md`。
- 安全探针：无 token 为 401，`/api/leads` 与 `/ops/api/system` 为 404；公网业务响应未暴露 token。
- 此处记录的是 localtunnel 阶段的中间状态；最终已在下一节切换为 Tailscale Funnel。

## 2026-07-16 V18-05A 切换稳定 Tailscale Funnel

- 用户完成 Tailscale 账号 Funnel 授权后，公网入口切换为 `https://xiaohao30000macbook-pro.tail9daeec.ts.net`，HTTPS 443 代理本机 `127.0.0.1:8020`。
- 连续 5 次公网健康检查 HTTP 200；真实工作台返回待审核 4、失败任务 6、Worker 8、运行中 Skill Run 0。
- 安全复验：无 token 工作台 401，`/api/leads`、`/ops/api/system` 和飞书回调均为 404。
- 妙搭 online `OPERATOR_API_BASE_URL` 已更新为稳定 `ts.net`；release `7662804087717498126` 状态 `finished`，线上入口 `https://tiho2o4ymck.feishuapp.com/app/app_17a4790srtt`。
- 已移除 localtunnel launchd 配置；`scripts/install_operator_gateway_launchd.sh` 现在只维护网关 launchd 并确保 Tailscale Funnel 开启。
- 自愈验收：主动结束网关 PID `61879` 后，launchd 自动以新 PID `61913` 拉起；稳定公网地址继续返回 HTTP 200 和真实工作台数据。
- 真人链路模拟：使用妙搭实际 CSRF Cookie + `X-Suda-Csrf-Token` 请求同源 BFF；BFF 与公网网关的业务载荷逐字段一致，第一条真实线索为 `线索 #151`，推荐动作为 `inspect_failure`，响应未泄露 token。

## 2026-07-16 妙搭运行时可见范围修复

- 用户无法在飞书打开应用的根因：运行范围是 `Range`，但只有访问申请审批人，没有任何实际 `users` / `departments` / `chats` 目标。
- 已确认审批人 open_id `ou_2e31580f74e91be75997d4f6ac1c7cea` 对应用户“张兆尊”。
- 已将该用户加入 specific 可见名单，并保留访问申请和本人审批；复查结果 `scope=Range` 且 `users` 已包含该 open_id。
- 这是运行时访问权限修复，不是开发协作者权限，也不需要重新发布代码。

## 2026-07-16 V18-02A/V18-03 线索审核与任务中心真实闭环

- Operator API 新增受 `OPS_TOKEN` 保护的 `/operator/api/leads*` 和 `/operator/api/tasks*`；公网网关仍不暴露原 `/api/leads`、管理员接口和飞书回调。
- 线索审核页已替换占位页：真实队列、AI/原始证据、有效、无效、观察、补充信息、负责人和进入跟进动作写回 PostgreSQL；真人验收对线索 `#151` 写入 `watch` 后按快照完整恢复为 `needs_enrichment`。
- 任务中心已替换占位页：模板、Campaign、数据范围、来源类型、数量、创建、预览、确认、取消、重试、复制、进度、事件和结果详情均接入现有 Skill Runtime。
- 新增 `com.aixhs.skill-run-worker` LaunchAgent，仅消费 `skill_run_execute`；真实 Run `#11` 处理 1/1 并 `succeeded`，飞书同步失败 0，不访问小红书、不发送评论或私信。
- 后端全量测试 `531 passed, 7 skipped, 1 warning`；妙搭 Jest `9 passed`，双端类型检查、ESLint、Stylelint、生产构建通过。
- 妙搭提交 `38501e4e777689c93d75e70bddec4ee7f0888566`，release `7662812324507454684` 状态 `finished`，线上入口保持 `https://tiho2o4ymck.feishuapp.com/app/app_17a4790srtt`。
- 可见范围复查仍为 `Range + require_login`，用户列表包含“张兆尊”的 open_id。
- 未完成：V18-02B 单条重新分析、重复客户合并和飞书深度链接；持续在线云托管与角色审计仍属于 V18-05。

## 2026-07-16 妙搭源码 GitHub 镜像

- 妙搭源码已镜像到公开仓库 `https://github.com/xiaohao300000000-cmd/aixhs666-console`。
- GitHub 默认分支为 `sprint/default`，提交 `38501e4e777689c93d75e70bddec4ee7f0888566`；同时保留发布快照 `main` 和历史分支 `feat/v18-01-workbench`。
- 本地妙搭仓库的 `origin` 继续指向妙搭官方 Git，供 `apps +release-create` 发布；新增 `github` remote 仅用于 GitHub 镜像。
- `sprint/default` 的 upstream 已恢复为 `origin/sprint/default`，避免后续误推 GitHub 后却未同步妙搭发布源。
- 公开前扫描未发现真实 `OPS_TOKEN`、`OPERATOR_API_TOKEN`、飞书预览 token 或 GitHub token；跟踪的 `.env` 仅含日志配置。
