import { useEffect, useRef } from "react";
import { Eye } from "lucide-react";
import type {
  ChatDiagnostics,
  ChatResponse,
  HiddenThinkingEvent,
  StatusResponse,
  StreamStageEvent,
  ThinkingEffort
} from "../../types";

function runtimePlan(status: StatusResponse | null | undefined, effort: ThinkingEffort) {
  return status?.effort_runtime_plans?.[effort];
}

function estimateThinkingTokens(text: string) {
  if (!text.trim()) {
    return 0;
  }
  const cjkCount = (text.match(/[\u3400-\u9fff]/g) ?? []).length;
  const latinWordCount = (text.match(/[A-Za-z0-9_]+/g) ?? []).length;
  const punctuationCount = Math.max(0, text.length - cjkCount);
  return Math.max(1, Math.round(cjkCount * 0.75 + latinWordCount * 1.15 + punctuationCount * 0.08));
}

function hiddenThinkingText(events?: HiddenThinkingEvent[]) {
  return (events ?? [])
    .map((event) => event.content)
    .filter(Boolean)
    .join("\n");
}

function thinkingEffortTokenBudget(baseTokenBudget: number | undefined, effort: ThinkingEffort) {
  const base = baseTokenBudget ?? 1280;
  const multiplier = effort === "high" ? 2 : effort === "medium" ? 1.4 : 1;
  return Math.round(base * multiplier);
}

function displayThinkingBudget(status: StatusResponse | null | undefined, effort: ThinkingEffort) {
  const plan = runtimePlan(status, effort);
  if (plan?.display_thinking_budget) return plan.display_thinking_budget;
  if (effort === "low") return 2000;
  if (effort === "medium") return 4000;
  return plan?.thinking_budget ?? thinkingEffortTokenBudget(undefined, effort);
}

function formatLatency(ms: number | undefined) {
  if (ms === undefined || Number.isNaN(ms)) return "--";
  if (ms < 1000) return `${Math.round(ms)} 毫秒`;
  return `${(ms / 1000).toFixed(1)} 秒`;
}

type ProcessTimelineProps = {
  activeStage: StreamStageEvent | null;
  isSending: boolean;
  latestResponse?: ChatResponse;
  liveElapsedMs: number;
  releaseNotice?: string;
};

export function ProcessTimeline({
  activeStage,
  isSending,
  latestResponse,
  liveElapsedMs,
  releaseNotice
}: ProcessTimelineProps) {
  const readableTimingRows = latestResponse
    ? [
        ["检索 / 事实刹车", latestResponse.timings.retrieval_ms],
        ["上下文组织", latestResponse.timings.context_ms],
        ["思考生成", latestResponse.timings.generation_ms],
        ["校验收尾", latestResponse.timings.verification_ms]
      ]
    : [];
  const readableLiveLabel = isSending
    ? activeStage?.label ?? "等待后端"
    : latestResponse
      ? "上轮完成"
      : "等待提问";
  const readableLiveDetail = isSending
    ? activeStage?.detail ?? "请求已发送。"
    : latestResponse
      ? `回答已完成 · 本轮耗时 ${formatLatency(latestResponse.timings.total_ms)}`
      : "发送消息后，这里会显示当前步骤和耗时。";
  const readableElapsed = isSending ? liveElapsedMs : latestResponse?.timings.total_ms;
  const readableInlineDetail = !isSending && Boolean(latestResponse);

  return (
    <section className="processTimeline" aria-label="当前步骤">
      <div className="timelineHeader">
        <div className="timelineTitleBlock">
          <p className="eyebrow">步骤</p>
          <div className="timelineTitleRow">
            <h2>{readableLiveLabel}</h2>
            {readableInlineDetail ? <span>{readableLiveDetail}</span> : null}
          </div>
        </div>
        <strong>{formatLatency(readableElapsed)}</strong>
      </div>
      {!readableInlineDetail ? <p>{readableLiveDetail}</p> : null}
      {releaseNotice ? <p className="releaseNotice">{releaseNotice}</p> : null}
      <div className="timelineSteps">
        {(readableTimingRows.length ? readableTimingRows : [["等待", undefined]]).map(([label, value]) => (
          <span key={label as string}>
            <small>{label}</small>
            <strong>{formatLatency(value as number | undefined)}</strong>
          </span>
        ))}
      </div>
    </section>
  );
}

