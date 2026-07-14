# 系统架构

## 1. 总体架构

```text
查询词库 / 事件日历 / 种子来源
                ↓
          任务调度器
                ↓
        平台采集适配层
                ↓
         原始数据存储
                ↓
      标准化、去重与关系化
                ↓
    语义分析、新词发现与聚类
                ↓
  高价值来源评分 / 信号新鲜度
                ↓
       飞书预警与数据看板
```

## 2. 技术栈

### 后端

- Python 3.12
- FastAPI
- SQLAlchemy 2.x
- Alembic
- Pydantic
- pytest

### 数据库

- PostgreSQL

第一阶段不使用 Kafka、Kubernetes 和复杂分布式架构。

### 采集

- Playwright
- Chrome CDP
- 真实浏览器会话
- 增量采集
- 页面原始快照

### 任务调度

第一阶段：

- PostgreSQL 任务表
- Python Worker
- n8n 定时触发

后续任务量增加后再考虑 Redis/BullMQ/Celery。

### 文件存储

- Cloudflare R2 或兼容 S3 的对象存储

保存：

- 原始 JSON
- HTML
- 截图
- 页面快照

### AI 分析

- 批量文本处理
- Embedding
- 便宜模型做批量分类和字段提取
- 强模型做新语义簇、查询扩展和覆盖分析

### 管理界面

第一阶段：

- 飞书多维表格
- 飞书机器人
- 简单 Web 看板

## 3. 模块边界

### collectors

负责“如何从平台拿到数据”。

不得包含：

- 线索评分
- 业务路由
- AI 提示词
- 飞书通知

### scheduler

负责：

- 创建任务
- 领取任务
- 重试
- 超时恢复
- 优先级
- 采集预算分配

### storage

负责：

- 数据库模型
- Repository
- 对象存储
- 快照
- 去重

### intelligence

负责：

- 文本标准化
- 字段提取
- 新词发现
- 语义聚类
- 查询扩展
- 覆盖分析
- 意图假设
- 黑话映射

### integrations

负责：

- 飞书
- n8n
- Cloudflare
- 外部模型 API

### apps/api

负责提供管理和查询 API。

### apps/worker

负责消费任务并执行采集或分析。

### services/pipeline_runner.py

负责 Agent 中立的完整运行闭环。它不是独立 Coordinator 微服务，也不引入 Kafka、Celery、Temporal 或 Redis 队列；它只在现有模块之上提供一个轻量服务层：

```text
选择查询
→ 创建/复用采集任务语义
→ 执行搜索采集
→ 详情、评论、用户入库
→ 文本处理
→ 需求事件链
→ 聚类和新词发现
→ 查询评分
→ 内容洞察
→ pipeline_runs 结构化结果
```

框架执行层负责确定性流程、状态持久化、幂等和结构化结果。AI 策略层只通过 CLI 或 REST 读取状态、选择查询、调整预算、批准候选查询和解释结果，不负责保存唯一状态或手动连接模块。

## 4. 平台适配器接口

```python
class PlatformAdapter(Protocol):
    async def search(self, query: str, cursor: str | None = None): ...
    async def fetch_content(self, content_id: str): ...
    async def fetch_comments(self, content_id: str, cursor: str | None = None): ...
    async def fetch_replies(self, comment_id: str, cursor: str | None = None): ...
    async def fetch_public_profile(self, user_id: str): ...
    async def check_updates(self, content_id: str, last_cursor: str | None = None): ...
```

平台适配器只负责返回统一数据对象。当前 V0 有三个实现路径：

- `MockPlatformAdapter`：测试和离线流程使用。
- `XiaohongshuAdapter`：默认真实小红书 Playwright 页面/公开响应采集路径。
- `MediaCrawlerXiaohongshuAdapter`：可选后端，通过 `WORKER_ADAPTER=mediacrawler` 启用，运行项目内 `third_party/MediaCrawler` 并把 JSONL 输出转换为统一数据对象。

