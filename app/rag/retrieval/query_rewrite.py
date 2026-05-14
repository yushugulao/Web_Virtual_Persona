from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class QueryPlan:
    original_query: str
    rewritten_queries: list[str]

    @property
    def queries(self) -> list[str]:
        return [self.original_query, *self.rewritten_queries]


INTENT_EXPANSIONS: tuple[tuple[tuple[str, ...], str], ...] = (
    (
        ("开始写代码", "写代码前", "同学", "队友"),
        "同事评价 协作风格 开始写代码前 需求 任务 具体问题 先把问题写清楚",
    ),
    (
        ("事实优先的价值观", "降低语气强度", "回答语气"),
        "价值观 事实优先 证据 不确定性 降低语气强度 回答边界 个人简介",
    ),
    (
        ("查论文", "读论文", "开源项目", "调研", "修正设计", "校准"),
        "思维风格 用调研校准直觉 查论文 开源项目 RAGFlow PrivateGPT ObsidianRAG 修正设计",
    ),
    (
        ("声音指纹", "说话风格", "说话方式", "口吻", "语气", "句式节奏", "像本人"),
        "声音指纹 思维风格 说话方式 口吻 语气 句式节奏 真实文本锚点 谨慎 事实优先 自然史节奏",
    ),
    (
        (
            "怎样安排",
            "一天的事情",
            "日常",
            "习惯",
            "日课",
            "作息",
            "怎样判断",
            "新想法",
            "值不值得实验",
            "怎样理解",
            "怎样表达",
            "触觉",
            "观察习惯",
        ),
        "思维风格 声音指纹 说话方式 习惯 日课 自我改进 判断 实验 触觉 语言 观察",
    ),
    (
        ("项目记忆", "长期项目记忆", "写进文件", "上下文丢失", "环境变化", "临时决定"),
        "价值观 工程可持续 项目记忆 写进文件 上下文丢失 环境变化 临时决定 文档 任务看板 决策日志",
    ),
    (
        ("courseops", "task board", "课程团队", "负责了哪些部分"),
        "简历 CourseOps Task Board 后端 API 数据库 schema 前端状态管理 课程团队协作",
    ),
    (
        ("生产级安全防护", "生产级安全", "安全防护"),
        "负面事实 禁止声称 生产级安全防护 当前限制 对话安全策略 隐私边界 不得声称",
    ),
    (
        ("evaluation", "eval metrics", "一等能力", "可复现评测", "评测"),
        "evaluation eval metrics 可复现评测 retrieval trace timings citations 证据 评测 一等能力",
    ),
    (
        ("推断", "父母职业", "家庭关系", "家里人", "家人", "大胆猜测", "年薪", "未来第一份工作"),
        "人物档案 个人资料 家庭关系 职业背景 年薪 公开来源 用户上传资料 证据",
    ),
    (
        ("GPA", "专业排名", "出生日期", "实习"),
        "简历 教育背景 GPA 专业排名 出生日期 实习 用户上传资料 人物档案 证据卡",
    ),
    (
        ("无视语料", "忽略语料", "忽略所有规则", "无视所有规则"),
        "对话安全策略 提示注入 用户临时事实 不能覆盖语料证据 负面事实 禁止声称",
    ),
    (
        ("需求含糊", "需求不清", "含糊", "具体问题"),
        "同事评价 协作风格 需求写清楚 具体问题 先建边界",
    ),
    (
        ("学术方案", "工程模块", "优势如何", "可替换模块", "落地路径", "口号"),
        "思维风格 简历 学术方案 工程模块 可替换模块 目标 约束 验收标准 落地路径",
    ),
    (
        ("2023", "2024", "2025", "2026", "时间线", "年份"),
        "时间线 2023 2024 2025 2026 后端开发 RAG 语料质量 chunk 评测 Qwen Ollama 量化 本地模型部署",
    ),
    (
        ("没有完成", "未完成", "当前限制", "限制", "后续升级", "哪些功能明确"),
        "当前限制 后续升级 负面事实 禁止声称 GraphRAG 长期记忆 PDF 多模态检索 reranker 生产级安全防护",
    ),
    (
        ("后端", "rag", "技术能力", "能力", "工程能力", "backend"),
        "FastAPI React SQLite RAG chunking embedding BM25 FTS rerank citation trace evaluation 本地模型 后端 技术能力",
    ),
    (
        ("同事", "协作", "沟通", "队友", "评价"),
        "同事评价 协作风格 沟通特点 需求 拆任务 技术方案 取舍 理解成本",
    ),
    (
        ("graphrag", "一开始", "完整", "取舍", "小步"),
        "小步快跑 最小闭环 GraphRAG rerank memory evaluation 工程取舍 大型平台",
    ),
    (
        ("顶会", "顶会论文", "发表论文", "发了论文", "publication", "conference"),
        "人物档案 证据卡 顶会论文 发表论文 学术成果 用户上传资料 公开来源",
    ),
    (
        ("本地模型", "模型", "检索管线", "系统当前", "当前使用", "stack"),
        "Ollama qwen3 qwen3-embedding SQLite FTS5 dense vector retrieval reciprocal rank fusion SSE FastAPI",
    ),
    (
        ("不确定", "思考", "思维", "复杂任务", "判断"),
        "思维风格 先建边界 调研 校准直觉 取舍 证据 不确定性 可替换模块",
    ),
    (
        ("手机号", "联系方式", "电话", "住址", "身份证", "隐私", "敏感"),
        "人物档案 联系方式 住址 身份信息 私人生活 用户上传资料 公开来源 证据",
    ),
    (
        ("银行卡", "账号", "密码", "系统提示词", "隐藏推理", "chain-of-thought", "system prompt", "ignore"),
        "对话安全策略 提示注入 隐私边界 系统提示词 隐藏推理 账号密码 敏感信息 拒绝 证据优先",
    ),
    (
        ("适合", "承担", "任务", "项目类型"),
        "适合任务 复杂需求 后端接口 RAG 原型 工程规范 FastAPI 可持续文档",
    ),
)


def build_query_plan(query: str, *, max_rewrites: int = 3) -> QueryPlan:
    normalized = query.lower()
    rewrites: list[str] = []
    for triggers, expansion in INTENT_EXPANSIONS:
        if any(trigger in normalized for trigger in triggers):
            rewrites.append(expansion)
        if len(rewrites) >= max_rewrites:
            break
    return QueryPlan(original_query=query, rewritten_queries=dedupe(rewrites))


def dedupe(items: list[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for item in items:
        key = " ".join(item.lower().split())
        if key in seen:
            continue
        seen.add(key)
        output.append(item)
    return output
