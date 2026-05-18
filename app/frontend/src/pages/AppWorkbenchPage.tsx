import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";
import {
  Activity,
  Brain,
  ChevronDown,
  ChevronUp,
  CircleSlash,
  Copy,
  Gauge,
  MessageSquareText,
  RotateCcw,
  Search,
  Settings,
  ShieldCheck,
  ThumbsDown,
  ThumbsUp,
  UserCog,
  Volume2
} from "lucide-react";
import {
  archiveChatSession,
  createChatSession,
  deleteChatSession,
  fetchBrowserAcceptanceMatrix,
  fetchChatSessionMessages,
  fetchChatSessions,
  fetchCurrentUser,
  fetchEvidenceStats,
  fetchEvalRuns,
  fetchMemoryItems,
  fetchMemoryStats,
  fetchPersonaFeedbackStats,
  fetchPersonaMaterials,
  fetchPersonas,
  fetchStatus,
  fetchThemePreference,
  fetchUserPersonaDetail,
  logoutAccount,
  proposeMemory,
  releaseRuntimeModels,
  runEval,
  setAuthTokenProvider,
  streamChat,
  submitPersonaTurnFeedback,
  restoreChatSessionApi,
  updateThemePreference,
  updateMemoryStatus
} from "../api";
import { AuthGateway } from "../components/auth/AuthGateway";
import { PersonaPlatformGateway } from "../components/PersonaPlatformGateway";
import {
  EvidenceBlock,
  EvaluationPanel,
  MaterialExplorer,
  MemoryPanel,
  SourceRegistry,
  TraceDetails
} from "../components/side-panels/SidePanels";
import { ThemeArtifacts } from "../components/ThemeArtifacts";
import { SessionDrawer } from "../components/chat/SessionDrawer";
import { SettingsPanel } from "../components/settings/SettingsPanel";
import { HiddenThinkingPanel, ProcessTimeline, ThinkingBudgetProgress } from "../components/runtime/RuntimePanels";
import { AdminUsersPage } from "./AdminUsersPage";
import { DEFAULT_THEME, isUiThemeId, type UiThemeId } from "../themes";
import { fallbackPersonas } from "../frontendFallbacks";
import type {
  AuthUser,
  BrowserAcceptanceCase,
  BrowserAcceptanceMatrixResponse,
  ChatDiagnostics,
  ChatResponse,
  ChatSessionSummary,
  Citation,
  EvidenceCardStats,
  EvalRunListItem,
  FeedbackIssue,
  FeedbackSeverity,
  HiddenThinkingDeltaEvent,
  HiddenThinkingEvent,
  MemoryItem,
  MemoryStatsResponse,
  PersonaTurnFeedbackStatsResponse,
  PersonaMaterialDocument,
  PersonaProfile,
  RetrievalTrace,
  StreamStageEvent,
  StatusResponse,
  ThinkingEffort,
  UiMessage,
  UserPersonaDetail,
} from "../types";

const thinkingEffortOptions: {
  value: ThinkingEffort;
  label: string;
  multiplier: number;
  tokenMultiplier: number;
  refinePasses: number;
}[] = [
  { value: "low", label: "低", multiplier: 1, tokenMultiplier: 1, refinePasses: 0 },
  { value: "medium", label: "中", multiplier: 2, tokenMultiplier: 1.4, refinePasses: 0 },
  { value: "high", label: "高", multiplier: 10, tokenMultiplier: 2, refinePasses: 2 }
];

const TURN_FEEDBACK_SAVED_NOTICE = "这轮反馈已保存，这将用于后续改进";

function readStoredThinkingEffort(): ThinkingEffort {
  const stored = window.localStorage.getItem("persona_rag_thinking_effort");
  if (stored === "medium" || stored === "high") return stored;
  return "low";
}

function thinkingEffortLabel(value: ThinkingEffort) {
  return thinkingEffortOptions.find((item) => item.value === value)?.label ?? "低";
}

function isPlaceholderSessionTitle(title?: string | null) {
  const normalized = (title ?? "").trim();
  return !normalized || normalized === "未命名会话" || normalized === "未命名对话";
}

function titleFromFirstUserMessage(messages: UiMessage[]) {
  const firstUserMessage = messages.find((message) => message.role === "user")?.content.trim() ?? "";
  if (!firstUserMessage) return "";
  return firstUserMessage.length > 34 ? `${firstUserMessage.slice(0, 33).trimEnd()}…` : firstUserMessage;
}

function runtimePlan(status: StatusResponse | null | undefined, effort: ThinkingEffort) {
  return status?.effort_runtime_plans?.[effort];
}

function thinkingEffortTimeoutSeconds(baseTimeoutSeconds: number | undefined, effort: ThinkingEffort) {
  const base = baseTimeoutSeconds ?? 480;
  const option = thinkingEffortOptions.find((item) => item.value === effort) ?? thinkingEffortOptions[0];
  return base * option.multiplier;
}

function thinkingEffortTokenBudget(baseTokenBudget: number | undefined, effort: ThinkingEffort) {
  const base = baseTokenBudget ?? 1280;
  const option = thinkingEffortOptions.find((item) => item.value === effort) ?? thinkingEffortOptions[0];
  return Math.round(base * option.tokenMultiplier);
}

function thinkingEffortRefinePasses(status: StatusResponse | null | undefined, effort: ThinkingEffort) {
  const option = thinkingEffortOptions.find((item) => item.value === effort) ?? thinkingEffortOptions[0];
  if (status?.quality_generation_model) {
    const minEffort = status.quality_generation_min_effort ?? "high";
    if (
      thinkingEffortRank(effort) >= thinkingEffortRank(minEffort) &&
      status.quality_generation_refinement_passes !== undefined &&
      status.quality_generation_refinement_passes !== null
    ) {
      return status.quality_generation_refinement_passes;
    }
  }
  return option.refinePasses;
}

function thinkingEffortRunLabel(effort: ThinkingEffort, status?: StatusResponse | null) {
  const plan = runtimePlan(status, effort);
  const refinePasses = plan?.refinement_passes ?? thinkingEffortRefinePasses(status, effort);
  const thinkLabel = plan?.think ? "有思考" : "直接回答";
  return refinePasses > 0
    ? `${thinkLabel} / ${refinePasses} 轮精修`
    : `${thinkLabel} / 单轮`;
}

function thinkingEffortRank(effort: ThinkingEffort) {
  if (effort === "high") return 2;
  if (effort === "medium") return 1;
  return 0;
}

function activeGenerationModel(status: StatusResponse | null | undefined, effort: ThinkingEffort) {
  const plan = runtimePlan(status, effort);
  if (plan?.model) return plan.model;
  if (!status?.quality_generation_model) return status?.generation_model ?? "qwen3:8b";
  const minEffort = status.quality_generation_min_effort ?? "high";
  if (thinkingEffortRank(effort) >= thinkingEffortRank(minEffort)) {
    return status.quality_generation_model;
  }
  return status.generation_model;
}

function isQualityModelActive(status: StatusResponse | null | undefined, effort: ThinkingEffort) {
  if (!status?.quality_generation_model) return false;
  const minEffort = status.quality_generation_min_effort ?? "high";
  return thinkingEffortRank(effort) >= thinkingEffortRank(minEffort);
}

function activeModelReady(status: StatusResponse | null | undefined, effort: ThinkingEffort) {
  if (!status) return false;
  const plan = runtimePlan(status, effort);
  if (plan) return Boolean(plan.model_ready);
  if (isQualityModelActive(status, effort)) return Boolean(status.quality_generation_model_ready);
  return status.generation_model_ready;
}

function rerankStatusLabel(status: StatusResponse | null | undefined) {
  if (!status) return "等待中";
  if (status.reranker_enabled) {
    return status.reranker_model_ready ? "模型重排" : "模型待加载";
  }
  if (status.local_reranker_enabled) return "规则重排";
  return "关闭";
}

function postPersonaAlignmentLabel(status: StatusResponse | null | undefined) {
  if (!status) return "等待中";
  const count = status.post_persona_alignment_event_rows ?? 0;
  return `${status.post_persona_alignment_enabled ? "开启" : "关闭"} / ${count}`;
}

function personaFirstLabel(status: StatusResponse | null | undefined) {
  if (!status) return "等待中";
  const count = status.persona_first_event_rows ?? 0;
  return `${status.persona_first_enabled ? "开启" : "回退"} / ${count}`;
}

function retrievalStackLabel(status: StatusResponse | null | undefined) {
  if (!status) return "等待中";
  const retrievalModeLabels: Record<string, string> = {
    hybrid: "混合检索",
    sparse: "关键词检索",
    dense: "语义检索"
  };
  const parts = [
    retrievalModeLabels[status.retrieval_mode] ?? displayArchiveText(status.retrieval_mode ?? "混合检索")
  ];
  if (status.query_rewrite_enabled) parts.push("问题改写");
  if (status.source_selector_enabled) parts.push("来源选择");
  return parts.join(" / ");
}

function formatPercent(value: number | undefined) {
  if (value === undefined || Number.isNaN(value)) return "等待中";
  return `${Math.round(value * 100)}%`;
}

