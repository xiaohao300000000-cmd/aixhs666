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
304 passed, 4 skipped, 1 warning
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
- 全量测试通过：`304 passed, 4 skipped, 1 warning`。

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
