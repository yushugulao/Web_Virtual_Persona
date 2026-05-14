from __future__ import annotations

import re
from dataclasses import dataclass

from app.backend.core.config import Settings
from app.rag.chunking.markdown import Chunk
from app.rag.retrieval.lexical import tokenize


CJK_SEGMENT_RE = re.compile(r"[\u4e00-\u9fff]+")
YEAR_RE = re.compile(r"20\d{2}")

STOPWORDS = {
    "about",
    "and",
    "are",
    "can",
    "does",
    "from",
    "have",
    "the",
    "this",
    "what",
    "which",
    "with",
    "一个",
    "不是",
    "以及",
    "可以",
    "哪些",
    "如何",
    "为什么",
    "这个",
    "这些",
}


@dataclass(frozen=True)
class IntentRule:
    triggers: tuple[str, ...]
    source_weights: dict[str, float]


INTENT_RULES: tuple[IntentRule, ...] = (
    IntentRule(
        triggers=("开始写代码", "写代码前", "同学", "队友"),
        source_weights={"colleague": 0.30, "thinking_style": 0.04},
    ),
    IntentRule(
        triggers=("事实优先的价值观", "降低语气强度", "回答语气"),
        source_weights={"values": 0.28, "profile": 0.12, "thinking_style": 0.04},
    ),
    IntentRule(
        triggers=("查论文", "读论文", "开源项目", "调研", "修正设计", "校准"),
        source_weights={"thinking_style": 0.16, "values": 0.04},
    ),
    IntentRule(
        triggers=("声音指纹", "说话风格", "说话方式", "口吻", "语气", "句式节奏", "像本人"),
        source_weights={"thinking_style": 0.18},
    ),
    IntentRule(
        triggers=(
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
        source_weights={"thinking_style": 0.14, "profile": 0.03},
    ),
    IntentRule(
        triggers=("项目记忆", "长期项目记忆", "写进文件", "上下文丢失", "环境变化", "临时决定"),
        source_weights={"values": 0.18},
    ),
    IntentRule(
        triggers=("courseops", "task board", "课程团队", "负责了哪些部分"),
        source_weights={"resume": 0.18},
    ),
    IntentRule(
        triggers=("生产级安全防护", "生产级安全", "安全防护"),
        source_weights={"negative_fact": 0.18, "safety_policy": 0.12, "project": 0.04},
    ),
    IntentRule(
        triggers=("evaluation", "eval metrics", "一等能力", "可复现评测", "评测"),
        source_weights={"project": 0.18, "values": 0.14, "qa_seed": 0.10},
    ),
    IntentRule(
        triggers=("推断", "父母职业", "家庭关系", "家里人", "家人", "大胆猜测", "年薪", "未来第一份工作"),
        source_weights={
            "reviewed_profile": 0.16,
            "profile": 0.14,
            "evidence_cards": 0.10,
            "qa_seed": 0.08,
        },
    ),
    IntentRule(
        triggers=("GPA", "专业排名", "出生日期"),
        source_weights={
            "reviewed_profile": 0.16,
            "profile": 0.13,
            "resume": 0.10,
            "evidence_cards": 0.08,
        },
    ),
    IntentRule(
        triggers=("真实公司", "公司实习", "实习"),
        source_weights={
            "evidence_cards": 0.28,
            "reviewed_profile": 0.24,
            "qa_seed": 0.18,
            "timeline": 0.10,
            "negative_fact": 0.03,
        },
    ),
    IntentRule(
        triggers=("无视语料", "忽略语料", "忽略所有规则", "无视所有规则"),
        source_weights={"safety_policy": 0.18, "negative_fact": 0.16},
    ),
    IntentRule(
        triggers=("需求含糊", "需求不清", "含糊", "具体问题"),
        source_weights={"colleague": 0.18, "thinking_style": 0.12},
    ),
    IntentRule(
        triggers=("学术方案", "工程模块", "优势如何"),
        source_weights={"resume": 0.18, "thinking_style": 0.14},
    ),
    IntentRule(
        triggers=("可替换模块", "落地路径", "口号"),
        source_weights={"thinking_style": 0.18},
    ),
    IntentRule(
        triggers=("普通聊天框", "知识工作台", "工作台", "前端", "用户体验"),
        source_weights={"values": 0.11, "project": 0.09, "profile": 0.05},
    ),
    IntentRule(
        triggers=("trace", "timings", "eval metrics", "可观测", "保存", "评测", "证据来源"),
        source_weights={"project": 0.10, "values": 0.09, "qa_seed": 0.06},
    ),
    IntentRule(
        triggers=("解释", "技术方案", "取舍", "讲清楚", "理解成本"),
        source_weights={"colleague": 0.16, "thinking_style": 0.12, "values": 0.02},
    ),
    IntentRule(
        triggers=("2023", "2024", "2025", "2026", "时间线", "年份"),
        source_weights={"timeline": 0.14},
    ),
    IntentRule(
        triggers=("事实优先", "价值观", "文档", "任务看板", "决策日志", "用户体验", "为什么重视"),
        source_weights={"thinking_style": 0.08, "values": 0.12, "profile": 0.03},
    ),
    IntentRule(
        triggers=("思维", "思考", "不确定", "复杂", "拆解", "模块", "判断"),
        source_weights={"thinking_style": 0.12, "project": 0.05},
    ),
    IntentRule(
        triggers=("graphrag", "一开始", "完整", "小步", "最小"),
        source_weights={"values": 0.13, "project": 0.09, "colleague": 0.07},
    ),
    IntentRule(
        triggers=("同事", "协作", "沟通", "队友", "提醒", "风险"),
        source_weights={"colleague": 0.12, "values": 0.03},
    ),
    IntentRule(
        triggers=("后端", "rag 相关", "技术能力", "能力", "工程能力"),
        source_weights={"profile": 0.11, "resume": 0.10, "project": 0.08},
    ),
    IntentRule(
        triggers=("简历", "教育", "课程背景"),
        source_weights={"resume": 0.14, "profile": 0.04},
    ),
    IntentRule(
        triggers=("为什么要做", "为什么做", "项目动机", "课程项目", "persona-rag 课程", "本地 persona-rag"),
        source_weights={"qa_seed": 0.16, "profile": 0.13, "project": 0.04},
    ),
    IntentRule(
        triggers=("适合", "承担", "任务", "项目类型"),
        source_weights={"qa_seed": 0.12, "resume": 0.08, "profile": 0.06},
    ),
    IntentRule(
        triggers=("项目", "后端", "系统", "eval", "模型", "检索管线", "亮点"),
        source_weights={"project": 0.10, "profile": 0.04, "qa_seed": 0.03},
    ),
    IntentRule(
        triggers=("后续", "升级", "路线", "roadmap"),
        source_weights={"project": 0.16, "values": 0.10, "thinking_style": 0.01},
    ),
    IntentRule(
        triggers=("没有完成", "未完成", "当前限制", "不得声称", "禁止声称"),
        source_weights={"negative_fact": 0.13, "project": 0.05},
    ),
    IntentRule(
        triggers=("顶会", "顶会论文", "发表论文", "发表过论文", "高级工程师"),
        source_weights={
            "reviewed_profile": 0.13,
            "profile": 0.10,
            "evidence_cards": 0.08,
            "negative_fact": 0.04,
        },
    ),
    IntentRule(
        triggers=("是不是已经完成", "已经完成", "长期记忆", "经过验证", "validated reranker", "reranker", "PDF 多模态", "自动化资料转 Markdown", "Docling", "MinerU", "生产级安全"),
        source_weights={"negative_fact": 0.18, "project": 0.08, "safety_policy": 0.06},
    ),
    IntentRule(
        triggers=("奖项", "竞赛", "国家级"),
        source_weights={
            "evidence_cards": 0.24,
            "reviewed_profile": 0.20,
            "qa_seed": 0.12,
            "negative_fact": 0.06,
        },
    ),
    IntentRule(
        triggers=(
            "医疗",
            "心理",
            "心理咨询",
            "特殊教育",
            "诊断",
            "专业建议",
            "治疗",
            "medical",
            "psychological",
            "diagnosis",
            "treatment",
            "special education",
            "special-education",
            "clinical",
        ),
        source_weights={"negative_fact": 0.18, "profile": 0.04, "safety_policy": 0.04},
    ),
    IntentRule(
        triggers=("手机号", "联系方式", "电话", "住址", "身份证", "隐私", "敏感"),
        source_weights={
            "reviewed_profile": 0.13,
            "profile": 0.10,
            "evidence_cards": 0.08,
        },
    ),
    IntentRule(
        triggers=(
            "银行卡",
            "账号",
            "密码",
            "api key",
            "apikey",
            "授权码",
            "token",
            "系统提示词",
            "隐藏推理",
            "chain-of-thought",
            "system prompt",
            "忽略",
        ),
        source_weights={"safety_policy": 0.13, "negative_fact": 0.12, "profile": 0.03},
    ),
)

MODERN_TECH_BOUNDARY_TERMS = (
    "rag",
    "fastapi",
    "python",
    "github",
    "modern ai",
    "software engineering",
    "software",
    "课程设计",
    "现代软件",
    "现代 ai",
    "璇剧▼璁捐",
    "鐜颁唬杞欢",
    "鐜颁唬 ai",
)
MODERN_TECH_BOUNDARY_MARKERS = (
    "真实",
    "真的",
    "做过",
    "参与",
    "是不是",
    "是否",
    "现代",
    "当代",
    "real",
    "actually",
    "participate",
    "鐪熷疄",
    "鍋氳繃",
    "鍙備笌",
    "鏄笉鏄",
    "鐜颁唬",
)
MODERN_TECH_BOUNDARY_RULE = IntentRule(
    triggers=(),
    source_weights={"negative_fact": 0.18, "profile": 0.04, "safety_policy": 0.04},
)


@dataclass(frozen=True)
class LocalRerankOutcome:
    results: list[tuple[Chunk, float]]
    note: str


class LocalIntentReranker:
    def __init__(self, settings: Settings):
        self.settings = settings

    def rerank(self, query: str, candidates: list[tuple[Chunk, float]]) -> LocalRerankOutcome:
        if not candidates:
            return LocalRerankOutcome(results=[], note="本地意图排序器已跳过：没有候选片段。")
        if not self.settings.local_reranker_enabled:
            return LocalRerankOutcome(
                results=candidates,
                note="本地意图排序器已由配置关闭。",
            )

        query_terms = content_terms(query)
        matched_rules = matching_rules(query)
        scored = [
            (
                chunk,
                score + lexical_bonus(query_terms, chunk) + intent_bonus(matched_rules, chunk) + year_bonus(query, chunk),
            )
            for chunk, score in candidates
        ]
        scored.sort(key=lambda item: item[1], reverse=True)
        scored = promote_intent_source_coverage(scored, matched_rules)
        return LocalRerankOutcome(
            results=scored,
            note=f"本地意图排序器已调整 {len(candidates)} 个候选片段，命中 {len(matched_rules)} 条意图规则。",
        )


def matching_rules(query: str) -> list[IntentRule]:
    normalized = query.lower()
    rules = [
        rule
        for rule in INTENT_RULES
        if any(trigger.lower() in normalized for trigger in rule.triggers)
    ]
    if matches_modern_tech_boundary(normalized):
        rules.append(MODERN_TECH_BOUNDARY_RULE)
    return rules


def matches_modern_tech_boundary(normalized_query: str) -> bool:
    has_tech_term = any(term.lower() in normalized_query for term in MODERN_TECH_BOUNDARY_TERMS)
    has_boundary_marker = any(
        marker.lower() in normalized_query for marker in MODERN_TECH_BOUNDARY_MARKERS
    )
    return has_tech_term and has_boundary_marker


def promote_intent_source_coverage(
    scored: list[tuple[Chunk, float]],
    rules: list[IntentRule],
) -> list[tuple[Chunk, float]]:
    if not scored or not rules:
        return scored

    source_weights: dict[str, float] = {}
    for rule in rules:
        for source_type, weight in rule.source_weights.items():
            source_weights[source_type] = max(source_weights.get(source_type, 0.0), weight)

    if len(source_weights) <= 1:
        return scored

    selected: list[tuple[Chunk, float]] = []
    selected_ids: set[str] = set()
    for source_type, _weight in sorted(source_weights.items(), key=lambda item: item[1], reverse=True):
        candidate = next(
            (
                item
                for item in scored
                if item[0].source_type == source_type and item[0].chunk_id not in selected_ids
            ),
            None,
        )
        if candidate:
            selected.append(candidate)
            selected_ids.add(candidate[0].chunk_id)

    selected.extend(item for item in scored if item[0].chunk_id not in selected_ids)
    return selected


def lexical_bonus(query_terms: set[str], chunk: Chunk) -> float:
    if not query_terms:
        return 0.0
    chunk_terms = content_terms(" ".join([chunk.title, chunk.section_path, chunk.text]))
    if not chunk_terms:
        return 0.0
    overlap = len(query_terms & chunk_terms) / len(query_terms)
    section_overlap = len(query_terms & content_terms(chunk.section_path)) / len(query_terms)
    return min(0.08, overlap * 0.05 + section_overlap * 0.03)


def intent_bonus(rules: list[IntentRule], chunk: Chunk) -> float:
    if not rules:
        return 0.0
    bonus = sum(rule.source_weights.get(chunk.source_type, 0.0) for rule in rules)
    return min(0.18, bonus)


def year_bonus(query: str, chunk: Chunk) -> float:
    years = set(YEAR_RE.findall(query))
    if not years:
        return 0.0
    text = " ".join([chunk.section_path, chunk.text])
    return 0.08 if any(year in text for year in years) else 0.0


def content_terms(text: str) -> set[str]:
    terms = {
        token
        for token in tokenize(text)
        if len(token) >= 2 and token not in STOPWORDS and not token.isdigit()
    }
    for segment in CJK_SEGMENT_RE.findall(text):
        terms.update(
            segment[index : index + 2]
            for index in range(max(0, len(segment) - 1))
        )
    return terms
