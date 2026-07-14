# MIVE — 虚拟世界具象化引擎

**MIVE** (Mythos Imagery Visualization Engine) 是一个基于大语言模型的动态仿真系统。从已有作品与权威信息源中自动抽取世界观设定，生成可编辑的角色关系图谱，并在时间推进与事件注入下产出可追溯的对话与叙事——让用户观察一个"真正活着"的虚拟世界。

[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-green.svg)](https://fastapi.tiangolo.com/)
[![Vue 3](https://img.shields.io/badge/Vue-3.5+-brightgreen.svg)](https://vuejs.org/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## 核心能力

| 模块 | 能力 |
|------|------|
| **世界观生成** | 输入作品名或 URL，自动检索 Wikipedia / Tavily 获取权威文本，提取地点、势力、规则、事件等世界元素；支持 15 个预设模板一键创建 |
| **角色图谱** | 三层角色体系（核心 / 配角 / 群演），自适应封顶防虚构；D3.js 力导向可视化；版本历史与回滚；自然语言图谱命令栏 |
| **角色记忆** | 短期 + 长期双层记忆架构，事件推演后异步晋升，角色越聊越像"自己" |
| **事件推演** | Plan-Execute-Revise 架构：Planner → SceneOrchestrator → 对话链 → Summarizer → Reviser；SSE 实时推送，支持暂停 / 恢复 / 停止 / 回溯 |
| **角色聊天** | 两步 LLM 调用（选角 → 对话生成）；旁白条件生成；多角色人格隔离；用户扮演模式 |
| **跨平台桥接** | Discord / Telegram / Slack ↔ MIVE 世界无缝桥接（Matterbridge） |
| **国际化** | 简中 / 繁中 / 英语 / 日语 / 韩语五语言支持 |

## 技术栈

| 层级 | 方案 |
|------|------|
| 大模型 | Claude Sonnet · OpenAI GPT · Qwen · DeepSeek · Kimi · Mimo（统一适配层） |
| 后端 | Python FastAPI + SQLAlchemy Async + Alembic |
| 前端 | Vue 3 + TypeScript + Vite + Naive UI + Pinia |
| 数据库 | PostgreSQL 16 + pgvector (HNSW + BM25 + RRF 融合检索) |
| 缓存 / 队列 | Redis |
| 图谱数据库（可选） | Zep |
| 部署 | Docker Compose（一键全套） |

## 快速开始

### 前置要求

- Python 3.11+
- Node.js 20+
- PostgreSQL 16（含 `pgvector` 扩展）
- Redis 7+

### 本地开发

```bash
# 1. 克隆项目
git clone https://github.com/xiuivfbc/mive.git
cd mive

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env，填入 LLM_API_KEY、DATABASE_URL 等

# 3. 启动依赖服务（推荐 Docker Compose）
docker compose up -d postgres redis

# 4. 安装后端依赖
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# 5. 安装前端依赖
cd frontend && npm install && cd ..

# 6. 一键启动（自动跑迁移 + 前后端）
bash dev.sh
# → 后端 :8000 | 前端 :5173
```

访问 `http://localhost:5173`，首次登录使用 `.env` 中配置的 `ADMIN_USERNAME` / `ADMIN_PASSWORD`。

### Docker 一键部署

```bash
# 完整堆栈：PostgreSQL + Redis + Backend + Frontend + Matterbridge
docker compose up -d
# → 后端 :8000 | 前端 :80
```

## 环境变量

关键变量一览（完整见 `.env.example`）：

| 变量 | 说明 | 必填 |
|------|------|------|
| `DATABASE_URL` | PostgreSQL 连接串 | 是 |
| `REDIS_URL` | Redis 连接串 | 是 |
| `LLM_PROVIDER` | 模型供应商 (`anthropic` / `openai` / `qwen` / `mock` …) | 是 |
| `LLM_API_KEY` | LLM API Key | 是 |
| `LLM_MODEL` | 模型名称 | 是 |
| `ADMIN_USERNAME` | 管理员账号 | 是 |
| `ADMIN_PASSWORD` | 管理员密码 | 是 |
| `TAVILY_API_KEY` | Web 搜索 API | 否* |
| `EMBEDDING_API_KEY` | 向量嵌入 API Key | 否* |
| `ZEP_ENABLED` | 启用 Zep 知识图谱 | 否 |
| `DISCORD_BOT_TOKEN` | Discord Bot Token | 否 |
| `MATTERBRIDGE_ENABLED` | 启用 Matterbridge 桥接 | 否 |

> *开源单人自托管模式，无登录流程——启动时自动创建固定管理员账号。

## 架构概览

```
┌─────────────────────────────────────────────────────┐
│              用户交互层 (Vue 3 SPA)                   │
│  世界观页 · 角色图谱页 · 事件推演 · 聊天页            │
└──────────────────────┬──────────────────────────────┘
                       │ HTTP / SSE
┌──────────────────────▼──────────────────────────────┐
│              API Gateway (FastAPI)                    │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐          │
│  │ 世界观   │  │ 角色图谱  │  │ 事件推演  │          │
│  │ 生成 Agent│  │ 服务     │  │ Planner   │          │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘          │
│       │             │             │                 │
│  ┌────┴─────────────┴─────────────┴───────┐         │
│  │      PostgreSQL (JSONB + pgvector)       │         │
│  └─────────────────────────────────────────┘         │
└─────────────────────────────────────────────────────┘
```

详细文档见 [CLAUDE.md](CLAUDE.md)。

## 目录结构

```
/
├── src/                # FastAPI 后端
│   ├── api/            # REST 路由
│   ├── db/             # 数据库会话 / 迁移
│   ├── domain/         # 领域模型
│   ├── llm/            # LLM 适配层（Anthropic / OpenAI / Mock）
│   ├── models/         # SQLAlchemy ORM
│   ├── services/       # 业务逻辑
│   └── utils/          # 工具函数
├── frontend/src/       # Vue 3 前端
│   ├── api/            # API 客户端
│   ├── composables/    # 组合式函数
│   ├── components/     # Vue 组件
│   ├── views/          # 页面
│   └── stores/         # Pinia 状态管理
├── tests/              # 测试
├── alembic/            # 数据库迁移脚本
├── prd/                # 产品需求文档
└── docker/             # 容器化配置
```

## 许可

MIT License — 详见 [LICENSE](LICENSE)。
