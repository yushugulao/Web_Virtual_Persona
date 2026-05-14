import { useState } from "react";
import {
  BadgeCheck,
  Brain,
  ClipboardList,
  Database,
  FileSearch,
  FileText,
  Gauge,
  Layers,
  Link2,
  MessageSquareText,
  RefreshCw
} from "lucide-react";
import type {
  BrowserAcceptanceCase,
  BrowserAcceptanceMatrixResponse,
  ChatResponse,
  Citation,
  EvidenceCardStats,
  EvalRunListItem,
  MemoryItem,
  MemoryStatsResponse,
  PersonaMaterialDocument,
  PersonaProfile,
  PersonaTurnFeedbackStatsResponse,
  RetrievalTrace,
  StatusResponse,
  UiMessage
} from "../../types";

function countLabel(count: number, unit: string) {
  return `${count} ${unit}`;
}

function formatLatency(ms: number | undefined) {
  if (ms === undefined || Number.isNaN(ms)) return "???";
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)} ?`;
  return `${Math.round(ms)} ??`;
}

function formatPercent(value: number | undefined) {
  if (value === undefined || Number.isNaN(value)) return "???";
  return `${Math.round(value * 100)}%`;
}

function formatRunTime(ts: number | undefined) {
  if (!ts) return "??";
  const millis = ts > 10_000_000_000 ? ts : ts * 1000;
  return new Date(millis).toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit"
  });
}

const sourceTypeLabels: Record<string, string> = {
  profile: "????",
  resume: "??",
  project: "??",
  values: "???",
  thinking_style: "????",
  colleague: "????",
  qa_seed: "????",
  negative_fact: "????",
  memory: "??",
  converted_pdf: "????",
  safety_policy: "????",
  loading: "???"
};

const trustLevelLabels: Record<string, string> = {
  verified: "???",
  synthetic: "??",
  inferred: "??",
  user_memory: "??"
};

const privacyLevelLabels: Record<string, string> = {
  public: "??",
  private: "??",
  sensitive: "??"
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
  ["????", "????"],
  ["??", "??"],
  ["????", "?????"],
  ["????", "????"],
  ["Retrieval mode", "????"],
  ["retrieval mode", "????"],
  ["Evidence Policy", "????"],
  ["source family", "????"],
  ["citation", "??"],
  ["citations", "??"],
  ["query rewrite", "????"],
  ["source selector", "????"],
  ["hybrid retrieval", "????"],
  ["keyword retrieval", "?????"],
  ["semantic retrieval", "????"]
];

function evidenceCardPersonaLabelFromPrefix(prefix: string | undefined): string {
  const labels: Record<string, string> = {
    franklin: "????",
    tesla: "???",
    keller: "??",
    darwin: "Darwin"
  };
  return prefix ? labels[prefix] ?? prefix : "??";
}

function displayArchiveText(value: string): string {
  return archiveTextReplacements
    .reduce((current, [needle, replacement]) => current.split(needle).join(replacement), value)
    .replace(/\b(Franklin|Tesla|Keller|Darwin)\s+Evidence Cards\s+(\d+)\b/gi, (_match, prefix: string, batch: string) =>
      `${evidenceCardPersonaLabelFromPrefix(prefix.toLowerCase())}???? ${batch}`
    )
    .replace(/\bevidence-card\b/gi, "????");
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

function displayDocumentTitle(document: PersonaMaterialDocument): string {
  if (isEvidenceCardDocument(document)) {
    const batch = document.title.match(/\bEvidence Cards\s+(\d+)/i)?.[1];
    return `${evidenceCardPersonaLabel(document.title)}????${batch ? ` ${batch}` : ""}`;
  }
  return displayArchiveText(document.title);
}

function displayArchivePreview(value: string): string {
  return displayArchiveText(value).trim();
}

function displayCitationTitle(citation: Citation) {
  if (citation.doc_id.startsWith("safety_policy")) return "????";
  return displayArchiveText(citation.title);
}

const feedbackIssueLabels: Record<string, string> = {
  good: "??",
  other: "???",
  cardiness: "????",
  lecture: "??",
  too_long: "??",
  unnatural: "???",
  memory_error: "????",
  era_boundary_error: "????"
};

function feedbackIssueLabel(issue: string) {
  return feedbackIssueLabels[issue] ?? issue;
}

function feedbackSeverityLabel(severity: string) {
  if (severity === "high") return "?";
  if (severity === "medium") return "?";
  if (severity === "low") return "?";
  return severity;
}

type MaterialExplorerProps = {
  className?: string;
  documents: PersonaMaterialDocument[];
  evidenceStats?: EvidenceCardStats;
  error: boolean;
  loading: boolean;
  selectedId: string;
  onSelect: (docId: string) => void;
};

export function MaterialExplorer({
  className = "",
  documents,
  evidenceStats,
  error,
  loading,
  selectedId,
  onSelect
}: MaterialExplorerProps) {
  const [showEvidenceCards, setShowEvidenceCards] = useState(false);
  const coreDocuments = documents.filter((document) => !isEvidenceCardDocument(document));
  const evidenceCardDocuments = documents.filter(isEvidenceCardDocument);
  const evidenceCardChunkCount = evidenceCardDocuments.reduce(
    (total, document) => total + document.chunk_count,
    0
  );
  const visibleDocuments = showEvidenceCards
    ? [...coreDocuments, ...evidenceCardDocuments]
    : coreDocuments.length
      ? coreDocuments
      : documents;
  const selectedDocument =
    visibleDocuments.find((document) => document.doc_id === selectedId) ??
    visibleDocuments[0] ??
    documents[0] ??
    null;

  return (
    <section className={`tracePanel materialExplorer ${className}`}>
      <div className="materialHeader">
        <div>
          <p className="eyebrow">档案</p>
          <h3>资料浏览</h3>
        </div>
        <span>
          {loading
            ? "读取中"
            : evidenceCardDocuments.length
              ? `${countLabel(coreDocuments.length, "份核心文档")} + ${countLabel(
                  evidenceCardDocuments.length,
                  "组证据卡片"
                )}`
              : countLabel(documents.length, "份")}
        </span>
      </div>

      {evidenceStats ? (
        <div className="evidenceStoreBadge">
          <Database size={14} />
          <span>
            typed evidence store：{countLabel(evidenceStats.total_cards, "张卡片")} /{" "}
            {countLabel(evidenceStats.source_title_count, "个来源")}
            {evidenceStats.manifest_matches_store ? "，已和清单对齐" : "，需要重建"}
          </span>
        </div>
      ) : null}

      {error ? (
        <p className="materialEmpty">资料暂时不可用，请确认后端服务在线。</p>
      ) : null}

      {!error && !loading && !documents.length ? (
        <p className="materialEmpty">当前分身还没有可展示的资料。</p>
      ) : null}

      {documents.length ? (
        <>
          <div className="materialList" aria-label="资料列表">
            {evidenceCardDocuments.length ? (
              <button
                type="button"
                className={`materialGroupButton ${showEvidenceCards ? "active" : ""}`}
                onClick={() => setShowEvidenceCards((current) => !current)}
                aria-pressed={showEvidenceCards}
              >
                <Layers size={14} />
                <span>
                  <strong>{showEvidenceCards ? "收起证据卡片批次" : "证据卡片批次"}</strong>
                  <small>
                    {countLabel(evidenceCardDocuments.length, "组")} / {countLabel(evidenceCardChunkCount, "段")}，用于支撑长尾事实召回
                  </small>
                </span>
              </button>
            ) : null}
            {visibleDocuments.map((document) => (
              <button
                key={document.doc_id}
                className={document.doc_id === selectedDocument?.doc_id ? "active" : ""}
                onClick={() => onSelect(document.doc_id)}
              >
                <FileText size={14} />
                <span>
                  <strong>{displayDocumentTitle(document)}</strong>
                  <small>
                    {sourceTypeLabel(document.source_type)} / {countLabel(document.chunk_count, "段")}
                  </small>
                </span>
              </button>
            ))}
          </div>

          {selectedDocument ? (
            <div className="materialDetail">
              <div className="materialDetailMeta">
                <span>{trustLevelLabel(selectedDocument.trust_level)}</span>
                <span>{privacyLevelLabel(selectedDocument.privacy_level)}</span>
              </div>
              <code>文档 ID：{selectedDocument.doc_id}</code>
              <p>{displayArchivePreview(selectedDocument.preview)}</p>
              {selectedDocument.sections.length ? (
                <div className="sectionChips" aria-label="档案章节">
                  {selectedDocument.sections.map((section) => (
                    <span key={section}>{displayArchiveText(section)}</span>
                  ))}
                </div>
              ) : null}
            </div>
          ) : null}
        </>
      ) : null}
    </section>
  );
}

type EvidenceBlockProps = {
  citation: Citation | null;
};

export function EvidenceBlock({ citation }: EvidenceBlockProps) {
  if (!citation) {
    return (
      <section className="emptyEvidence">
        <FileSearch size={24} />
        <p>有档案依据的回答会在这里显示片段；会话记忆、寒暄或边界回应可能不引用档案。</p>
      </section>
    );
  }

  return (
    <section className="evidenceCard">
      <div className="evidenceTitle">
        <BadgeCheck size={18} />
        <h3>{displayCitationTitle(citation)}</h3>
      </div>
      <dl className="evidenceMeta">
        <div>
          <dt>绔犺妭</dt>
          <dd>{displayArchiveText(citation.section_path)}</dd>
        </div>
        <div>
          <dt>匹配</dt>
          <dd>{citation.score.toFixed(3)}</dd>
        </div>
        <div>
          <dt>核验</dt>
          <dd>{trustLevelLabel(citation.trust_level)}</dd>
        </div>
        <div>
          <dt>隐私</dt>
          <dd>{privacyLevelLabel(citation.privacy_level)}</dd>
        </div>
      </dl>
      <p className="preview">{displayArchivePreview(citation.preview)}</p>
    </section>
  );
}

type SourceRegistryProps = {
  persona: PersonaProfile;
  documents: PersonaMaterialDocument[];
  evidenceStats?: EvidenceCardStats;
  expanded?: boolean;
};

export function SourceRegistry({ persona, documents, evidenceStats, expanded = false }: SourceRegistryProps) {
  const coreDocuments = documents.filter((document) => !isEvidenceCardDocument(document));
  const evidenceCardDocuments = documents.filter(isEvidenceCardDocument);
  const evidenceCardChunkCount = evidenceCardDocuments.reduce(
    (total, document) => total + document.chunk_count,
    0
  );
  const displayedDocuments = expanded ? coreDocuments : coreDocuments.slice(0, 4);

  return (
    <section className="tracePanel sourceRegistry">
      <h3>本地档案来源</h3>
      <div className="sourceSummary">
        <FileText size={16} />
        <span>{countLabel(persona.corpus_paths.length, "组已审阅档案")}</span>
      </div>
      <div className="sourceSummary">
        <Layers size={16} />
        <span>{countLabel(persona.raw_source_paths?.length ?? 0, "份公开原文")}</span>
      </div>
      {evidenceStats ? (
        <div className="sourceSummary">
          <Database size={16} />
          <span>
            {countLabel(evidenceStats.by_persona[persona.id] ?? 0, "张 typed 证据卡")}
          </span>
        </div>
      ) : null}
      <div className="sourceSummary">
        <Link2 size={16} />
        <span>
          {(persona.source_urls?.length ?? 0) > 0
            ? persona.source_urls?.map(hostLabel).join(", ")
            : "暂无公开来源链接"}
        </span>
      </div>
      <div className="sourceList" aria-label="来源列表">
        {displayedDocuments.length ? (
          <>
            {displayedDocuments.map((document) => (
              <code key={document.doc_id}>{displayDocumentTitle(document)}</code>
            ))}
            {evidenceCardDocuments.length ? (
              <code>
                证据卡片批次：{countLabel(evidenceCardDocuments.length, "组")} /{" "}
                {countLabel(evidenceCardChunkCount, "段")}
              </code>
            ) : null}
          </>
        ) : (
          <code>
            {evidenceCardDocuments.length
              ? `证据卡片批次：${countLabel(evidenceCardDocuments.length, "组")} / ${countLabel(evidenceCardChunkCount, "段")}`



              : "暂无可展示档案"}
          </code>
        )}
      </div>
    </section>
  );
}

type TraceDetailsProps = {
  activeTrace: RetrievalTrace | undefined;
  latestResponse: ChatResponse | undefined;
  selectedPersonaId: string;
};

export function TraceDetails({ activeTrace, latestResponse, selectedPersonaId }: TraceDetailsProps) {
  const evidencePolicyNote = activeTrace?.notes.find((note) => note.startsWith("Evidence Policy V2"));
  return (
    <details className="tracePanel traceDetails">
      <summary>运行记录</summary>
      <div className="traceLine">
        <span>人物</span>
        <strong>{activeTrace?.persona_id ?? selectedPersonaId}</strong>
      </div>
      <div className="traceLine">
        <span>问题</span>
        <strong>{activeTrace?.original_query ?? "尚未提问"}</strong>
      </div>
      <div className="traceLine">
        <span>片段</span>
        <strong>{countLabel(activeTrace?.selected_chunk_ids.length ?? 0, "段")}</strong>
      </div>
      <div className="traceLine">
        <span>耗时</span>
        <strong>{formatLatency(latestResponse?.timings.total_ms)}</strong>
      </div>
      <div className="traceLine">
        <span>依据校验</span>
        <strong>
          {latestResponse
            ? `${latestResponse.verification.supported_claim_count}/${latestResponse.verification.claim_count}`
            : "0/0"}
        </strong>
      </div>
      {evidencePolicyNote ? (
        <div className="traceLine">
          <span>证据策略</span>
          <strong>{displayArchiveText(evidencePolicyNote)}</strong>
        </div>
      ) : null}
      <div className="traceNotes">
        {(activeTrace?.notes ?? ["第一次问答后会生成运行记录。"]).map((note) => (
          <p key={note}>{displayArchiveText(note)}</p>
        ))}
      </div>
    </details>
  );
}

type MemoryPanelProps = {
  messages: UiMessage[];
  sessionId?: string;
  status?: StatusResponse;
  personaName: string;
  personaId: string;
  memoryItems: MemoryItem[];
  memoryStats?: MemoryStatsResponse;
  loading: boolean;
  onPropose: (content: string) => void;
  onApprove: (id: string) => void;
  onReject: (id: string) => void;
  onRetract: (id: string) => void;
};

export function MemoryPanel({
  messages,
  sessionId,
  status,
  personaName,
  personaId,
  memoryItems,
  memoryStats,
  loading,
  onPropose,
  onApprove,
  onReject,
  onRetract
}: MemoryPanelProps) {
  const recentMessages = messages.slice(-6);
  const [draftMemory, setDraftMemory] = useState("");
  const pendingItems = memoryItems.filter((item) => item.status === "pending");
  const approvedItems = memoryItems.filter((item) => item.status === "approved");
  const inactiveItems = memoryItems.filter((item) =>
    ["rejected", "retracted", "expired"].includes(item.status)
  );

  function submitDraftMemory() {
    const content = draftMemory.trim();
    if (!content) return;
    onPropose(content);
    setDraftMemory("");
  }

  return (
    <>
      <section className="tracePanel memoryPanel">
        <h3>长期记忆审批</h3>
        <p className="panelHint">
          普通聊天不会自动写入长期记忆；只有“记住：...”或下方手动提交会进入这里。历史人物只会把它称为“你先前告诉我...”，不会当作本人传记事实。
        </p>
        <div className="memoryComposer">
          <textarea
            value={draftMemory}
            onChange={(event) => setDraftMemory(event.target.value)}
            placeholder="写入一条希望系统记住的用户信息"
          />
          <button className="panelActionButton" type="button" onClick={submitDraftMemory}>
            提交待确认
          </button>
        </div>
        <div className="traceLine">
          <span>待确认</span>
          <strong>{loading ? "读取中" : countLabel(pendingItems.length, "条")}</strong>
        </div>
        <div className="traceLine">
          <span>已批准</span>
          <strong>{loading ? "读取中" : countLabel(approvedItems.length, "条")}</strong>
        </div>
        <div className="traceLine">
          <span>后端记忆表</span>
          <strong>{countLabel(memoryStats?.total ?? status?.memory_item_rows ?? memoryItems.length, "条")}</strong>
        </div>
        <div className="traceLine">
          <span>当前对象</span>
          <strong>{countLabel(memoryStats?.by_persona_status?.[personaId]?.approved ?? approvedItems.length, "条已批准")}</strong>
        </div>
        <div className="traceLine">
          <span>待确认</span>
          <strong>{countLabel(memoryStats?.by_status?.pending ?? pendingItems.length, "条")}</strong>
        </div>
      </section>

      <MemoryItemList
        title="待确认记忆"
        items={pendingItems}
        emptyText="没有待确认记忆。"
        onApprove={onApprove}
        onReject={onReject}
        onRetract={onRetract}
      />
      <MemoryItemList
        title="已批准记忆"
        items={approvedItems}
        emptyText="没有已批准记忆。"
        onApprove={onApprove}
        onReject={onReject}
        onRetract={onRetract}
      />
      <MemoryItemList
        title="已拒绝 / 已撤回"
        items={inactiveItems}
        emptyText="没有已拒绝或已撤回记忆。"
        onApprove={onApprove}
        onReject={onReject}
        onRetract={onRetract}
      />

      <section className="tracePanel memoryPanel">
        <h3>短期会话记忆</h3>
        <p className="panelHint">
          当前页面会保留本轮对话，后端也会按会话编号保存问答记录，用来回答“我刚刚问了什么”这类问题。
        </p>
        <div className="traceLine">
          <span>当前人物</span>
          <strong>{personaName}</strong>
        </div>
        <div className="traceLine">
          <span>会话编号</span>
          <strong>{sessionId || "未创建"}</strong>
        </div>
        <div className="traceLine">
          <span>本轮消息</span>
          <strong>{countLabel(messages.length, "条")}</strong>
        </div>
        <div className="traceLine">
          <span>后端记录</span>
          <strong>{countLabel(status?.chat_event_rows ?? 0, "条")}</strong>
        </div>
      </section>

      <section className="tracePanel memoryPanel">
        <h3>最近消息</h3>
        {recentMessages.length ? (
          <div className="memoryList">
            {recentMessages.map((message) => (
              <article key={message.id}>
                <span>{message.role === "assistant" ? personaName : "你"}</span>
                <p>{message.content}</p>
              </article>
            ))}
          </div>
        ) : (
          <p className="materialEmpty">还没有新的对话。发送第一条消息后，这里会显示当前会话的短期记忆。</p>
        )}
      </section>
    </>
  );
}

type MemoryItemListProps = {
  title: string;
  items: MemoryItem[];
  emptyText: string;
  onApprove: (id: string) => void;
  onReject: (id: string) => void;
  onRetract: (id: string) => void;
};

function MemoryItemList({
  title,
  items,
  emptyText,
  onApprove,
  onReject,
  onRetract
}: MemoryItemListProps) {
  return (
    <section className="tracePanel memoryPanel">
      <h3>{title}</h3>
      {items.length ? (
        <div className="memoryList">
          {items.map((item) => (
            <article key={item.id}>
              <div className="memoryItemHeader">
                <span>{memoryStatusLabel(item.status)}</span>
                <code>{item.memory_type}</code>
              </div>
              <p>{item.content}</p>
              <div className="memoryMeta">
                <span>{item.sensitivity === "sensitive" ? "敏感待审" : "普通"}</span>
                <span>{item.scope}</span>
              </div>
              <div className="memoryActions">
                {item.status !== "approved" ? (
                  <button type="button" onClick={() => onApprove(item.id)}>
                    批准
                  </button>
                ) : null}
                {item.status === "pending" ? (
                  <button type="button" onClick={() => onReject(item.id)}>
                    拒绝
                  </button>
                ) : null}
                {item.status === "approved" || item.status === "pending" ? (
                  <button type="button" onClick={() => onRetract(item.id)}>
                    撤回
                  </button>
                ) : null}
              </div>
            </article>
          ))}
        </div>
      ) : (
        <p className="materialEmpty">{emptyText}</p>
      )}
    </section>
  );
}

function memoryStatusLabel(status: string) {
  if (status === "pending") return "待确认";
  if (status === "approved") return "已批准";
  if (status === "rejected") return "已拒绝";
  if (status === "retracted") return "已撤回";
  if (status === "expired") return "已过期";
  return status;
}

type EvaluationPanelProps = {
  latestRetrievalEval?: EvalRunListItem;
  latestChatEval?: EvalRunListItem;
  latestJudgeEval?: EvalRunListItem;
  feedbackStats?: PersonaTurnFeedbackStatsResponse;
  feedbackLoading: boolean;
  feedbackError: boolean;
  acceptanceMatrix?: BrowserAcceptanceMatrixResponse;
  acceptanceMatrixLoading: boolean;
  acceptanceMatrixError: boolean;
  activePersonaId: string;
  loading: boolean;
  error: boolean;
  isRunning: boolean;
  notice: string;
  onRefresh: () => void;
  onRunRetrieval: () => void;
  onRunJudge: () => void;
  onUseAcceptancePrompt: (caseItem: BrowserAcceptanceCase) => void;
};

export function EvaluationPanel({
  latestRetrievalEval,
  latestChatEval,
  latestJudgeEval,
  feedbackStats,
  feedbackLoading,
  feedbackError,
  acceptanceMatrix,
  acceptanceMatrixLoading,
  acceptanceMatrixError,
  activePersonaId,
  loading,
  error,
  isRunning,
  notice,
  onRefresh,
  onRunRetrieval,
  onRunJudge,
  onUseAcceptancePrompt
}: EvaluationPanelProps) {
  return (
    <>
      <section className="tracePanel evaluationPanel">
        <div className="materialHeader">
          <div>
            <p className="eyebrow">操作</p>
            <h3>本地评测</h3>
          </div>
          <span>{loading ? "读取中" : "可执行"}</span>
        </div>
        <p className="panelHint">
          检索评测会检查档案命中、引用精度、排序和延迟；Judge 评测会额外调用本地模型检查人格一致性、时代边界和自然度。
        </p>
        <div className="panelActionRow">
          <button className="panelActionButton" onClick={onRunRetrieval} disabled={isRunning}>
            <Gauge size={14} />
            {isRunning ? "评测中" : "运行检索评测"}
          </button>
          <button className="panelActionButton" onClick={onRunJudge} disabled={isRunning}>
            <Brain size={14} />
            {isRunning ? "评测中" : "运行 Judge 评测"}
          </button>
          <button className="panelActionButton secondary" onClick={onRefresh} disabled={isRunning}>
            <RefreshCw size={14} />
            刷新记录
          </button>
        </div>
        {notice ? <p className="panelNotice">{notice}</p> : null}
        {error ? <p className="panelNotice warning">评测记录暂时不可用，请确认后端服务在线。</p> : null}
      </section>

      <FeedbackStatsCard stats={feedbackStats} loading={feedbackLoading} error={feedbackError} />
      <BrowserAcceptanceMatrixCard
        matrix={acceptanceMatrix}
        loading={acceptanceMatrixLoading}
        error={acceptanceMatrixError}
        activePersonaId={activePersonaId}
        onUsePrompt={onUseAcceptancePrompt}
      />
      <EvalRunCard title="最近检索评测" run={latestRetrievalEval} />
      <EvalRunCard title="最近对话评测" run={latestChatEval} />
      <EvalRunCard title="最近 Judge 评测" run={latestJudgeEval} />
    </>
  );
}

type FeedbackStatsCardProps = {
  stats?: PersonaTurnFeedbackStatsResponse;
  loading: boolean;
  error: boolean;
};

type BrowserAcceptanceMatrixCardProps = {
  matrix?: BrowserAcceptanceMatrixResponse;
  loading: boolean;
  error: boolean;
  activePersonaId: string;
  onUsePrompt: (caseItem: BrowserAcceptanceCase) => void;
};

function BrowserAcceptanceMatrixCard({
  matrix,
  loading,
  error,
  activePersonaId,
  onUsePrompt
}: BrowserAcceptanceMatrixCardProps) {
  const categories = matrix?.categories ?? [];
  const activeCases = (matrix?.cases ?? []).filter((item) => item.persona_id === activePersonaId);
  const groupedCases = categories
    .map((category) => ({
      category,
      cases: activeCases.filter((item) => item.category_id === category.category_id)
    }))
    .filter((group) => group.cases.length > 0);
  const personaLabel =
    matrix?.personas.find((persona) => persona.persona_id === activePersonaId)?.display_name ??
    activePersonaId;
  const activeCaseIds = new Set(activeCases.map((item) => item.case_id));
  const activeFeedbackRows = Object.entries(matrix?.case_feedback ?? {}).filter(([caseId]) =>
    activeCaseIds.has(caseId)
  );
  const testedCaseCount = activeFeedbackRows.filter(
    ([, feedback]) => feedback.matched_feedback_count > 0
  ).length;
  const negativeCaseCount = activeFeedbackRows.filter(
    ([, feedback]) => feedback.negative_feedback_count > 0
  ).length;
  const positiveCaseCount = activeFeedbackRows.filter(
    ([, feedback]) => feedback.positive_feedback_count > 0
  ).length;
  const personaProgressRows = (matrix?.personas ?? []).map((persona) => {
    const personaCases = (matrix?.cases ?? []).filter((item) => item.persona_id === persona.persona_id);
    const personaCaseIds = new Set(personaCases.map((item) => item.case_id));
    const personaFeedbackRows = Object.entries(matrix?.case_feedback ?? {}).filter(([caseId]) =>
      personaCaseIds.has(caseId)
    );
    const tested = personaFeedbackRows.filter(
      ([, feedback]) => feedback.matched_feedback_count > 0
    ).length;
    const negative = personaFeedbackRows.filter(
      ([, feedback]) => feedback.negative_feedback_count > 0
    ).length;
    const positive = personaFeedbackRows.filter(
      ([, feedback]) => feedback.positive_feedback_count > 0
    ).length;
    return {
      personaId: persona.persona_id,
      label: persona.display_name,
      total: personaCases.length,
      tested,
      negative,
      positive
    };
  });

  return (
    <section className="tracePanel acceptanceMatrixPanel">
      <div className="evalRunTitle">
        <ClipboardList size={16} />
        <h3>浏览器验收矩阵</h3>
      </div>
      <p className="panelHint">
        按这些问题手动聊天，再用回答下方反馈按钮标记问题。重复失败会先进入 harvest 报告，再升级为正式评测用例。
      </p>
      {error ? <p className="panelNotice warning">验收矩阵暂时不可用，请确认 8001 后端在线。</p> : null}
      <div className="traceLine">
        <span>当前人物</span>
        <strong>{loading ? "读取中" : personaLabel}</strong>
      </div>
      <div className="traceLine">
        <span>覆盖范围</span>
        <strong>
          {loading ? "读取中" : `${activeCases.length} 个用例 / ${groupedCases.length} 组`}
        </strong>
      </div>
      <div className="acceptanceProgressGrid" aria-label="验收进度">
        <span>
          已测
          <strong>
            {testedCaseCount}/{activeCases.length}
          </strong>
        </span>
        <span>
          负反馈
        </span>
        <span>
          正反馈
        </span>
      </div>
      <div className="acceptancePersonaProgressList" aria-label="all-persona acceptance progress">
        {personaProgressRows.map((row) => (
          <div
            key={row.personaId}
            className={row.personaId === activePersonaId ? "active" : undefined}
          >
            <strong>{row.label}</strong>
            <span>
              {row.tested}/{row.total} 已测 · {row.negative} 负反馈 · {row.positive} 正反馈
            </span>
          </div>
        ))}
      </div>
      <div className="acceptanceCategoryList">
        {groupedCases.map(({ category, cases }) => (
          <details key={category.category_id}>
            <summary>
              <span>{category.label}</span>
              <strong>{cases.length}</strong>
            </summary>
            <div className="acceptancePromptList">
              {cases.map((item) => {
                const feedback = matrix?.case_feedback?.[item.case_id];
                const isTested = Boolean(feedback?.matched_feedback_count);
                const hasNegativeFeedback = Boolean(feedback?.negative_feedback_count);
                const isRetestedGood = hasNegativeFeedback && feedback?.latest_issue === "good";
                const statusLabel = !isTested
                  ? "未测"
                  : isRetestedGood
                  ? "已复测"
                  : hasNegativeFeedback
                    ? `问题 ${feedback?.negative_feedback_count}`
                    : `通过 ${feedback?.positive_feedback_count || feedback?.matched_feedback_count}`;
                const statusClassName = !isTested
                  ? "matrixStatus"
                  : isRetestedGood
                    ? "matrixStatus resolved"
                  : hasNegativeFeedback
                    ? "matrixStatus bad"
                    : "matrixStatus good";
                return (
                  <button
                    key={item.case_id}
                    type="button"
                    title={item.expected_behavior}
                    onClick={() => onUsePrompt(item)}
                  >
                    <span>{item.prompt}</span>
                    <small>{item.expected_behavior}</small>
                    <code className={statusClassName}>{statusLabel}</code>
                  </button>
                );
              })}
            </div>
          </details>
        ))}
      </div>
      {!loading && !activeCases.length ? (
        <p className="materialEmpty">当前人物还没有验收矩阵。</p>
      ) : null}
    </section>
  );
}

function FeedbackStatsCard({ stats, loading, error }: FeedbackStatsCardProps) {
  const issueRows = Object.entries(stats?.by_issue ?? {}).sort((first, second) => second[1] - first[1]);
  const latestRecords = stats?.latest_records ?? [];
  const topIssue = issueRows[0];

  return (
    <section className="tracePanel feedbackStatsPanel">
      <div className="evalRunTitle">
        <MessageSquareText size={16} />
        <h3>浏览器反馈</h3>
      </div>
      <p className="panelHint">
        这里汇总前端按钮收集到的自然度反馈。单条负面反馈只进入候选池，重复出现后再升级为正式评测用例。
      </p>
      {error ? <p className="panelNotice warning">反馈统计暂时不可用，请确认 8001 后端在线。</p> : null}
      <div className="traceLine">
        <span>总反馈</span>
        <strong>{loading ? "读取中" : countLabel(stats?.total ?? 0, "条")}</strong>
      </div>
      <div className="traceLine">
        <span>负面候选</span>
        <strong>{loading ? "读取中" : countLabel(stats?.negative_total ?? 0, "条")}</strong>
      </div>
      <div className="traceLine">
        <span>正向样本</span>
        <strong>{loading ? "读取中" : countLabel(stats?.positive_total ?? 0, "条")}</strong>
      </div>
      <div className="traceLine">
        <span>最高频问题</span>
        <strong>{topIssue ? `${feedbackIssueLabel(topIssue[0])} / ${topIssue[1]} 次` : "暂无"}</strong>
      </div>

      {issueRows.length ? (
        <div className="feedbackIssueGrid" aria-label="反馈问题分布">
          {issueRows.map(([issue, count]) => (
            <span key={issue}>
              {feedbackIssueLabel(issue)}
              <strong>{count}</strong>
            </span>
          ))}
        </div>
      ) : (
        <p className="materialEmpty">还没有浏览器反馈。和分身聊几轮后，可以用回答下方按钮留下样本。</p>
      )}

      {latestRecords.length ? (
        <div className="feedbackSampleList">
          {latestRecords.map((record) => (
            <article key={record.feedback_id}>
              <div className="memoryItemHeader">
                <span>{feedbackIssueLabel(record.issue)}</span>
                <code>{feedbackSeverityLabel(record.severity)}</code>
              </div>
              <p>{record.user_message}</p>
              <small>
                {record.persona_name ?? record.persona_id} / {record.mode ?? "unknown"}
              </small>
            </article>
          ))}
        </div>
      ) : null}
    </section>
  );
}

type EvalRunCardProps = {
  title: string;
  run?: EvalRunListItem;
};

function EvalRunCard({ title, run }: EvalRunCardProps) {
  return (
    <section className="tracePanel evalRunCard">
      <div className="evalRunTitle">
        <ClipboardList size={16} />
        <h3>{title}</h3>
      </div>
      {run ? (
        <>
          <div className="traceLine">
            <span>运行时间</span>
            <strong>{formatRunTime(run.ts)}</strong>
          </div>
          <div className="traceLine">
            <span>通过率</span>
            <strong>{formatPercent(run.metrics.pass_rate)}</strong>
          </div>
          <div className="traceLine">
            <span>用例</span>
            <strong>
              {run.passed_count}/{run.question_count}
            </strong>
          </div>
          <div className="traceLine">
            <span>引用精度</span>
            <strong>{formatPercent(run.metrics.mean_citation_precision)}</strong>
          </div>
          <div className="traceLine">
            <span>Top-1</span>
            <strong>{formatPercent(run.metrics.top1_accuracy)}</strong>
          </div>
          {run.mode === "judge" ? (
            <>
              <div className="traceLine">
                <span>Judge 通过</span>
                <strong>{formatPercent(run.metrics.judge_pass_rate ?? 0)}</strong>
              </div>
              <div className="traceLine">
                <span>Judge 均分</span>
                <strong>{(run.metrics.mean_judge_score ?? 0).toFixed(2)}</strong>
              </div>
              <div className="traceLine">
                <span>最低维度</span>
                <strong>
                  {run.metrics.weakest_judge_dimension ?? "n/a"}
                  {typeof run.metrics.weakest_judge_score === "number"
                    ? ` (${formatPercent(run.metrics.weakest_judge_score)})`
                    : ""}
                </strong>
              </div>
            </>
          ) : null}
          <div className="traceLine">
            <span>平均延迟</span>
            <strong>{formatLatency(run.metrics.mean_latency_ms)}</strong>
          </div>
        </>
      ) : (
        <p className="materialEmpty">暂无评测记录。</p>
      )}
    </section>
  );
}
