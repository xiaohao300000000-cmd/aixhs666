# V19-04 妙搭运营体验验收报告

验收日期：2026-07-17（返工收口）

## 结论

V19-04 已在 `miaoda-console/**` 内完成。妙搭本地页面使用真实 Operator Gateway / PostgreSQL 只读数据呈现今日主动作、Run 业务报告、每日连续审核、客户中心、Base 去向和系统健康；未使用演示数据，未触发任何审核、继续队列、发布、Base/飞书写入、公开回复、私信、采集或调度动作。

当前代码可交由主控验收、合并和发布。现行公网 Gateway 进程尚未提供 V19-03 新增的报告/队列/客户路由，Run #8 报告 GET 返回 404；本报告通过当前 worktree 的临时本地 Gateway 连接同一真实 PostgreSQL 完成只读验收。主控发布妙搭前需先确认 Gateway 已部署/重启到含 V19-03 路由的版本。

## 实现范围

- NestJS BFF 代理工作台、单条线索详情、Run 报告/候选、每日审核队列、客户列表/详情/时间线；Bearer token 始终仅存在服务端。
- 首页根据真实阻塞、审核进度和客户状态生成首要动作，不显示内部 task type 或演示数字。
- Run 页面展示人类结论、漏斗、候选分层、数据去向和审核深链，技术细节默认折叠。
- 审核页恢复批次、当前候选和位置；展示真实证据、动作后果、原因约束、稳定幂等键和下一条选择；缺少 `lead_id` 时明确禁用提交。
- 客户中心展示阶段、下一步、同步状态、详情时间线和真实 Base 记录深链，不伪造缺失映射。
- 系统健康区分阻塞/非阻塞异常，Base/飞书无健康探针时显示“未提供状态”，并隐藏 token、URL、绝对/相对本机路径和堆栈。
- 明确标注 V19-05/V19-06 才开放的公开回复、回复检查和调度能力；V19-04 没有实现或触发这些动作。

## TDD 与提交

每一组 BFF 合同、视图模型和浏览验收发现的缺口均先运行失败测试，再最小实现并转绿。提交如下：

1. `5a2764a feat: proxy V19 operator resources in Miaoda`
2. `d6d7e4b feat: build action-first workbench and run reports`
3. `69cb7be feat: add continuous review experience`
4. `fb6aa7e feat: add customer center and timeline`
5. `71ea532 feat: add system health and recovery states`
6. `311cc0a fix: translate live customer timeline facts`
7. `99e8042 fix: close real review and privacy gaps`
8. `2cf9aa0 fix: route system failures to operator actions`
9. `0594120 docs: verify V19-04 Miaoda experience`
10. `479dd98 fix: close V19-04 review safety gaps`
11. 本轮报告更新提交

真实浏览额外发现并修复三处自动化前未暴露的问题：中文 `action_type=新客户` 的业务翻译、缺失的单条线索详情 BFF GET、系统健康中的本机路径/Traceback 泄漏；同时把异常动作链接收敛到任务中心。

2026-07-17 返工收口保留并复验五项已有修复：成功 Run 在报告加载、404、401、503 和 unknown 状态下不冒充业务结论；客户 `sync_error` 只显示脱敏摘要；下一 pending 到队尾后从队首回绕；Run 候选与日队列在加载/错误时绝不串线且不保留 selected/lead；文件清单使用实际的 `TaskCenterPage.tsx`。

最后两项审查按 RED→GREEN 完成：

- RED：`Authorization: Bearer secret-token` 的旧脱敏结果仍残留 `secret-token`；GREEN：先整体识别 Authorization Bearer 值，再执行通用 token 脱敏，定向测试转绿。
- RED：旧日队列 data 在后台刷新或请求错误时，没有可供页面约束 continue 写动作的纯状态合同；GREEN：新增 `reviewQueueWritesEnabled`，只有 `ReviewBatchView.state === ready` 才允许“继续审核 20 条/只看高优先级”，页面同时受 mutation busy 与该合同约束。

## 自动化结果

| 检查 | 结果 |
|---|---|
| `npm test -- --runInBand` | 2 suites、38 tests 全部通过 |
| `npm run type:check` | server/client 均通过 |
| `npm run lint` | eslint、type check、stylelint 全部通过 |
| `npm run build` | 生产构建成功，API/页面路由与 server/client 产物生成成功 |
| 简报原样后端命令 | 失败：仓库不存在 `tests/test_operator_customers.py`，pytest exit 4、未运行测试 |
| 将上述文件名更正为 `tests/test_customer_crm_operator.py` 的指定集 | 32 passed，1 个既有弃用 warning |
| 全量 `pytest -q` | 594 passed、7 skipped、1 个既有弃用 warning |
| `git diff --check` | 通过 |

Jest 锁定 BFF 路径/参数/请求体/服务端 Bearer、400/401/404/422/503 安全翻译、主动作、Run 漏斗、URL 恢复、下一条回绕、审核后果、幂等键复用、客户/时间线/Base 状态、缺字段、系统异常分层、完整 Bearer 脱敏、旧日队列加载/错误态禁写和未启用能力边界。

## 真实只读数据验收

### Operator / PostgreSQL

- 现行公网 workbench GET 成功：审核队列 0（旧投影）、运行中 0、失败任务 6、stale Worker 8；公网 Run #8 报告 GET 为 404，证明运行中 Gateway 尚未加载 V19-03 路由。
- 使用当前 worktree Gateway 连接真实 PostgreSQL，只执行受认证 GET：
  - Run #8：分析 50 条公开内容，合并 49 个待审核候选；高优先级 1、普通 0、不确定 48、自动排除 1；每日队列准备 50、QC 5、backlog 36。
  - 2026-07-16 队列：总数 50、完成 0、待处理 50、位置 1–50 且 candidate key 唯一；高优先级 1、不确定 49。27 条缺少 `lead_id`，页面如实禁用错误目标提交。
  - 客户：12 条真实客户事实，均处于新客户阶段；1 条已同步 Base、11 条待同步。
  - 客户 #147：稳定路径 `/customers/147`，有 1 条时间线事实、真实下一步和 Base 记录映射；未伪造联系或下次跟进。
