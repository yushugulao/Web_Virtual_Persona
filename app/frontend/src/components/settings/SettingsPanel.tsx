import { CircleSlash, RefreshCw, RotateCcw, Trash2 } from "lucide-react";
import { UI_THEMES, type UiThemeId } from "../../themes";
import type { ChatSessionSummary } from "../../types";

type SettingsPanelProps = {
  open: boolean;
  theme: UiThemeId;
  archivedSessions: ChatSessionSummary[];
  archivedLoading: boolean;
  onClose: () => void;
  onThemeChange: (theme: UiThemeId) => void;
  onRefreshArchived: () => void;
  onRestoreArchived: (session: ChatSessionSummary) => void;
  onDeleteArchived: (session: ChatSessionSummary) => void;
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

export function SettingsPanel({
  open,
  theme,
  archivedSessions,
  archivedLoading,
  onClose,
  onThemeChange,
  onRefreshArchived,
  onRestoreArchived,
  onDeleteArchived
}: SettingsPanelProps) {
  if (!open) return null;

  return (
    <div className="settingsOverlay" role="presentation" onMouseDown={onClose}>
      <section
        className="settingsPanel surfaceTransition"
        role="dialog"
        aria-modal="true"
        aria-label="设置"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header className="settingsHeader">
          <div>
            <p className="eyebrow">偏好</p>
            <h2>设置</h2>
          </div>
          <button type="button" className="iconButton" onClick={onClose}>
            <CircleSlash size={16} />
          </button>
        </header>
        <section className="settingsSection">
          <div>
            <p className="eyebrow">主题</p>
            <h3>页面风格</h3>
          </div>
          <div className="themeOptionGrid">
            {UI_THEMES.map((themeOption) => (
              <button
                key={themeOption.id}
                type="button"
                className={`themeOption ${theme === themeOption.id ? "active" : ""}`}
                onClick={() => onThemeChange(themeOption.id)}
              >
                <span>{themeOption.name}</span>
                <small>{themeOption.description}</small>
                <i className="themeSwatches" aria-hidden="true">
                  {themeOption.colors.map((color) => (
                    <b key={color} style={{ background: color }} />
                  ))}
                </i>
              </button>
            ))}
          </div>
        </section>
        <section className="settingsSection archivedSessionsPanel">
          <div className="settingsSectionHeader">
            <div>
              <p className="eyebrow">会话</p>
              <h3>已归档会话</h3>
            </div>
            <button type="button" className="ghostButton" onClick={onRefreshArchived}>
              <RefreshCw size={14} />
              刷新
            </button>
          </div>
          <div className="archivedSessionList">
            {archivedSessions.map((session) => (
              <article key={session.session_id} className="archivedSessionItem">
                <div>
                  <strong>{session.title || "未命名会话"}</strong>
                  <span>{session.persona_name ?? session.persona_id}</span>
                  <small>
                    创建 {formatRunTime(session.created_at)} · 归档{" "}
                    {session.archived_at ? formatRunTime(session.archived_at) : "未知"} ·{" "}
                    {session.message_count} 条
                  </small>
                </div>
                <div className="archivedSessionActions">
                  <button type="button" onClick={() => onRestoreArchived(session)}>
                    <RotateCcw size={14} />
                    恢复
                  </button>
                  <button
                    type="button"
                    className="danger"
                    onClick={() => onDeleteArchived(session)}
                  >
                    <Trash2 size={14} />
                    永久删除
                  </button>
                </div>
              </article>
            ))}
            {!archivedSessions.length ? (
              <p className="settingsEmpty">
                {archivedLoading ? "正在读取归档会话..." : "目前没有归档会话。"}
              </p>
            ) : null}
          </div>
        </section>
      </section>
    </div>
  );
}
