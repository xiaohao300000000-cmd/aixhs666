# Feishu Card Callback Protocol Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 修复 V16 飞书 Card 2.0 真实点击回调。

**Architecture:** 保留单一 FastAPI HTTP 回调入口；Webhook 层负责签名和解密，Task Center 层负责动作兼容，路由层返回官方卡片响应，Worker 保持异步执行。

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy, PyCryptodome, pytest

## Global Constraints

- 不修改回调模式和公网地址。
- 不在回调中运行 DeepSeek。
- 不访问小红书或发送评论/私信。

### Task 1: Lock the failing protocol

- [x] Add tests for official signature, encrypted payload, raw-card response, and Card 2.0 `action.value.action`.
- [x] Run focused tests and confirm failures precede implementation.

### Task 2: Implement callback compatibility

- [x] Correct signature verification and add AES-CBC payload decoding.
- [x] Parse both Card 2.0 action shapes.
- [x] Return official toast/raw-card response bodies.

### Task 3: Verify and document

- [x] Run focused and full tests, compileall, and `git diff --check`.
- [x] Restart the existing API and probe local/public original routes.
- [x] Update productization, task, decision, dashboard, verification, and handoff records.