- 临时 Gateway 与页面服务均只读使用真实库；验收结束后停止，不保留后台进程。

### 六条页面路径

| 路径 | 真人体验结果 |
|---|---|
| `/` | 首次成功数据渲染在 10 秒内明确给出“先审核 1 条高优先级候选”；显示 0/50、客户 12 和系统异常入口 |
| `/tasks?run_id=8` | 显示中文业务结论、50→49 漏斗、四层候选、四类数据去向；候选层和“审核本次候选”均为稳定深链 |
| `/leads?queue_date=2026-07-16&candidate_key=profile%3A407&position=6` | 恢复第 6 条高优先级候选，真实单条详情、证据链和动作后果可见；未点击任何写按钮 |
| `/customers` | 显示 12 个真实客户、阶段、下一步和同步状态；仅已映射客户显示 Base 入口 |
| `/customers/147` | 显示需求证据、AI 判断、中文时间线、稳定相对地址和真实 Base 深链；未打开外部链接 |
| `/system-health` | 显示 8 个 stale Worker、6 个非阻塞失败、无可证明阻塞失败；Base/飞书为“未提供状态”；错误动作指向任务中心 |

桌面宽度 1280px 的六条路径均无横向溢出。使用 390×844 视口逐路复验，六条路径的 `scrollWidth` 均等于 390，无横向溢出；验收后已重置视口。

## 加载、空、错误和隐私状态

- 本地首次未映射 `OPERATOR_API_TOKEN` 时，首页正确显示“尚未配置访问凭证”，没有静态数字或 token；映射服务端 `OPS_TOKEN` 后恢复真实数据。
- 公网新路由 404、缺配置、后端不可达、上游 400/401/404/422/503 均由安全错误合同覆盖。
- 空队列、缺失报告、缺少 `lead_id`、缺失 Base 映射、缺少联系事实和未提供集成健康探针均有明确中文状态。
- 浏览器验证系统健康文本不包含 `/Users/`、`third_party/` 或 `Traceback`；单测同时验证 token 与内部 URL 不进入 UI 摘要。
- 报告只记录聚合统计、稳定业务 ID 和脱敏状态，不保存 token、Cookie、完整个人内容或内部地址。

## 未触发外部动作

- 未调用审核 POST、`continue`、`prepare`、`rebuild` 或任何任务运行写接口。
- 未写 PostgreSQL、Base、飞书；未打开 Base 外链。
- 未触发公开回复、私信、回复检查、小红书访问、采集或 14:00/15:00/21:00 调度。
- 未修改 `/Users/xiaohao30000/aixhs666-console`，未设置环境变量、可见范围或 release，未推送/合并。

## 主控发布清单

1. 验收并合并本分支 `codex/v19-04-miaoda-operations`；只导出合并后的 `miaoda-console/**` 到官方发布工作区。
2. 发布前确认 Operator Gateway 已运行包含 V19-03 报告/队列/客户 GET 路由的代码；以 Run #8 报告和 2026-07-16 队列 GET 返回 200 为准。
3. 在发布工作区确认服务端 `OPERATOR_API_BASE_URL` 与 `OPERATOR_API_TOKEN`，不要把 token 写入源码或客户端环境。
4. 在官方 `sprint/default` 上复跑 Jest、type check、lint、build，提交并推送后创建妙搭 release，轮询到 `finished`。
5. 线上按 `/`、`/tasks?run_id=8`、`/leads`、`/customers`、`/customers/147`、`/system-health` 验收；只读检查深链，不执行真实审核或继续队列。
6. 回滚点：V19-04 前源码基线 `89c585b`；妙搭可回滚到先前已验收 release `7663073809487023329`。回滚前保留当前 release ID 和线上只读截图/响应摘要。

## 已知风险

- 公网 Gateway 进程当前对 V19-03 新 GET 路由返回 404；主控未部署/重启 Gateway 前，线上 Run 报告、每日队列和客户页会进入安全错误态。
- 真实日队列 50 条中有 27 条缺少 `lead_id`，只能展示和报告，不能审核；V19-04 如实阻止写向错误目标，数据修复不在本任务范围。
- 12 个客户中 11 个没有 Base 映射；页面显示“尚未同步”，没有伪造成功。
- workbench 未提供 Base/飞书健康探针，系统健康只能显示“未提供状态”。
- 简报指定测试文件名与仓库实际文件名不一致；本报告保留原命令失败并给出等价通过结果。
- Jest 有既有 `ts-jest` 配置 warning，pytest 有既有 Starlette/httpx2 弃用 warning；均不影响通过结果。

## 2026-07-17 V19-04-H1 审核队列继续动作热修

线上只读验收发现，成功加载后的空队列和已完成队列虽然提示可以继续审核，但继续按钮被纯视图模型错误禁用。热修按 TDD 将日队列写入合同修正为：`ready`、`empty`、`complete` 允许 continue；`daily_loading`、`daily_missing`、`daily_unavailable` 继续禁写。Run 模式仍不渲染日队列进度和 continue 按钮，任一 mutation pending 时页面仍统一禁用写动作。

本热修未修改页面、BFF、Python、FastAPI、数据库或依赖，未使用浏览器，未触发审核、continue 或任何外部写入；详细 RED、GREEN 和最终验证见 `orchestration/reports/V19-04-H1.md`。