function formatLatency(ms: number | undefined) {
  if (ms === undefined || Number.isNaN(ms)) return "等待中";
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)} 秒`;
  return `${Math.round(ms)} 毫秒`;
}

function diagnosticsWithoutFinalAnswerSource(
  response: ChatResponse,
  existing?: ChatDiagnostics | null
): ChatDiagnostics {
  const diagnostics = response.diagnostics ?? existing;
  const hiddenThinkingEvents = diagnostics?.hidden_thinking_events ?? [];
  return {
    enabled: diagnostics?.enabled ?? true,
    hidden_thinking_events: hiddenThinkingEvents,
    visible_answer_sources: [],
    final_answer_source: null,
    thinking_budget: response.diagnostics?.thinking_budget ?? existing?.thinking_budget ?? null,
    thinking_tokens_observed:
      response.diagnostics?.thinking_tokens_observed ?? existing?.thinking_tokens_observed ?? null,
    thinking_budget_ratio:
      response.diagnostics?.thinking_budget_ratio ?? existing?.thinking_budget_ratio ?? null,
    thinking_budget_stop_reason:
      response.diagnostics?.thinking_budget_stop_reason ?? existing?.thinking_budget_stop_reason ?? null,
    thinking_budget_overshoot_tokens:
      response.diagnostics?.thinking_budget_overshoot_tokens ??
      existing?.thinking_budget_overshoot_tokens ??
      null
  };
}

function formatOptionalPercent(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "等待中";
  return `${Math.round(value)}%`;
}

function formatOptionalMb(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "等待中";
  if (value >= 1024) return `${(value / 1024).toFixed(1)} GB`;
  return `${Math.round(value)} MB`;
}

function formatOptionalGb(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "等待中";
  return `${value.toFixed(1)} GB`;
}

function gpuMemoryLabel(resourceUsage: StatusResponse["resource_usage"]) {
  if (!resourceUsage?.gpu_name) return "未检测到 NVIDIA GPU";
  return `${resourceUsage.gpu_name} GPU ${formatOptionalMb(resourceUsage.gpu_memory_used_mb)} / ${formatOptionalMb(
    resourceUsage.gpu_memory_total_mb
  )}`;
}

function isAbortError(error: unknown) {
  return error instanceof DOMException && error.name === "AbortError";
}

function formatRunTime(ts: number | undefined) {
  if (!ts) return "无";
  const millis = ts > 10_000_000_000 ? ts : ts * 1000;
  return new Date(millis).toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit"
  });
}

type SidePanelView = "chat" | "archive" | "memory" | "evaluation";

type ActiveTurn = {
  turnId: string;
  controller: AbortController;
  assistantId: string;
  startedAt: number;
  personaId: string;
  sessionId: string;
  thinkingEffort: ThinkingEffort;
  cancelled: boolean;
};

type TurnMeta = {
  persona_id: string;
  persona_name: string;
  session_id: string;
  thinking_effort: ThinkingEffort;
};

function mergeHiddenThinkingDelta(
  events: HiddenThinkingEvent[],
  deltaEvent: HiddenThinkingDeltaEvent
): HiddenThinkingEvent[] {
  if (
    deltaEvent.kind === "final_answer_selected" ||
    deltaEvent.kind === "visible_answer_source" ||
    deltaEvent.kind === "thinking_budget_progress"
  ) {
    return events;
  }
  const eventId = deltaEvent.event_id ?? `runtime-${deltaEvent.phase ?? "model"}-${deltaEvent.kind}`;
  const phase = deltaEvent.phase ?? "model_call";
  const model = deltaEvent.model ?? "unknown";
  const provider = deltaEvent.provider ?? "unknown";
  const source = deltaEvent.source ?? deltaEvent.kind;
  const sequence = deltaEvent.sequence ?? events.length + 1;
  const elapsedMs = deltaEvent.elapsed_ms ?? 0;
  const delta =
    deltaEvent.delta ??
    `${deltaEvent.kind}: ${phase}${elapsedMs ? ` (${Math.round(elapsedMs)}ms)` : ""}\n`;
  const existing = events.find((event) => event.event_id === eventId);
  if (!existing) {
    return [
      ...events,
      {
        event_id: eventId,
        phase,
        model,
        provider,
        source,
        content: delta,
        elapsed_ms: elapsedMs,
        sequence
      }
    ].sort((left, right) => left.sequence - right.sequence);
  }
  return events.map((event) =>
    event.event_id === eventId
      ? {
          ...event,
          content: `${event.content}${delta}`,
          elapsed_ms: elapsedMs,
          source
        }
      : event
  );
}

function mergeRuntimeDiagnosticDelta(
  existing: ChatDiagnostics | null | undefined,
  deltaEvent: HiddenThinkingDeltaEvent,
  includeHiddenThinking: boolean
): ChatDiagnostics {
  return {
    ...(existing ?? {}),
    enabled: includeHiddenThinking ? true : existing?.enabled ?? false,
    final_answer_source: null,
    visible_answer_sources: [],
    hidden_thinking_events: includeHiddenThinking
      ? mergeHiddenThinkingDelta(existing?.hidden_thinking_events ?? [], deltaEvent)
      : existing?.hidden_thinking_events ?? [],
    thinking_budget: deltaEvent.thinking_budget ?? existing?.thinking_budget ?? null,
    thinking_tokens_observed:
      deltaEvent.thinking_tokens_observed ?? existing?.thinking_tokens_observed ?? null,
    thinking_budget_ratio: deltaEvent.thinking_budget_ratio ?? existing?.thinking_budget_ratio ?? null,
    thinking_budget_stop_reason:
      deltaEvent.thinking_budget_stop_reason ?? existing?.thinking_budget_stop_reason ?? null,
    thinking_budget_overshoot_tokens:
      deltaEvent.thinking_budget_overshoot_tokens ?? existing?.thinking_budget_overshoot_tokens ?? null
  };
}

const sidePanelMeta: Record<SidePanelView, { eyebrow: string; title: string }> = {
  chat: { eyebrow: "依据", title: "回答依据" },
  archive: { eyebrow: "档案", title: "人物档案" },
  memory: { eyebrow: "记忆", title: "当前会话" },
  evaluation: { eyebrow: "评测", title: "质量检查" }
};

const DIAGNOSTIC_FLUSH_INTERVAL_MS = 180;

const turnFeedbackOptions: {
  issue: FeedbackIssue;
  severity: FeedbackSeverity;
  label: string;
  title: string;
}[] = [
  { issue: "cardiness", severity: "high", label: "像资料卡", title: "回答听起来像在复述资料卡片" },
  { issue: "lecture", severity: "high", label: "说教", title: "回答过于说教" },
  { issue: "too_long", severity: "medium", label: "太长", title: "回答比需要的更长" },
  { issue: "unnatural", severity: "high", label: "不自然", title: "回答不像自然对话" },
  { issue: "memory_error", severity: "high", label: "记忆错用", title: "上下文或记忆使用不正确" },
  { issue: "era_boundary_error", severity: "high", label: "时代越界", title: "历史人物时代边界错误" },
  { issue: "good", severity: "low", label: "喜欢", title: "这轮回答有帮助" },
  { issue: "other", severity: "high", label: "不喜欢", title: "这轮回答不理想" }
];

function feedbackIssueLabel(issue: string) {
  return turnFeedbackOptions.find((item) => item.issue === issue)?.label ?? issue;
}

function feedbackSeverityLabel(severity: string) {
  if (severity === "high") return "高";
  if (severity === "medium") return "中";
  if (severity === "low") return "低";
  return severity;
}

function countLabel(count: number, unit: string) {
  return `${count} ${unit}`;
}

const sourceTypeLabels: Record<string, string> = {
  profile: "人物档案",
  resume: "简历",
  project: "项目",
  values: "价值观",
  thinking_style: "思考方式",
  colleague: "同事视角",
  qa_seed: "问答种子",
  negative_fact: "边界记录",
  memory: "记忆",
  converted_pdf: "转换文档",
  safety_policy: "对话边界",
  loading: "读取中"
};

const trustLevelLabels: Record<string, string> = {
  verified: "已核验",
  synthetic: "合成",
  inferred: "推断",
  user_memory: "记忆"
};

const privacyLevelLabels: Record<string, string> = {
  public: "公开",
  private: "私有",
  sensitive: "敏感"
};

function sourceTypeLabel(value: string) {
  return sourceTypeLabels[value] ?? displayArchiveText(value);
}

function trustLevelLabel(value: string) {
  return trustLevelLabels[value] ?? displayArchiveText(value);
}

function privacyLevelLabel(value: string) {
  return privacyLevelLabels[value] ?? displayArchiveText(value);
}

function hostLabel(url: string) {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

const archiveTextReplacements: [string, string][] = [
  ["虚拟分身", "交谈对象"],
  ["语料", "档案"],
  ["当前材料", "已审阅档案"],
  ["证据显示", "档案显示"],
  ["Retrieval mode", "档案匹配"],
  ["retrieval mode", "档案匹配"],
  ["Evidence Policy", "证据策略"],
  ["source family", "来源类别"],
  ["citation", "引用"],
  ["citations", "引用"],
  ["query rewrite", "问题改写"],
  ["source selector", "片段选择"],
  ["hybrid retrieval", "混合检索"],
  ["keyword retrieval", "关键词检索"],
  ["semantic retrieval", "语义检索"]
];

function displayArchiveText(value: string): string {
  return archiveTextReplacements
    .reduce(
      (current, [needle, replacement]) => current.split(needle).join(replacement),
      value
    )
    .replace(
      /\b(Franklin|Tesla|Keller|Darwin)\s+Evidence Cards\s+(\d+)\b/gi,
      (_match, prefix: string, batch: string) =>
        `${evidenceCardPersonaLabelFromPrefix(prefix.toLowerCase())}证据卡片 ${batch}`
    )
    .replace(/\bevidence-card\b/gi, "证据卡片");
}

function isEvidenceCardDocument(document: PersonaMaterialDocument) {
  return (
    document.doc_id.includes("source_expansion_evidence_cards") ||
    document.source_path.includes("source_expansion_evidence_cards") ||
    /\bEvidence Cards\b/i.test(document.title)
  );
}

function evidenceCardPersonaLabel(title: string): string {
  const prefix = title.match(/^([A-Za-z]+)\s+Evidence Cards\b/i)?.[1]?.toLowerCase();
  return evidenceCardPersonaLabelFromPrefix(prefix);
}

function evidenceCardPersonaLabelFromPrefix(prefix: string | undefined): string {
  const labels: Record<string, string> = {
    franklin: "富兰克林",
    tesla: "特斯拉",
    keller: "凯勒",
    darwin: "Darwin"
  };
  return prefix ? labels[prefix] ?? prefix : "人物";
}

function displayDocumentTitle(document: PersonaMaterialDocument): string {
  if (isEvidenceCardDocument(document)) {
    const batch = document.title.match(/\bEvidence Cards\s+(\d+)/i)?.[1];
    return `${evidenceCardPersonaLabel(document.title)}证据卡片${batch ? ` ${batch}` : ""}`;
  }
  return displayArchiveText(document.title);
}

function displayArchivePreview(value: string): string {
  return displayArchiveText(value).trim();





















}

function displayCitationTitle(citation: Citation) {
  if (citation.doc_id.startsWith("safety_policy")) return "conversation boundary";
  return displayArchiveText(citation.title);
}

function lastSessionStorageKey(userId: string) {
  return `persona_rag_last_session_id_${userId}`;
}

function readLastSessionId(userId?: string) {
  if (!userId) return "";
  return window.localStorage.getItem(lastSessionStorageKey(userId)) ?? "";
}

function writeLastSessionId(userId: string | undefined, sessionId: string) {
  if (!userId) return;
  window.localStorage.setItem(lastSessionStorageKey(userId), sessionId);
}

function clearLastSessionId(userId: string | undefined) {
  if (!userId) return;
  window.localStorage.removeItem(lastSessionStorageKey(userId));
}

const OPENING_PENDING_TEXT = "正在准备问候语";

function openingPendingMessage(persona: PersonaProfile): UiMessage {
  return {
    id: `welcome-${persona.id}-pending`,
    role: "assistant",
    content: OPENING_PENDING_TEXT
  };
}

function welcomeMessage(persona: PersonaProfile, openingMessage?: string | null): UiMessage {
  return {
    id: `welcome-${persona.id}`,
    role: "assistant",
    content: normalizeOpeningMessage(openingMessage) || fallbackWelcomeMessage(persona)
  };
}

function normalizeOpeningMessage(message?: string | null) {
  const compact = (message ?? "").trim();
  return compact.length > 0 ? compact : "";
}

function fallbackWelcomeMessage(persona: PersonaProfile) {
  if (persona.id === "nikola_tesla") {
    return "你好。把问题放到台面上吧，我更愿意从一个具体的现象或设想开始检验。";
  }
  if (persona.id === "benjamin_franklin") {
    return "你好。我们不妨从一件实际的小事谈起；若它能被改进，就值得认真算一算。";
  }
  if (persona.id === "helen_keller") {
    return "你好。很高兴和你说话；你可以从今天最想说的一件小事开始。";
  }
  if (persona.id === "charles_darwin") {
    return "你好。先把观察摆出来吧，我愿意和你一起慢慢分辨其中的线索。";
  }
  if (persona.id === "paul_graham_public_archive") {
    return "你好。直接说你正在想的事吧，我们可以把它缩成一个更清楚的问题。";
  }
  if (persona.id === "local_persona") {
    return "你好，我是小王，也就是王浩沣，《Web虚拟分身》这个综合课程设计的唯一开发者。这个项目已经完成从创建分身到社区分享的闭环；你可以从目标、架构、使用流程或部署方式里挑一个切入点，我会有条理地讲清楚。";
  }
  return `你好，我是 ${persona.name}。我们可以先从一个具体问题开始，把情况说清楚。`;
}

function profileFromUserPersonaDetail(persona: UserPersonaDetail): PersonaProfile {
  return {
    id: persona.id,
    name: persona.name,
    subtitle: persona.identity_tags.length ? persona.identity_tags.join("、") : persona.short_description,
    description: persona.description || persona.short_description || "用户创建的虚拟分身。",
    avatar_label: persona.avatar_label,
    avatar_url: persona.avatar_url,
    identity_tags: persona.identity_tags,
    source_note: persona.is_public ? "用户公开虚拟分身。" : "用户自有虚拟分身。",
    boundary_note:
      persona.runtime_status === "ready" ? "该分身已准备好进入对话。" : "该分身尚未准备好进入对话。",
    corpus_paths: [],
    retrieval_prefixes: [],
    raw_source_paths: [],
    source_urls: [],
    suggested_questions: ["你最想让我从哪里开始讲？", "你通常会怎样回答这个问题？", "给我一个简洁的建议。"],
    kind: persona.kind,
    is_owner: persona.is_owner,
    is_public: persona.is_public,
    published_at: persona.published_at
  };
}

function isReadonlyPublicUserPersona(persona: PersonaProfile | null | undefined) {
  return Boolean(persona?.id.startsWith("user_persona_") && persona.is_owner === false && persona.is_public);
}

const AUTH_TOKEN_KEY = "persona_rag_auth_token";
const DASHBOARD_COLLAPSED_KEY = "persona_rag_runtime_dashboard_popover_collapsed";
const THEME_KEY = "persona_rag_ui_theme";

function readStoredDashboardCollapsed() {
  const stored = window.localStorage.getItem(DASHBOARD_COLLAPSED_KEY);
  return stored === null ? true : stored === "true";
}

function readStoredTheme(): UiThemeId {
  const storedTheme = window.localStorage.getItem(THEME_KEY);
  return isUiThemeId(storedTheme) ? storedTheme : DEFAULT_THEME;
}

export default function App() {
  const location = useLocation();
  const navigate = useNavigate();
  const params = useParams<{ personaId?: string }>();
  const [searchParams] = useSearchParams();
  const routePath = location.pathname;
  const routeState = location.state as { returnTo?: string } | null;
  const routePersonaId = params.personaId ? decodeURIComponent(params.personaId) : "";
  const routeSessionId = searchParams.get("session") ?? "";
  const platformInitialView =
    routePath === "/app/public" ? "public" : routePath === "/app/mine" ? "mine" : "home";
  const isPlatformRoute = routePath === "/app" || routePath === "/app/public" || routePath === "/app/mine";
  const isAdminUsersRoute = routePath === "/app/admin/users";
  const isChatRoute = routePath.startsWith("/app/chat/");
  const [authToken, setAuthToken] = useState(() => window.localStorage.getItem(AUTH_TOKEN_KEY) ?? "");
  const [dashboardCollapsed, setDashboardCollapsed] = useState(readStoredDashboardCollapsed);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [theme, setTheme] = useState(readStoredTheme);
  const themePreferenceLoadedRef = useRef(false);

  useEffect(() => {
    setAuthTokenProvider(() => window.localStorage.getItem(AUTH_TOKEN_KEY));
  }, [authToken]);

  useEffect(() => {
    if (themePreferenceLoadedRef.current) return;
    themePreferenceLoadedRef.current = true;
    let cancelled = false;
    void fetchThemePreference()
      .then((preference) => {
        if (cancelled || !isUiThemeId(preference.theme)) return;
        setTheme(preference.theme);
        window.localStorage.setItem(THEME_KEY, preference.theme);
      })
      .catch(() => {
        // Backend theme lookup is a convenience. The local cached theme remains usable offline.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!authToken && routePath !== "/login") {
      navigate("/login", { replace: true });
    }
  }, [authToken, navigate, routePath]);

  const currentUserQuery = useQuery({
    queryKey: ["auth-me", authToken],
    queryFn: fetchCurrentUser,
    enabled: Boolean(authToken),
    retry: false
  });
  const currentUser = currentUserQuery.data;
  const authReady = Boolean(authToken && currentUser);

  useEffect(() => {
    if (!currentUser?.theme_preference || !isUiThemeId(currentUser.theme_preference)) return;
    setTheme(currentUser.theme_preference);
    window.localStorage.setItem(THEME_KEY, currentUser.theme_preference);
  }, [currentUser?.theme_preference]);

  useEffect(() => {
    if (authReady && routePath === "/login") {
      navigate("/app", { replace: true });
    }
  }, [authReady, navigate, routePath]);

  useEffect(() => {
    if (authReady && isAdminUsersRoute && currentUser && currentUser.role !== "admin") {
      navigate("/app", { replace: true });
    }
  }, [authReady, currentUser, isAdminUsersRoute, navigate]);

  const personasQuery = useQuery({
    queryKey: ["personas"],
    queryFn: fetchPersonas,
    enabled: authReady,
    staleTime: 60_000,
    retry: false
  });
  const personas = personasQuery.data?.length ? personasQuery.data : fallbackPersonas;
  const [selectedPersonaId, setSelectedPersonaId] = useState(
    () => window.localStorage.getItem("persona_rag_selected_persona") ?? ""
  );
  const [selectedCustomPersona, setSelectedCustomPersona] = useState<PersonaProfile | null>(null);
  const [sessionId, setSessionId] = useState("");
  const [sessionDrawerOpen, setSessionDrawerOpen] = useState(false);
  const [sessionSort, setSessionSort] = useState<"recent" | "persona">("recent");
  const [sessionNotice, setSessionNotice] = useState("");
  const selectedSystemPersona = personas.find((persona) => persona.id === selectedPersonaId) ?? null;
  const hasSelectedPersona = Boolean(selectedPersonaId) && Boolean(selectedSystemPersona ?? selectedCustomPersona);
  const selectedPersona = selectedSystemPersona ?? selectedCustomPersona ?? fallbackPersonas[0];
  const readonlyPublicPersona = isReadonlyPublicUserPersona(selectedPersona);
  const [messages, setMessages] = useState<UiMessage[]>([]);
  const [input, setInput] = useState("");
  const [thinkingEffort, setThinkingEffort] = useState<ThinkingEffort>(readStoredThinkingEffort);
  const [isSending, setIsSending] = useState(false);
  const [selectedCitation, setSelectedCitation] = useState<Citation | null>(null);
  const [selectedMaterialId, setSelectedMaterialId] = useState("");
  const [activeRailView, setActiveRailView] = useState<SidePanelView>("chat");
  const [isEvalRunning, setIsEvalRunning] = useState(false);
  const [evalRunNotice, setEvalRunNotice] = useState("");
  const [turnFeedbackByRequest, setTurnFeedbackByRequest] = useState<Record<string, FeedbackIssue>>({});
  const [turnFeedbackNotice, setTurnFeedbackNotice] = useState("");
  const [turnMetaByRequest, setTurnMetaByRequest] = useState<Record<string, TurnMeta>>({});
  const [pendingAcceptanceCase, setPendingAcceptanceCase] = useState<BrowserAcceptanceCase | null>(null);
  const [acceptanceCaseByRequest, setAcceptanceCaseByRequest] = useState<Record<string, string>>({});
  const [activeStage, setActiveStage] = useState<StreamStageEvent | null>(null);
  const [sendStartedAt, setSendStartedAt] = useState<number | null>(null);
  const [liveElapsedMs, setLiveElapsedMs] = useState(0);
  const [releaseNotice, setReleaseNotice] = useState("");
  const [showJumpToLatest, setShowJumpToLatest] = useState(false);
  const activeTurnRef = useRef<ActiveTurn | null>(null);
  const autoRestoreSessionRef = useRef("");
  const messageListRef = useRef<HTMLElement | null>(null);
  const shouldStickToBottomRef = useRef(true);
  const lastMessageUpdateKindRef = useRef<"content" | "diagnostic" | null>(null);
  const pendingDiagnosticDeltasRef = useRef<HiddenThinkingDeltaEvent[]>([]);
  const diagnosticFlushTimerRef = useRef<ReturnType<typeof window.setTimeout> | null>(null);
  const diagnosticFlushTargetRef = useRef<{
    assistantId: string;
    turnId: string;
    includeHiddenThinking: boolean;
  } | null>(null);
  const latestResponse = [...messages].reverse().find((message) => message.response)?.response;

  function clearPendingDiagnostics() {
    pendingDiagnosticDeltasRef.current = [];
    diagnosticFlushTargetRef.current = null;
    if (diagnosticFlushTimerRef.current !== null) {
      window.clearTimeout(diagnosticFlushTimerRef.current);
      diagnosticFlushTimerRef.current = null;
    }
  }

  function flushPendingDiagnostics() {
    if (diagnosticFlushTimerRef.current !== null) {
      window.clearTimeout(diagnosticFlushTimerRef.current);
      diagnosticFlushTimerRef.current = null;
    }
    const pending = pendingDiagnosticDeltasRef.current;
    const target = diagnosticFlushTargetRef.current;
    pendingDiagnosticDeltasRef.current = [];
    if (!target || pending.length === 0) return;
    if (activeTurnRef.current?.turnId !== target.turnId) return;
    lastMessageUpdateKindRef.current = "diagnostic";
    setMessages((current) =>
      current.map((message) => {
        if (message.id !== target.assistantId) return message;
        const diagnostics = pending.reduce<ChatDiagnostics | null | undefined>(
          (currentDiagnostics, delta) =>
            mergeRuntimeDiagnosticDelta(
              currentDiagnostics,
              delta,
              target.includeHiddenThinking
            ),
          message.diagnostics
        );
        return { ...message, diagnostics };
      })
    );
  }

  function queueDiagnosticDelta(
    delta: HiddenThinkingDeltaEvent,
    target: {
      assistantId: string;
      turnId: string;
      includeHiddenThinking: boolean;
    }
  ) {
    diagnosticFlushTargetRef.current = target;
    pendingDiagnosticDeltasRef.current.push(delta);
    if (diagnosticFlushTimerRef.current !== null) return;
    diagnosticFlushTimerRef.current = window.setTimeout(
      flushPendingDiagnostics,
      DIAGNOSTIC_FLUSH_INTERVAL_MS
    );
  }

  useEffect(() => () => clearPendingDiagnostics(), []);

  useEffect(() => {
    if (!authReady || !isChatRoute || !routePersonaId) return;
    if (selectedPersonaId === routePersonaId && hasSelectedPersona) return;
    const systemPersona = personas.find((persona) => persona.id === routePersonaId);
    if (systemPersona) {
      window.localStorage.setItem("persona_rag_selected_persona", systemPersona.id);
      setSelectedCustomPersona(null);
      setSelectedPersonaId(systemPersona.id);
      clearTurnSurface(systemPersona);
      return;
    }
    let cancelled = false;
    void fetchUserPersonaDetail(routePersonaId)
      .then((detail) => {
        if (cancelled) return;
        const customPersona = profileFromUserPersonaDetail(detail);
        window.localStorage.setItem("persona_rag_selected_persona", customPersona.id);
        setSelectedCustomPersona(customPersona);
        setSelectedPersonaId(customPersona.id);
        clearTurnSurface(customPersona);
      })
      .catch(() => {
        if (!cancelled) {
          navigate("/app/public", { replace: true });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [authReady, hasSelectedPersona, isChatRoute, navigate, personas, routePersonaId, selectedPersonaId]);

  useEffect(() => {
    if (!selectedPersona || messages.length > 0) return;
    lastMessageUpdateKindRef.current = "content";
    setMessages([openingPendingMessage(selectedPersona)]);
    setSelectedCitation(null);
    setSelectedMaterialId("");
  }, [messages.length, selectedPersona]);

  useEffect(() => {
    autoRestoreSessionRef.current = "";
    if (!currentUser?.id) {
      setSessionId("");
      return;
    }
    setSessionId(readLastSessionId(currentUser.id));
  }, [currentUser?.id]);

  useEffect(() => {
    window.localStorage.setItem(THEME_KEY, theme);
  }, [theme]);

  const statusQuery = useQuery({
    queryKey: ["status"],
    queryFn: fetchStatus,
    enabled: authReady,
    refetchInterval: 3000,
    retry: false
  });

  const evalRunsQuery = useQuery({
    queryKey: ["eval-runs"],
    queryFn: fetchEvalRuns,
    enabled: false,
    refetchInterval: false,
    retry: false
  });

  const evidenceStatsQuery = useQuery({
    queryKey: ["evidence-stats"],
    queryFn: fetchEvidenceStats,
    enabled: false,
    refetchInterval: false,
    retry: false
  });

  const materialsQuery = useQuery({
    queryKey: ["persona-materials", selectedPersona?.id],
    queryFn: () => fetchPersonaMaterials(selectedPersona!.id),
    enabled: false,
    staleTime: 60_000,
    retry: false
  });

  const chatSessionsQuery = useQuery({
    queryKey: ["chat-sessions", currentUser?.id, sessionSort, "active"],
    queryFn: () => fetchChatSessions(sessionSort, "active"),
    enabled: authReady && Boolean(currentUser),
    staleTime: 10_000,
    retry: false
  });

  const archivedSessionsQuery = useQuery({
    queryKey: ["chat-sessions", currentUser?.id, sessionSort, "archived"],
    queryFn: () => fetchChatSessions(sessionSort, "archived"),
    enabled: authReady && Boolean(currentUser) && settingsOpen,
    staleTime: 10_000,
    retry: false
  });

  const memoryItemsQuery = useQuery({
    queryKey: ["memory-items", currentUser?.id, selectedPersona?.id, sessionId, "session"],
    queryFn: () => fetchMemoryItems(selectedPersona!.id, sessionId, "session"),
    enabled: false,
    refetchInterval: false,
    retry: false
  });

  const memoryStatsQuery = useQuery({
    queryKey: ["memory-stats", currentUser?.id, selectedPersona?.id, sessionId, "session"],
    queryFn: () => fetchMemoryStats(selectedPersona?.id, sessionId, "session"),
    enabled: false,
    refetchInterval: false,
    retry: false
  });

  const globalMemoryItemsQuery = useQuery({
    queryKey: ["memory-items", currentUser?.id, "user_global"],
    queryFn: () => fetchMemoryItems(undefined, undefined, "user_global"),
    enabled: false,
    refetchInterval: false,
    retry: false
  });

  const globalMemoryStatsQuery = useQuery({
    queryKey: ["memory-stats", currentUser?.id, "user_global"],
    queryFn: () => fetchMemoryStats(undefined, undefined, "user_global"),
    enabled: false,
    refetchInterval: false,
    retry: false
  });

  const feedbackStatsQuery = useQuery({
    queryKey: ["feedback-stats"],
    queryFn: fetchPersonaFeedbackStats,
    enabled: false,
    refetchInterval: false,
    retry: false
  });

  const browserAcceptanceMatrixQuery = useQuery({
    queryKey: ["browser-acceptance-matrix"],
    queryFn: fetchBrowserAcceptanceMatrix,
    enabled: false,
    retry: false
  });

  const status = statusQuery.data;
  const evidenceStats = evidenceStatsQuery.data;
  const latestRetrievalEval = evalRunsQuery.data?.find((run) => run.mode === "retrieval");
  const latestChatEval = evalRunsQuery.data?.find((run) => run.mode === "chat");
  const latestJudgeEval = evalRunsQuery.data?.find((run) => run.mode === "judge");
  const selectedRuntimePlan = runtimePlan(status, thinkingEffort);
  const activeThinkingTokenBudget =
    selectedRuntimePlan?.num_predict ?? thinkingEffortTokenBudget(status?.model_num_predict, thinkingEffort);
  const activeThinkingRunLabel = thinkingEffortRunLabel(thinkingEffort, status);
  const activeModelName = activeGenerationModel(status, thinkingEffort);
  const activeCitations = latestResponse?.citations ?? [];
  const activeTrace = latestResponse?.retrieval_trace;
  const visibleCitation = selectedCitation ?? activeCitations[0] ?? null;
  const corpusDocuments = materialsQuery.data?.documents ?? [];
  const currentPanel = sidePanelMeta[activeRailView];
  const visibleConversationMessages = messages.filter((message) => !message.id.startsWith("welcome-"));
  const resourceUsage = status?.resource_usage;

  useEffect(() => {
    if (!currentUser?.id || !chatSessionsQuery.isSuccess || isSending || !isChatRoute || !routeSessionId) return;
    if (visibleConversationMessages.length > 0) return;
    const storedSessionId = routeSessionId;
    if (!storedSessionId || autoRestoreSessionRef.current === storedSessionId) return;
    const session = (chatSessionsQuery.data ?? []).find((item) => item.session_id === storedSessionId);
    if (!session || session.status !== "active") {
      clearLastSessionId(currentUser.id);
      autoRestoreSessionRef.current = storedSessionId;
      return;
    }
    autoRestoreSessionRef.current = storedSessionId;
    void restoreChatSession(session, { silent: true });
  }, [
    chatSessionsQuery.data,
    chatSessionsQuery.isSuccess,
    currentUser?.id,
    isChatRoute,
    isSending,
    routeSessionId,
    visibleConversationMessages.length
  ]);

  useEffect(() => {
    if (!isSending || sendStartedAt === null) return;
    setLiveElapsedMs(Date.now() - sendStartedAt);
    const timer = window.setInterval(() => {
      setLiveElapsedMs(Date.now() - sendStartedAt);
    }, 250);
    return () => window.clearInterval(timer);
  }, [isSending, sendStartedAt]);

  useEffect(() => {
    if (turnFeedbackNotice !== TURN_FEEDBACK_SAVED_NOTICE) return;
    const timer = window.setTimeout(() => setTurnFeedbackNotice(""), 3200);
    return () => window.clearTimeout(timer);
  }, [turnFeedbackNotice]);

  function isMessageListNearBottom() {
    const element = messageListRef.current;
    if (!element) return true;
    return element.scrollHeight - element.scrollTop - element.clientHeight < 180;
  }

  function scrollMessagesToBottom(behavior: ScrollBehavior = "smooth") {
    const element = messageListRef.current;
    if (!element) return;
    element.scrollTo({ top: element.scrollHeight, behavior });
    shouldStickToBottomRef.current = true;
    setShowJumpToLatest(false);
  }

  function handleMessageListScroll() {
    const nearBottom = isMessageListNearBottom();
    shouldStickToBottomRef.current = nearBottom;
    setShowJumpToLatest(!nearBottom);
  }

  useEffect(() => {
    if (lastMessageUpdateKindRef.current === "diagnostic") {
      lastMessageUpdateKindRef.current = null;
      return;
    }
    lastMessageUpdateKindRef.current = null;
    if (!shouldStickToBottomRef.current) return;
    window.requestAnimationFrame(() => scrollMessagesToBottom("auto"));
  }, [messages, isSending]);

  async function releaseRuntimeAfterTurn(options: {
    thinkingEffort?: ThinkingEffort;
    includeEmbedding?: boolean;
    includeAllGenerationModels?: boolean;
    notice?: string;
  }) {
    setReleaseNotice(options.notice ?? "正在停止并释放模型...");
    try {
      const result = await releaseRuntimeModels(options);
      if (result.still_loaded_models.length) {
        setReleaseNotice(`释放仍在进行：${result.still_loaded_models.join(" / ")}`);
      } else if (result.released_models.length) {
        setReleaseNotice(`已释放模型：${result.released_models.join(" / ")}`);
      } else {
        setReleaseNotice("没有检测到需要释放的常驻生成模型。");
      }
      await statusQuery.refetch();
    } catch (error) {
      setReleaseNotice(error instanceof Error ? error.message : "模型释放失败。");
    }
  }

  function cancelActiveTurn(reason = "Generation interrupted.") {
    const activeTurn = activeTurnRef.current;
    if (!activeTurn) return;
    activeTurn.cancelled = true;
    activeTurn.controller.abort();
    activeTurnRef.current = null;
    clearPendingDiagnostics();
    void releaseRuntimeAfterTurn({
      thinkingEffort: activeTurn.thinkingEffort,
      includeEmbedding: true,
      notice: "正在停止并释放模型..."
    });
    const elapsed = Date.now() - activeTurn.startedAt;
    lastMessageUpdateKindRef.current = "content";
    setMessages((current) =>
      current.map((message) =>
        message.id === activeTurn.assistantId && !message.response
          ? {
              ...message,
              content: `已中断，本轮未记录。${reason ? ` ${reason}` : ""}`
            }
          : message
      )
    );
    setIsSending(false);
    setSendStartedAt(null);
    setLiveElapsedMs(elapsed);
    setActiveStage({
      key: "cancelled",
      label: "已中断",
      elapsed_ms: elapsed,
      detail: reason
    });
  }

  function clearTurnSurface(persona?: PersonaProfile, restoredMessages?: UiMessage[], openingMessage?: string | null) {
    setInput("");
    setIsSending(false);
    clearPendingDiagnostics();
    lastMessageUpdateKindRef.current = "content";
    setMessages(restoredMessages ?? (persona ? [welcomeMessage(persona, openingMessage)] : []));
    setSelectedCitation(null);
    setSelectedMaterialId("");
    setPendingAcceptanceCase(null);
    setAcceptanceCaseByRequest({});
    setTurnFeedbackByRequest({});
    setTurnMetaByRequest({});
    setActiveStage(null);
    setSendStartedAt(null);
    setLiveElapsedMs(0);
    setActiveRailView("chat");
  }

  function choosePersona(persona: PersonaProfile) {
    cancelActiveTurn(`已切换到 ${persona.name}。`);
    const returnTo = isPlatformRoute ? `${routePath}${location.search}` : routeState?.returnTo ?? "/app/public";
    window.localStorage.setItem("persona_rag_selected_persona", persona.id);
    setSelectedCustomPersona(personas.some((item) => item.id === persona.id) ? null : persona);
    setSelectedPersonaId(persona.id);
    setSessionNotice("");
    navigate(`/app/chat/${encodeURIComponent(persona.id)}`, { state: { returnTo } });
    void startNewConversationForPersona(persona, { replaceRoute: true, returnTo });
  }

  function clearPersona() {
    cancelActiveTurn("已返回分身选择。");
    const returnTo = routeState?.returnTo ?? "/app/public";
    window.localStorage.removeItem("persona_rag_selected_persona");
    setSelectedPersonaId("");
    setSelectedCustomPersona(null);
    setSessionId("");
    setSessionDrawerOpen(false);
    setSettingsOpen(false);
    clearTurnSurface();
    navigate(returnTo, { replace: true });
  }

  async function startNewConversationForPersona(
    persona: PersonaProfile,
    options?: { replaceRoute?: boolean; returnTo?: string }
  ) {
    if (!currentUser) return;
    setSessionNotice("正在创建新会话...");
    lastMessageUpdateKindRef.current = "content";
    setMessages([openingPendingMessage(persona)]);
    try {
      const session = await createChatSession(persona.id);
      writeLastSessionId(currentUser.id, session.session_id);
      setSessionId(session.session_id);
      window.localStorage.setItem("persona_rag_selected_persona", persona.id);
      setSelectedPersonaId(persona.id);
      setSelectedCustomPersona(personas.some((item) => item.id === persona.id) ? null : persona);
      clearTurnSurface(persona, undefined, session.opening_message);
      navigate(`/app/chat/${encodeURIComponent(persona.id)}?session=${encodeURIComponent(session.session_id)}`, {
        replace: options?.replaceRoute ?? false,
        state: { returnTo: options?.returnTo ?? routeState?.returnTo ?? "/app/public" }
      });
      setSessionNotice("新会话已创建。");
      await chatSessionsQuery.refetch();
    } catch (error) {
      setSessionNotice(error instanceof Error ? error.message : "新建会话失败。");
      clearTurnSurface(persona);
    }
  }

  function startNewConversation() {
    if (!currentUser || !selectedPersona) return;
    cancelActiveTurn("已创建新对话。");
    void startNewConversationForPersona(selectedPersona);
  }

  async function restoreChatSession(session: ChatSessionSummary, options?: { silent?: boolean }) {
    if (!currentUser) return;
    if (session.status !== "active") {
      setSessionNotice("该会话已归档，请先在设置中恢复。");
      return;
    }
    let persona = personas.find((item) => item.id === session.persona_id) ?? null;
    cancelActiveTurn(`已切换到会话：${session.title}`);
    if (!options?.silent) {
      setSessionNotice("正在恢复会话...");
    }
    try {
      if (!persona) {
        const detail = await fetchUserPersonaDetail(session.persona_id);
        persona = profileFromUserPersonaDetail(detail);
        setSelectedCustomPersona(persona);
      } else {
        setSelectedCustomPersona(null);
      }
      const history = await fetchChatSessionMessages(session.session_id);
      const restoredMessages: UiMessage[] = [];
      for (const message of history.messages) {
        const restoredMessage: UiMessage = {
          id: message.id,
          role: message.role,
          content: message.content,
          diagnostics: message.role === "assistant" ? message.diagnostics ?? null : null
        };
        if (message.role === "assistant") {
          restoredMessage.followUpQuestions = message.follow_up_questions ?? [];
        }
        restoredMessages.push(restoredMessage);
      }
      window.localStorage.setItem("persona_rag_selected_persona", session.persona_id);
      writeLastSessionId(currentUser.id, session.session_id);
      setSelectedPersonaId(session.persona_id);
      setSessionId(session.session_id);
      clearTurnSurface(
        persona,
        restoredMessages.length ? restoredMessages : [welcomeMessage(persona, session.opening_message)]
      );
      navigate(`/app/chat/${encodeURIComponent(session.persona_id)}?session=${encodeURIComponent(session.session_id)}`, {
        replace: options?.silent ?? false,
        state: { returnTo: routeState?.returnTo ?? "/app/public" }
      });
      if (!options?.silent) {
        setSessionNotice("会话已恢复。");
        setSessionDrawerOpen(false);
      }
      await chatSessionsQuery.refetch();
    } catch (error) {
      setSessionNotice(error instanceof Error ? error.message : "恢复会话失败。");
    }
  }

  async function archiveSession(session: ChatSessionSummary) {
    if (!currentUser) return;
    cancelActiveTurn("会话已归档。");
    setSessionNotice("正在归档会话...");
    try {
      await archiveChatSession(session.session_id);
      if (session.session_id === sessionId) {
        clearLastSessionId(currentUser.id);
        setSessionId("");
        clearTurnSurface(selectedPersona);
      }
      await chatSessionsQuery.refetch();
      await archivedSessionsQuery.refetch();
      await globalMemoryItemsQuery.refetch();
      await globalMemoryStatsQuery.refetch();
      setSessionNotice("会话已归档，可在设置中恢复。");
    } catch (error) {
      setSessionNotice(error instanceof Error ? error.message : "归档会话失败。");
    }
  }

  async function restoreArchivedSession(session: ChatSessionSummary) {
    if (!currentUser) return;
    setSessionNotice("正在恢复归档会话...");
    try {
      await restoreChatSessionApi(session.session_id);
      await chatSessionsQuery.refetch();
      await archivedSessionsQuery.refetch();
      await globalMemoryItemsQuery.refetch();
      await globalMemoryStatsQuery.refetch();
      setSessionNotice("会话已恢复到主列表。");
    } catch (error) {
      setSessionNotice(error instanceof Error ? error.message : "恢复会话失败。");
    }
  }

  async function deleteArchivedSession(session: ChatSessionSummary) {
    const confirmed = window.confirm(`确定永久删除“${session.title || "未命名会话"}”吗？删除后无法恢复。`);
    if (!confirmed) return;
    setSessionNotice("正在永久删除会话...");
    try {
      await deleteChatSession(session.session_id);
      if (currentUser && session.session_id === sessionId) {
        clearLastSessionId(currentUser.id);
        setSessionId("");
        clearTurnSurface(selectedPersona);
      }
      await chatSessionsQuery.refetch();
      await archivedSessionsQuery.refetch();
      await globalMemoryItemsQuery.refetch();
      await globalMemoryStatsQuery.refetch();
      setSessionNotice("会话已永久删除。");
    } catch (error) {
      setSessionNotice(error instanceof Error ? error.message : "永久删除会话失败。");
    }
  }

  function chooseThinkingEffort(value: ThinkingEffort) {
    if (value === thinkingEffort) return;
    if (isSending) {
      cancelActiveTurn(`已切换到${thinkingEffortLabel(value)}思考强度。`);
    } else {
      void releaseRuntimeAfterTurn({
        thinkingEffort,
        includeEmbedding: true,
        notice: "正在切换思考强度并释放旧模型..."
      });
    }
    window.localStorage.setItem("persona_rag_thinking_effort", value);
    setThinkingEffort(value);
  }

  function toggleDashboardCollapsed() {
    setDashboardCollapsed((current) => {
      const next = !current;
      window.localStorage.setItem(DASHBOARD_COLLAPSED_KEY, String(next));
      return next;
    });
  }

  function useAcceptancePrompt(caseItem: BrowserAcceptanceCase) {
    setInput(caseItem.prompt);
    setPendingAcceptanceCase(caseItem);
    setTurnFeedbackNotice(
      `已载入验收用例 ${caseItem.case_id}。发送后会把反馈计入矩阵进度。`
    );
  }

  function updateComposerInput(value: string) {
    setInput(value);
    if (pendingAcceptanceCase && value.trim() !== pendingAcceptanceCase.prompt.trim()) {
      setPendingAcceptanceCase(null);
      setTurnFeedbackNotice("");
    }
  }

  async function runRetrievalEval() {
    if (isEvalRunning) return;
    setIsEvalRunning(true);
    setEvalRunNotice("");
    try {
      const result = await runEval("retrieval");
      setEvalRunNotice(
        `检索评测完成：${result.passed_count}/${result.question_count} 通过，平均延迟 ${formatLatency(
          result.metrics.mean_latency_ms
        )}。`
      );
      await evalRunsQuery.refetch();
      await statusQuery.refetch();
    } catch (error) {
      setEvalRunNotice(error instanceof Error ? error.message : "评测执行失败。");
    } finally {
      setIsEvalRunning(false);
    }
  }

  async function runJudgeEval() {
    if (isEvalRunning) return;
    setIsEvalRunning(true);
    setEvalRunNotice("");
    try {
      const result = await runEval("judge");
      setEvalRunNotice(
        `Judge 评测完成：${result.passed_count}/${result.question_count} 通过，平均分 ${(
          result.metrics.mean_judge_score ?? 0
        ).toFixed(2)}。`
      );
      await evalRunsQuery.refetch();
      await statusQuery.refetch();
    } catch (error) {
      setEvalRunNotice(error instanceof Error ? error.message : "Judge 评测执行失败。");
    } finally {
      setIsEvalRunning(false);
    }
  }

  async function refreshEvalRuns() {
    setEvalRunNotice("");
    await evalRunsQuery.refetch();
    await feedbackStatsQuery.refetch();
  }

  async function submitMemory(content: string) {
    if (!selectedPersona || !sessionId || !content.trim()) return;
    await proposeMemory(content.trim(), selectedPersona.id, sessionId);
    await memoryItemsQuery.refetch();
    await memoryStatsQuery.refetch();
  }

  async function changeMemoryStatus(memoryId: string, action: "approve" | "reject" | "retract") {
    await updateMemoryStatus(memoryId, action, sessionId);
    await memoryItemsQuery.refetch();
    await memoryStatsQuery.refetch();
  }

  async function submitTurnFeedback(
    response: ChatResponse,
    issue: FeedbackIssue,
    severity: FeedbackSeverity,
    userMessage: string
  ) {
    if (!selectedPersona || !sessionId || !userMessage.trim()) return;
    const turnMeta = turnMetaByRequest[response.request_id];
    const feedbackPersonaId = turnMeta?.persona_id ?? response.retrieval_trace?.persona_id ?? selectedPersona.id;
    const feedbackPersonaName =
      turnMeta?.persona_name ?? personas.find((persona) => persona.id === feedbackPersonaId)?.name ?? selectedPersona.name;
    setTurnFeedbackNotice("");
    try {
      await submitPersonaTurnFeedback({
        persona_id: feedbackPersonaId,
        persona_name: feedbackPersonaName,
        session_id: turnMeta?.session_id ?? response.session_id ?? sessionId,
        request_id: response.request_id,
        acceptance_case_id: acceptanceCaseByRequest[response.request_id] ?? undefined,
        user_message: userMessage,
        assistant_answer: response.answer,
        issue,
        severity,
        thinking_effort: turnMeta?.thinking_effort ?? thinkingEffort,
        mode: response.mode,
        model: response.model,
        trace_notes: response.retrieval_trace?.notes ?? [],
        citation_doc_ids: response.citations.map((citation) => citation.doc_id),
        citation_titles: response.citations.map((citation) => citation.title),
        frontend_url: window.location.href
      });
      setTurnFeedbackByRequest((current) => ({
        ...current,
        [response.request_id]: issue
      }));
      await feedbackStatsQuery.refetch();
      await browserAcceptanceMatrixQuery.refetch();
      setTurnFeedbackNotice(TURN_FEEDBACK_SAVED_NOTICE);
    } catch (error) {
      setTurnFeedbackNotice(error instanceof Error ? error.message : "反馈保存失败。");
    }
  }

  async function copyAssistantAnswer(answer: string) {
    try {
      await navigator.clipboard.writeText(answer);
      setTurnFeedbackNotice("回答已复制。");
    } catch {
      setTurnFeedbackNotice("复制失败，请手动选择文本。");
    }
  }

  function speakAssistantAnswer(answer: string) {
    if (!("speechSynthesis" in window)) {
      setTurnFeedbackNotice("当前浏览器不支持朗读。");
      return;
    }
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(answer);
    utterance.lang = "zh-CN";
    window.speechSynthesis.speak(utterance);
    setTurnFeedbackNotice("正在朗读回答。");
  }

  async function submitMessage(value: string) {
    const trimmed = value.trim();
    if (!trimmed || isSending || !selectedPersona || !currentUser) return;
    const startedAt = Date.now();
    let activeSessionId = sessionId;
    if (!activeSessionId) {
      try {
        setSessionNotice("正在创建会话...");
        const createdSession = await createChatSession(selectedPersona.id, trimmed);
        activeSessionId = createdSession.session_id;
        writeLastSessionId(currentUser.id, activeSessionId);
        setSessionId(activeSessionId);
        setSessionNotice("");
        await chatSessionsQuery.refetch();
      } catch (error) {
        const message =
          error instanceof Error
            ? `会话创建失败：${error.message}。请确认 8001 后端已重启。`
            : "会话创建失败。请确认 8001 后端已重启。";
        setSessionNotice(message);
        setTurnFeedbackNotice(message);
        setActiveStage({
          key: "error",
          label: "会话创建失败",
          elapsed_ms: Date.now() - startedAt,
          detail: message
        });
        return;
      }
    }
    const turnId = crypto.randomUUID();
    const controller = new AbortController();
    const personaSnapshot = selectedPersona;
    const sessionSnapshot = activeSessionId;
    const effortSnapshot = thinkingEffort;
    const acceptanceCaseForTurn =
      pendingAcceptanceCase &&
      pendingAcceptanceCase.persona_id === personaSnapshot.id &&
      pendingAcceptanceCase.prompt.trim() === trimmed
        ? pendingAcceptanceCase
        : null;
    const userMessage: UiMessage = {
      id: crypto.randomUUID(),
      role: "user",
      content: trimmed
    };
    const assistantId = crypto.randomUUID();
    const pendingText = `${personaSnapshot.name} 正在思考...`;
    const assistantDraft: UiMessage = {
      id: assistantId,
      role: "assistant",
      content: pendingText,
      followUpQuestions: []
    };
    activeTurnRef.current = {
      turnId,
      controller,
      assistantId,
      startedAt,
      personaId: personaSnapshot.id,
      sessionId: sessionSnapshot,
      thinkingEffort: effortSnapshot,
      cancelled: false
    };
    const isCurrentTurn = () => {
      const activeTurn = activeTurnRef.current;
      return (
        activeTurn?.turnId === turnId &&
        activeTurn.personaId === personaSnapshot.id &&
        activeTurn.sessionId === sessionSnapshot &&
        !activeTurn.cancelled
      );
    };
    lastMessageUpdateKindRef.current = "content";
    setMessages((current) => [...current, userMessage, assistantDraft]);
    setInput("");
    setPendingAcceptanceCase(null);
    setIsSending(true);
    setSendStartedAt(startedAt);
    setLiveElapsedMs(0);
    setReleaseNotice("");
    setActiveStage({
      key: "queued",
      label: "正在连接",
      elapsed_ms: 0,
      detail: `请求已发送；${thinkingEffortLabel(effortSnapshot)}思考强度。`
    });
    window.setTimeout(() => {
      if (isCurrentTurn()) {
        void chatSessionsQuery.refetch();
      }
    }, 350);

    try {
      await streamChat(trimmed, sessionSnapshot, personaSnapshot.id, effortSnapshot, {
        onStage: (stage) => {
          if (!isCurrentTurn()) return;
          setActiveStage(stage);
          setLiveElapsedMs(stage.elapsed_ms);
        },
        onDiagnostic: (diagnostic) => {
          const includeHiddenThinking = currentUser?.role === "admin";
          const isBudgetProgress = diagnostic.kind === "thinking_budget_progress";
          if (!isCurrentTurn() || (!includeHiddenThinking && !isBudgetProgress)) return;
          queueDiagnosticDelta(diagnostic, {
            assistantId,
            turnId,
            includeHiddenThinking
          });
        },
        onToken: (value) => {
          if (!isCurrentTurn()) return;
          flushPendingDiagnostics();
          lastMessageUpdateKindRef.current = "content";
          setMessages((current) =>
            current.map((message) =>
              message.id === assistantId
                ? {
                    ...message,
                    content:
                      message.content === pendingText
                        ? value
                        : `${message.content}${value}`
                  }
                : message
            )
          );
        },
        onFinal: (response) => {
          if (!isCurrentTurn()) return;
          flushPendingDiagnostics();
          lastMessageUpdateKindRef.current = "content";
          setMessages((current) =>
            current.map((message) => {
              if (message.id !== assistantId) return message;
              const diagnostics = diagnosticsWithoutFinalAnswerSource(response, message.diagnostics);
              const followUpQuestions = response.follow_up_questions ?? [];
              return {
                ...message,
                id: response.request_id,
                content: response.answer,
                followUpQuestions,
                response: {
                  ...response,
                  diagnostics,
                  follow_up_questions: followUpQuestions
                },
                diagnostics
              };
            })
          );
          setSelectedCitation(response.citations[0] ?? null);
          setTurnMetaByRequest((current) => ({
            ...current,
            [response.request_id]: {
              persona_id: personaSnapshot.id,
              persona_name: personaSnapshot.name,
              session_id: sessionSnapshot,
              thinking_effort: response.thinking_effort ?? effortSnapshot
            }
          }));
          if (acceptanceCaseForTurn) {
            setAcceptanceCaseByRequest((current) => ({
              ...current,
              [response.request_id]: acceptanceCaseForTurn.case_id
            }));
          }
          setActiveStage({
            key: "done",
            label: "已完成",
            elapsed_ms: response.timings.total_ms,
            detail: "回答已生成。"
          });
          setLiveElapsedMs(response.timings.total_ms);
          if (currentUser?.id && response.session_id) {
            writeLastSessionId(currentUser.id, response.session_id);
            setSessionId(response.session_id);
          }
          void chatSessionsQuery.refetch();
          void globalMemoryItemsQuery.refetch();
          void globalMemoryStatsQuery.refetch();
        }
      }, controller.signal);
    } catch (error) {
      if (isAbortError(error) || !isCurrentTurn()) return;
      clearPendingDiagnostics();
      lastMessageUpdateKindRef.current = "content";
      setMessages((current) => [
        ...current.filter((message) => message.id !== assistantId),
        {
          id: crypto.randomUUID(),
          role: "assistant",
          content:
            error instanceof Error
              ? `后端暂时不可用：${error.message}`
              : "Backend unavailable."
        }
      ]);
      setActiveStage({
        key: "error",
        label: "Connection failed",
        elapsed_ms: Date.now() - startedAt,
        detail: error instanceof Error ? error.message : "Backend unavailable."
      });
    } finally {
      if (isCurrentTurn()) {
        clearPendingDiagnostics();
        activeTurnRef.current = null;
        setIsSending(false);
        setSendStartedAt(null);
      }
    }
  }

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void submitMessage(input);
  }

  function applyThemePreference(nextTheme: UiThemeId) {
    setTheme(nextTheme);
    window.localStorage.setItem(THEME_KEY, nextTheme);
    if (!authToken || !currentUser?.id) return;
    void updateThemePreference(nextTheme)
      .then((preference) => {
        if (!isUiThemeId(preference.theme)) return;
        setTheme(preference.theme);
        window.localStorage.setItem(THEME_KEY, preference.theme);
        void currentUserQuery.refetch();
      })
      .catch(() => {
        // Theme selection remains local if the server save fails; the next login will resync it.
      });
  }

  function handleAuthenticated(token: string, user?: AuthUser) {
    window.localStorage.setItem(AUTH_TOKEN_KEY, token);
    if (user?.theme_preference && isUiThemeId(user.theme_preference)) {
      setTheme(user.theme_preference);
      window.localStorage.setItem(THEME_KEY, user.theme_preference);
    }
    setAuthToken(token);
    void currentUserQuery.refetch();
    navigate("/app", { replace: true });
  }

  async function handleLogout() {
    cancelActiveTurn("账号已退出。");
    void releaseRuntimeAfterTurn({
      includeEmbedding: true,
      includeAllGenerationModels: true,
      notice: "正在退出并释放本地模型..."
    });
    try {
      await logoutAccount();
    } catch {
      // Local logout should succeed even if the token is already expired.
    }
    window.localStorage.removeItem(AUTH_TOKEN_KEY);
    setAuthToken("");
    setSelectedPersonaId("");
    setSelectedCustomPersona(null);
    setSessionId("");
    setSessionDrawerOpen(false);
    setSettingsOpen(false);
    lastMessageUpdateKindRef.current = "content";
    setMessages([]);
    navigate("/login", { replace: true });
  }

  if (!authReady) {
    return <AuthGateway onAuthenticated={handleAuthenticated} theme={theme} />;
  }

  function navigatePlatform(view: "home" | "public" | "mine") {
    const nextPath = view === "home" ? "/app" : view === "public" ? "/app/public" : "/app/mine";
    navigate(nextPath);
  }

  function currentRouteForReturn() {
    return `${routePath}${location.search}`;
  }

  function openAdminUsers() {
    navigate("/app/admin/users", { state: { returnTo: currentRouteForReturn() } });
  }

  function adminReturnPath() {
    const returnTo = routeState?.returnTo;
    return returnTo && !returnTo.startsWith("/app/admin/users") ? returnTo : "/app";
  }

  if (isAdminUsersRoute && currentUser?.role === "admin") {
    return (
      <AdminUsersPage
        currentUser={currentUser}
        onClose={() => navigate(adminReturnPath(), { replace: true })}
        theme={theme}
      />
    );
  }

  if (isAdminUsersRoute && currentUser?.role !== "admin") {
    return null;
  }

  if (isPlatformRoute || !hasSelectedPersona) {
    if (!currentUser) {
      return null;
    }
    return (
      <PersonaPlatformGateway
        initialView={isPlatformRoute ? platformInitialView : "home"}
        onNavigate={navigatePlatform}
        systemPersonas={personas}
        loading={personasQuery.isLoading}
        offline={personasQuery.isError}
        currentUser={currentUser}
        onEnter={choosePersona}
        onLogout={() => void handleLogout()}
        onAdminUsers={openAdminUsers}
        theme={theme}
      />
    );
  }

  const sessionSummaries = chatSessionsQuery.data ?? [];
  const archivedSessionSummaries = archivedSessionsQuery.data ?? [];

  return (
    <main
      className={`compactWorkbench surfaceTransition ${dashboardCollapsed ? "dashboardCollapsed" : ""} ${
        sessionDrawerOpen ? "sessionDrawerOpen" : ""
      } theme-${theme}`}
    >
      <ThemeArtifacts theme={theme} />
      <SessionDrawer
        open={sessionDrawerOpen}
        sessions={sessionSummaries}
        currentSessionId={sessionId}
        sort={sessionSort}
        notice={sessionNotice}
        onToggle={() => setSessionDrawerOpen((current) => !current)}
        onClose={() => setSessionDrawerOpen(false)}
        onSortChange={setSessionSort}
        onNewConversation={startNewConversation}
        onOpenSession={(session) => void restoreChatSession(session)}
        onArchiveSession={(session) => void archiveSession(session)}
      />
      <SettingsPanel
        open={settingsOpen}
        theme={theme}
        archivedSessions={archivedSessionSummaries}
        archivedLoading={archivedSessionsQuery.isFetching}
        onClose={() => setSettingsOpen(false)}
        onThemeChange={applyThemePreference}
        onRefreshArchived={() => void archivedSessionsQuery.refetch()}
        onRestoreArchived={(session) => void restoreArchivedSession(session)}
        onDeleteArchived={(session) => void deleteArchivedSession(session)}
      />
      <button
        className={`dashboardToggleTab ${dashboardCollapsed ? "collapsed" : ""}`}
        type="button"
        onClick={toggleDashboardCollapsed}
        aria-expanded={!dashboardCollapsed}
        aria-controls="runtime-dashboard-panel"
      >
        {dashboardCollapsed ? <ChevronDown size={15} /> : <ChevronUp size={15} />}
        运行状态
      </button>
      <nav className="globalTopActions" aria-label="产品操作">
        <span className="topbarUserBadge">
          <UserCog size={14} />
          {currentUser?.username}
        </span>
        <button className="pillButton subtle" type="button" onClick={() => setSettingsOpen(true)}>
          <Settings size={15} />
          设置
        </button>
        {currentUser?.role === "admin" ? (
          <button className="pillButton subtle" type="button" onClick={openAdminUsers}>
            <UserCog size={15} />
            用户管理
          </button>
        ) : null}
        <button className="pillButton subtle" onClick={clearPersona}>
          <RotateCcw size={15} />
          切换分身
        </button>
        <button className="pillButton logoutDanger" type="button" onClick={() => void handleLogout()}>
          退出登录
        </button>
      </nav>
      <section id="runtime-dashboard-panel" className="runtimeDashboard" aria-label="本地运行状态">
        <div className="dashboardIntro">
          <div className="brandBlock">
            <div className="brandMark">
              <Brain size={22} />
            </div>
            <div>
              <p className="eyebrow">本地运行状态</p>
              <h1>{selectedPersona.name}</h1>
            </div>
          </div>
          <div className="dashboardActions">
            <span className="statusBadge">
              <UserCog size={14} />
              {currentUser?.username} / {currentUser?.role === "admin" ? "管理员" : "用户"}
            </span>
            <button className="pillButton subtle" type="button" onClick={() => setSettingsOpen(true)}>
              <Settings size={15} />
              设置
            </button>
            {currentUser?.role === "admin" ? (
              <button className="pillButton subtle" type="button" onClick={openAdminUsers}>
                <UserCog size={15} />
                用户管理
              </button>
            ) : null}
            <button className="pillButton subtle" onClick={clearPersona}>
              <RotateCcw size={15} />
              切换分身
            </button>
            <button className="pillButton logoutDanger" type="button" onClick={() => void handleLogout()}>
              退出登录
            </button>
          </div>
        </div>

        <div className="dashboardGrid">
          <section className="dashboardMetric">
            <div>
              <Activity size={18} />
              <span>CPU</span>
            </div>
            <strong>{formatOptionalPercent(resourceUsage?.cpu_percent)}</strong>
            <small>后端进程 {formatOptionalPercent(resourceUsage?.process_cpu_percent)}</small>
          </section>
          <section className="dashboardMetric">
            <div>
              <Gauge size={18} />
              <span>内存</span>
            </div>
            <strong>{formatOptionalPercent(resourceUsage?.memory_percent)}</strong>
            <small>
              {formatOptionalMb(resourceUsage?.memory_used_mb)} / {formatOptionalMb(resourceUsage?.memory_total_mb)}
            </small>
          </section>
          <section className="dashboardMetric">
            <div>
              <Activity size={18} />
              <span>GPU</span>
            </div>
            <strong>{formatOptionalPercent(resourceUsage?.gpu_util_percent)}</strong>
            <small>{gpuMemoryLabel(resourceUsage)}</small>
          </section>
          <section className="dashboardMetric">
            <div>
              <ShieldCheck size={18} />
              <span>当前模型</span>
            </div>
            <strong>{activeModelName}</strong>
            <small>{activeModelReady(status, thinkingEffort) ? "就绪" : "等待模型服务"}</small>
          </section>
        </div>

        <ProcessTimeline
          activeStage={activeStage}
          isSending={isSending}
          latestResponse={latestResponse}
          liveElapsedMs={liveElapsedMs}
          releaseNotice={releaseNotice}
        />
      </section>

      <section className="compactChatShell">
        {readonlyPublicPersona ? (
          <p className="sessionNotice publicPersonaNotice">这是其他用户公开的分身；你可以聊天，资料详情仅创建者可见。</p>
        ) : null}
        <section
          ref={messageListRef}
          className="messageList compactMessages"
          aria-live="polite"
          onScroll={handleMessageListScroll}
        >
          {messages.map((message, index) => {
            const previousUserMessage =
              [...messages.slice(0, index)].reverse().find((item) => item.role === "user")?.content ?? "";
            const feedbackIssue = message.response
              ? turnFeedbackByRequest[message.response.request_id]
              : undefined;
            const responseEffort = message.response
              ? turnMetaByRequest[message.response.request_id]?.thinking_effort ??
                message.response.thinking_effort
              : undefined;
            const diagnostics = message.response
              ? diagnosticsWithoutFinalAnswerSource(message.response, message.diagnostics)
              : message.diagnostics;
            const hiddenThinkingEvents = diagnostics?.hidden_thinking_events ?? [];
            const isActiveAssistant = isSending && activeTurnRef.current?.assistantId === message.id;
            const followUpQuestions =
              message.role === "assistant" && !message.id.startsWith("welcome-") && !isActiveAssistant
                ? message.followUpQuestions ?? []
                : [];
            const progressEffort =
              responseEffort ?? (isActiveAssistant ? activeTurnRef.current?.thinkingEffort : undefined);
            const showDiagnostics =
              message.role === "assistant" &&
              currentUser?.role === "admin" &&
              Boolean(diagnostics && hiddenThinkingEvents.length);
            const isOpeningPending =
              message.role === "assistant" &&
              message.id.startsWith("welcome-") &&
              message.content === OPENING_PENDING_TEXT;
            return (
              <article key={message.id} className={`message ${message.role}${isOpeningPending ? " openingPending" : ""}`}>
                <div className="messageAvatar">
                  {message.role === "assistant" ? <Brain size={17} /> : <MessageSquareText size={17} />}
                </div>
                <div className="messageBody">
                  <div className="messageMeta">
                    <span>{message.role === "assistant" ? selectedPersona.name : "你"}</span>
                    {message.response ? (
                      <span className="confidence">
                        {responseEffort ? `思考：${thinkingEffortLabel(responseEffort)} · ` : ""}
                        {formatLatency(message.response.timings.total_ms)}
                      </span>
                    ) : null}
                  </div>
                  {message.role === "assistant" && progressEffort ? (
                    <ThinkingBudgetProgress
                      diagnostics={diagnostics}
                      events={hiddenThinkingEvents}
                      status={status}
                      effort={progressEffort}
                      receiving={isActiveAssistant}
                      complete={Boolean(message.response)}
                    />
                  ) : null}
                  <p>{message.content}</p>
                  {showDiagnostics ? (
                    <HiddenThinkingPanel
                      events={hiddenThinkingEvents}
                      receiving={isActiveAssistant}
                    />
                  ) : null}
                  {message.role === "assistant" && followUpQuestions.length ? (
                    <div className="followUpQuestionRow" aria-label="你可能想继续问">
                      {followUpQuestions.map((question) => (
                        <button
                          key={question}
                          type="button"
                          disabled={isSending}
                          onClick={() => void submitMessage(question)}
                        >
                          {question}
                        </button>
                      ))}
                    </div>
                  ) : null}
                  {message.response && !message.id.startsWith("welcome-") ? (
                    <div className="feedbackRow messageActionBar" aria-label="回答操作">
                      <button
                        type="button"
                        className="messageActionButton"
                        title="复制"
                        aria-label="复制"
                        onClick={() => void copyAssistantAnswer(message.content)}
                      >
                        <Copy size={17} />
                      </button>
                      <button
                        type="button"
                        className={`messageActionButton ${feedbackIssue === "good" ? "active" : ""}`}
                        title="喜欢"
                        aria-label="喜欢"
                        disabled={Boolean(feedbackIssue)}
                        onClick={() =>
                          void submitTurnFeedback(
                            message.response as ChatResponse,
                            "good",
                            "low",
                            previousUserMessage
                          )
                        }
                      >
                        <ThumbsUp size={17} />
                      </button>
                      <button
                        type="button"
                        className={`messageActionButton ${feedbackIssue === "other" ? "active" : ""}`}
                        title="不喜欢"
                        aria-label="不喜欢"
                        disabled={Boolean(feedbackIssue)}
                        onClick={() =>
                          void submitTurnFeedback(
                            message.response as ChatResponse,
                            "other",
                            "high",
                            previousUserMessage
                          )
                        }
                      >
                        <ThumbsDown size={17} />
                      </button>
                      <button
                        type="button"
                        className="messageActionButton"
                        title="重试"
                        aria-label="重试"
                        disabled={isSending || !previousUserMessage.trim()}
                        onClick={() => void submitMessage(previousUserMessage)}
                      >
                        <RotateCcw size={17} />
                      </button>
                      <button
                        type="button"
                        className="messageActionButton"
                        title="朗读"
                        aria-label="朗读"
                        onClick={() => speakAssistantAnswer(message.content)}
                      >
                        <Volume2 size={17} />
                      </button>
                    </div>
                  ) : null}
                </div>
              </article>
            );
          })}
        </section>

        {showJumpToLatest ? (
          <button
            className="jumpToLatest"
            type="button"
            onClick={() => scrollMessagesToBottom()}
          >
            跳到最新
          </button>
        ) : null}

        {turnFeedbackNotice ? <p className="feedbackNotice compactFeedbackNotice">{turnFeedbackNotice}</p> : null}

        <div className="composerDock compactComposerDock">
          <div className="effortBar" aria-label="思考强度">
            <span>
              <Gauge size={14} />
              思考强度
            </span>
            <div className="segmentedControl">
              {thinkingEffortOptions.map((option) => {
                const optionPlan = runtimePlan(status, option.value);
                const timeoutSeconds =
                  optionPlan?.timeout_seconds ??
                  thinkingEffortTimeoutSeconds(status?.model_timeout_seconds, option.value);
                const tokenBudget =
                  optionPlan?.num_predict ?? thinkingEffortTokenBudget(status?.model_num_predict, option.value);
                const runLabel = thinkingEffortRunLabel(option.value, status);
                return (
                  <button
                    key={option.value}
                    type="button"
                    className={thinkingEffort === option.value ? "active" : ""}
                    onClick={() => chooseThinkingEffort(option.value)}
                    aria-pressed={thinkingEffort === option.value}
                    title={`最长等待 ${timeoutSeconds} 秒，回答预算 ${tokenBudget} token；${runLabel}`}
                  >
                    {option.label}
                  </button>
                );
              })}
            </div>
            <strong>
              {activeThinkingRunLabel} / 回答预算 {activeThinkingTokenBudget} token
            </strong>
          </div>

          <form className="composer" onSubmit={onSubmit}>
            <Search size={18} />
            <input
              value={input}
              onChange={(event) => updateComposerInput(event.target.value)}
              placeholder={`直接和 ${selectedPersona.name} 说话...`}
            />
            {isSending ? (
              <button
                className="composerStopButton"
                type="button"
                onClick={() => cancelActiveTurn("你手动停止了本轮生成。")}
                title="停止生成"
              >
                <CircleSlash size={15} />
                <span>停止</span>
              </button>
            ) : null}
            <button className="composerSendButton" disabled={isSending || !input.trim()} type="submit">
              发送
            </button>
          </form>
        </div>
      </section>
    </main>
  );

}
