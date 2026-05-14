import { Archive, MessageSquareText, PanelLeftClose, PanelLeftOpen } from "lucide-react";
import type { ChatSessionSummary } from "../../types";

type SessionDrawerProps = {
  open: boolean;
  sessions: ChatSessionSummary[];
  currentSessionId: string;
  sort: "recent" | "persona";
  notice: string;
  onToggle: () => void;
  onClose: () => void;
  onSortChange: (sort: "recent" | "persona") => void;
  onNewConversation: () => void;
  onOpenSession: (session: ChatSessionSummary) => void;
  onArchiveSession: (session: ChatSessionSummary) => void;
};

function formatRunTime(ts: number | undefined) {
  if (!ts) return "暂无";
  const millis = ts > 10_000_000_000 ? ts : ts * 1000;
  return new Date(millis).toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit"
  });
}

export function SessionDrawer({
  open,
  sessions,
  currentSessionId,
  sort,
  notice,
  onToggle,
  onClose,
  onSortChange,
  onNewConversation,
  onOpenSession,
  onArchiveSession
}: SessionDrawerProps) {
  return (
    <>
      <button
        className={`sessionDrawerToggle ${open ? "open" : ""}`}
        type="button"
        onClick={onToggle}
        aria-expanded={open}
      >
        {open ? <PanelLeftClose size={15} /> : <PanelLeftOpen size={15} />}
        对话
      </button>
      <aside className={`sessionDrawer ${open ? "open" : ""}`} aria-label="会话列表">
        <div className="sessionDrawerHeader">
          <div>
            <h2>对话列表</h2>
          </div>
          <button type="button" className="iconButton" onClick={onClose}>
            <PanelLeftClose size={16} />
          </button>
        </div>
        <div className="sessionDrawerControls">
          <button
            type="button"
            className={sort === "recent" ? "active" : ""}
            onClick={() => onSortChange("recent")}
          >
            最近
          </button>
          <button
            type="button"
            className={sort === "persona" ? "active" : ""}
            onClick={() => onSortChange("persona")}
          >
            人物
          </button>
          <button type="button" className="sessionNewButton" onClick={onNewConversation}>
            <MessageSquareText size={14} />
            新对话
          </button>
        </div>
        {notice ? <p className="sessionNotice">{notice}</p> : null}
        <div className="sessionList">
          {sessions.map((session) => (
            <article
              key={session.session_id}
              className={`sessionListItem ${session.session_id === currentSessionId ? "active" : ""}`}
            >
              <button type="button" className="sessionOpenButton" onClick={() => onOpenSession(session)}>
                <strong>{session.title || "未命名"}</strong>
                <span>{session.persona_name ?? session.persona_id}</span>
                <small>
                  {formatRunTime(session.created_at)} · {session.message_count} 条
                </small>
              </button>
              <button
                type="button"
                className="sessionArchiveButton"
                title="归档会话"
                onClick={() => onArchiveSession(session)}
              >
                <Archive size={13} />
                归档
              </button>
            </article>
          ))}
          {!sessions.length ? <p className="sessionEmpty">还没有对话。</p> : null}
        </div>
      </aside>
    </>
  );
}
