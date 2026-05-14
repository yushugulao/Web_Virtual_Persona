---
doc_id: timeline_main
title: 项目时间线
source_type: timeline
trust_level: synthetic
privacy_level: public
time_range: 2026
---

# 项目时间线

## 早期闭环：本地 Persona-RAG

项目最初以本地 Persona-RAG 为目标：FastAPI 后端、React 前端、Markdown corpus、FTS5 / 向量检索、RRF 融合、Ollama 本地模型和引用展示组成了最小可运行的档案对话系统。

## Persona-first 与多分身

随后系统扩展为 Persona-first runtime，并加入 Franklin、Tesla、Keller、Darwin、Paul Graham 等公开档案分身。回答不再只是资料检索摘要，而是尽量以角色第一人称、语气和思考方式进行对话。

## 账号、会话与记忆

系统加入邮箱验证注册、管理员用户管理、会话持久化、会话归档 / 删除、用户 + 会话 + 分身三重隔离记忆、user-global memory、短期滚动摘要和最近原文继承，解决多用户、多会话和长期使用的问题。

## 前端平台化

前端从单一聊天页扩展为分身平台：首页提供“与公开的虚拟分身交谈”和“我创建的虚拟分身”，公开目录支持搜索和推荐，自建分身入口支持详情、发布和创建弹窗。主题包括“黑与灰”和“蹦蹦炸弹！”两套风格。

## 用户分身创建

项目加入用户上传文件、文件解析、分身构建 skill、私有知识库、证据卡、分身内核、构建状态和可用分身入口。用户分身资料默认放在私有数据目录，不进入开源默认资料库。

## 文件读取器与 OCR-heavy

文件读取器从轻量解析升级到多格式读取：文本、代码、表格、Office、PDF、图片和扫描件都会被整理成统一文本、结构块、来源追踪和质量诊断。OCR-heavy 路线以 Docling 和 Marker/Surya CUDA 为主，保留其他高质量解析方案作为候选。

## 公网部署与可移植化

公网演示使用 AutoDL 运行后端和 Ollama 模型，阿里云 ECS 只负责 Nginx + frps 公网入口。项目已经整理出可移植部署向导、公开导出、依赖自动检测、官方来源安装、模型透明下载和开源迁移方案。