export function ThinkingBudgetProgress({
  diagnostics,
  events,
  status,
  effort,
  receiving,
  complete
}: {
  diagnostics?: ChatDiagnostics | null;
  events: HiddenThinkingEvent[];
  status: StatusResponse | null | undefined;
  effort: ThinkingEffort;
  receiving?: boolean;
  complete?: boolean;
}) {
  const budget = displayThinkingBudget(status, effort);
  const used = diagnostics?.thinking_tokens_observed ?? estimateThinkingTokens(hiddenThinkingText(events));
  const rawPercent = budget > 0 ? (used / budget) * 100 : 0;
  const percent = complete
    ? 100
    : receiving
      ? Math.min(99, Math.max(0, Math.floor(rawPercent)))
      : Math.min(100, Math.max(0, Math.round(rawPercent)));
  const label = receiving ? "思考进度" : "本轮思考";

  return (
    <div className={`thinkingBudgetProgress ${receiving ? "active" : ""}`}>
      <div className="thinkingBudgetProgressHeader">
        <span>{label}</span>
        <small>{percent}%</small>
      </div>
      <div
        className="thinkingBudgetTrack"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={percent}
      >
        <i style={{ width: `${percent}%` }} />
      </div>
    </div>
  );
}

export function HiddenThinkingPanel({
  events,
  receiving
}: {
  events: HiddenThinkingEvent[];
  receiving?: boolean;
}) {
  const nonEmptyEvents = events.filter((event) => event.content.trim());
  const detailsRef = useRef<HTMLDetailsElement | null>(null);
  const preRefs = useRef<Record<string, HTMLPreElement | null>>({});
  const eventLengthSignature = nonEmptyEvents
    .map((event) => `${event.event_id}:${event.content.length}`)
    .join("|");

  function scrollLatestThinkingToBottom(behavior: ScrollBehavior = "auto") {
    const latest = nonEmptyEvents[nonEmptyEvents.length - 1];
    if (!latest) return;
    const pre = preRefs.current[latest.event_id];
    if (!pre) return;
    pre.scrollTo({ top: pre.scrollHeight, behavior });
  }

  useEffect(() => {
    if (!detailsRef.current?.open) return;
    window.requestAnimationFrame(() => scrollLatestThinkingToBottom("auto"));
  }, [eventLengthSignature, receiving]);

  if (!nonEmptyEvents.length) return null;
  const totalChars = nonEmptyEvents.reduce((total, event) => total + event.content.length, 0);
  return (
    <details
      ref={detailsRef}
      className="hiddenThinkingPanel"
      onToggle={() => {
        if (detailsRef.current?.open) {
          window.requestAnimationFrame(() => scrollLatestThinkingToBottom("auto"));
        }
      }}
    >
      <summary>
        <span>
          <Eye size={14} />
          开发者诊断
        </span>
        <small>
          {receiving ? "接收中 · " : ""}
          {nonEmptyEvents.length} 段 / {totalChars} 字符
        </small>
      </summary>
      {receiving ? (
        <p className="hiddenThinkingLiveHint">模型仍在运行；hidden-thinking 与管理员可见草稿缓冲会继续更新。</p>
      ) : null}
      <div className="hiddenThinkingList">
        {nonEmptyEvents.map((event) => (
          <section key={event.event_id} className="hiddenThinkingEvent">
            <header>
              <strong>{event.phase}</strong>
              <span>{event.model}</span>
              <small>
                {event.source} / {formatLatency(event.elapsed_ms)}
              </small>
            </header>
            <pre
              ref={(node) => {
                preRefs.current[event.event_id] = node;
              }}
            >
              {event.content}
            </pre>
          </section>
        ))}
      </div>
    </details>
  );
}