注意：MediaCrawler 的 search 模式会在一次平台访问中生成内容详情和评论 JSONL。Pipeline Runner 后续 detail/comment 阶段优先通过同一 adapter 缓存读取这些结果，不为了流程形式再次访问小红书。

## 5. 渐进式采集

### L0：发现

仅保存：

- 平台内容 ID
- 标题或摘要
- 作者公开 ID
- 链接
- 发布时间
- 互动量
- 来源查询

### L1：正文补全

补充：

- 完整正文
- 标签
- 地域
- 图片链接
- 热门评论
- 最新评论

### L2：对话补全

补充：

- 一级评论
- 二级回复
- 作者回复
- 评论关系
- 评论者公开 ID

### L3：公开主页补全

仅对高价值候选补充：

- 公开简介
- 公开地区
- 公开联系方式
- 其他相关公开内容

## 6. 采集调度

第一版采用可解释评分：

```text
任务价值 =
0.30 × 新内容率
+ 0.20 × 新用户率
+ 0.20 × 新表达率
+ 0.15 × 覆盖空白价值
+ 0.15 × 上下文补全价值
- 重复率惩罚
- 采集成本惩罚
- 失败风险惩罚
```

资源建议：

- 60% 高产来源
- 20% 覆盖空白
- 10% 新查询
- 10% 随机探索

## 7. 评论区动态预算

每批采集 30 条评论，计算：

- 新用户率
- 新表达率
- 有效文本率
- 重复率
- 新机构或新地域数量

继续条件：仍有明显新增信息。

停止条件：连续两批新增信息显著下降。

第一版默认上限：

- 500 条一级评论
- 1000 条评论与回复总量

## 8. 事件雷达

系统维护教育事件日历：

- 报名时间
- 考试时间
- 出成绩时间
- 暑假
- 寒假
- 开学
- 期中
- 期末
- 分班考
- 小升初节点

事件发生前后自动提高相关查询频率。

## 9. 高价值来源评分

来源包括：

- 查询词
- 帖子
- 账号
- 评论区
- 竞品账号
- 考试资讯账号

评分考虑：

- 新需求用户数
- 新表达数
- 地域匹配度
- 近期活跃度
- 重复率
- 软广比例
- 采集成本

## 10. 可恢复性

所有任务必须支持：

- 断点续传
- 幂等写入
- 重试
- 部分成功
- 超时恢复
- 手动重跑
- 原始快照复查

## 11. 许可证和依赖原则

可以参考开源项目的架构和接口，但不得直接复制许可证不允许商业使用的代码。

任何新依赖加入前必须记录在 `DECISIONS.md`：

- 用途
- 许可证
- 替代方案
- 为什么选择它

## 12. 飞书审批后的小红书评论回复

评论回复使用独立 `LeadCommentReply` 聚合，不复用私信对象。有效评论线索先生成 `pending_review` 草稿和飞书卡片；人工确认后回调原子领取 `sending`，再由 `XiaohongshuCommentReplySender` 定位唯一目标评论并最多点击一次提交。最终状态只有 `sent`、`failed` 或 `result_unknown`。

平台发送与飞书/Base 同步分离：平台结果先持久化，客户跟进同步失败只能重跑同步，不得重发评论。`result_unknown` 表示点击可能已到达平台但缺少相关证据，必须人工核对且禁止盲目重试。真实上线前还必须在准备好的专用目标上先完成只读 selector probe，再获得飞书明确批准；完整操作合同见 `docs/COMMENT_REPLY_OPERATIONS.md`。

## V16 Skill Runtime

`Skill Registry -> SkillRun/SkillRunEvent -> CollectionTask(skill_run_execute) -> Worker -> Python services -> Feishu card/Base projection`。PostgreSQL Skill Run 是产品事实源；CollectionTask 只负责投递和领取执行；飞书卡片与多维表格都是可重建投影。回调事务只校验、幂等写入和入队，DeepSeek 与完整流程只在独立 Worker 中运行。同一任务卡通过消息 PATCH 持续更新。
