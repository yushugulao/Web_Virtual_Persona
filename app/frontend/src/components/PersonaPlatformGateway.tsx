import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Plus, RefreshCw, Search, Sparkles } from "lucide-react";

import {
  fetchUserPersonaBuild,
  fetchMyUserPersonas,
  fetchPublicUserPersonas,
  publishUserPersona,
  rebuildUserPersona,
  startUserPersonaBuild,
  unpublishUserPersona
} from "../api";
import { personaRuntimeStatusLabel, shortPersonaDescription } from "../frontendText";
import type { AuthUser, PersonaCatalogCard, PersonaProfile, UserPersonaDetail } from "../types";
import type { UiThemeId } from "../themes";
import { ThemeArtifacts } from "./ThemeArtifacts";
import { CreateUserPersonaDialog } from "./CreateUserPersonaDialog";

type PlatformView = "home" | "public" | "mine";
type PublicCatalogSort = "published_at" | "score";
const PUBLIC_PAGE_SIZE = 24;

type PersonaPlatformGatewayProps = {
  systemPersonas: PersonaProfile[];
  loading: boolean;
  offline: boolean;
  currentUser: AuthUser;
  initialView?: PlatformView;
  onNavigate?: (view: PlatformView) => void;
  onEnter: (persona: PersonaProfile) => void;
  onLogout: () => void;
  onAdminUsers: () => void;
  theme: UiThemeId;
};

function cardFromPersonaProfile(persona: PersonaProfile): PersonaCatalogCard {
  return {
    id: persona.id,
    name: persona.name,
    avatar_url: persona.avatar_url ?? null,
    avatar_label: persona.avatar_label,
    identity_tags: persona.identity_tags?.length ? persona.identity_tags : persona.subtitle.split(/[、，,]/).slice(0, 4),
    short_description: persona.subtitle || shortPersonaDescription(persona.description, "系统公开虚拟分身"),
    kind: "system",
    runtime_status: "ready",
    score: 0,
    is_owner: false,
    is_public: true,
    published_at: null
  };
}

function cardFromUserPersonaDetail(persona: UserPersonaDetail): PersonaCatalogCard {
  return {
    id: persona.id,
    name: persona.name,
    avatar_url: persona.avatar_url,
    avatar_label: persona.avatar_label,
    identity_tags: persona.identity_tags,
    short_description: persona.short_description,
    kind: persona.kind,
    runtime_status: persona.runtime_status,
    score: persona.score,
    is_owner: persona.is_owner,
    is_public: persona.is_public,
    published_at: persona.published_at
  };
}

function profileFromPersonaCard(card: PersonaCatalogCard): PersonaProfile {
  return {
    id: card.id,
    name: card.name,
    subtitle: card.identity_tags.length ? card.identity_tags.join("、") : card.short_description,
    description: card.short_description || "用户创建的虚拟分身。",
    avatar_label: card.avatar_label,
    avatar_url: card.avatar_url,
    identity_tags: card.identity_tags,
    source_note: card.kind === "system" ? "系统内置公开档案。" : "用户公开或自有分身。",
    boundary_note:
      card.runtime_status === "ready" ? "该分身已准备好进入对话。" : "该分身尚未准备好进入对话。",
    corpus_paths: [],
    retrieval_prefixes: [],
    raw_source_paths: [],
    source_urls: [],
    suggested_questions: ["你最想让我从哪里开始讲？", "你通常会怎样回答这个问题？", "给我一个简洁的建议。"],
    kind: card.kind,
    is_owner: card.is_owner,
    is_public: card.is_public,
    published_at: card.published_at
  };
}

function PersonaCardAvatar({ card }: { card: PersonaCatalogCard }) {
  if (card.avatar_url) {
    return <img src={card.avatar_url} alt="" />;
  }
  return <span>{card.avatar_label}</span>;
}

function formatPublishedAt(value?: number | null) {
  if (!value) return "未公开";
  return new Date(value * 1000).toLocaleDateString("zh-CN", {
    month: "2-digit",
    day: "2-digit"
  });
}

function catalogCardMeta(card: PersonaCatalogCard) {
  if (card.kind === "system") return "系统默认分身";
  const visibility = card.is_public ? "已公开" : "私有";
  const score = `分数 ${card.score}`;
  const published = card.is_public && card.published_at ? `公开于 ${formatPublishedAt(card.published_at)}` : "";
  return [visibility, score, published || personaRuntimeStatusLabel(card.runtime_status)].filter(Boolean).join(" · ");
}

function cardMatchesQuery(card: PersonaCatalogCard, query: string) {
  const normalized = query.trim().toLowerCase();
  if (!normalized) return true;
  const haystack = [
    card.name,
    card.short_description,
    card.runtime_status,
    card.kind,
    ...card.identity_tags
  ].join(" ").toLowerCase();
  return haystack.includes(normalized);
}

function PersonaCatalogCardView({
  card,
  onEnter,
  onDetail
}: {
  card: PersonaCatalogCard;
  onEnter: (card: PersonaCatalogCard) => void;
  onDetail?: (card: PersonaCatalogCard) => void;
}) {
  const canEnter = card.runtime_status === "ready";
  return (
    <article
      className={`catalogPersonaCard ${card.kind} ${card.runtime_status}`}
      onClick={onDetail ? () => onDetail(card) : undefined}
    >
      <div className="catalogPersonaAvatar">
        <PersonaCardAvatar card={card} />
      </div>
      <div className="catalogPersonaBody">
        <h3>{card.name}</h3>
        <div className="personaTagRow">
          {card.identity_tags.slice(0, 4).map((tag) => (
            <span key={tag}>{tag}</span>
          ))}
        </div>
        <p>{card.short_description}</p>
        <small>{catalogCardMeta(card)}</small>
      </div>
      <div className="catalogPersonaActions">
        {onDetail ? (
          <button
            type="button"
            className="ghostButton"
            onClick={(event) => {
              event.stopPropagation();
              onDetail(card);
            }}
          >
            详情
          </button>
        ) : null}
        <button
          type="button"
          className="primaryAction"
          disabled={!canEnter}
          onClick={(event) => {
            event.stopPropagation();
            onEnter(card);
          }}
        >
          <ArrowRight size={15} />
          进入对话
        </button>
      </div>
    </article>
  );
}

function UserPersonaDetailDialog({
  persona,
  onClose,
  onEnter,
  onUpdated
}: {
  persona: UserPersonaDetail;
  onClose: () => void;
  onEnter: (persona: PersonaCatalogCard) => void;
  onUpdated: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [buildBusy, setBuildBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const card = cardFromUserPersonaDetail(persona);
  const buildActionLabel =
    persona.runtime_status === "error" || persona.runtime_status === "ready" ? "重新生成" : "生成分身";
  const buildDisabled = buildBusy || busy || persona.runtime_status === "building";

  async function togglePublish() {
    setBusy(true);
    setNotice("");
    try {
      if (persona.is_public) {
        await unpublishUserPersona(persona.id);
      } else {
        await publishUserPersona(persona.id);
      }
      await onUpdated();
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "公开状态更新失败。");
    } finally {
      setBusy(false);
    }
  }

  async function runBuild() {
    setBuildBusy(true);
    setNotice("");
    try {
      const started =
        persona.runtime_status === "draft" ? await startUserPersonaBuild(persona.id) : await rebuildUserPersona(persona.id);
      setNotice(`已开始生成：${started.phase || "整理资料"}。生成完成后即可公开和进入对话。`);
      await onUpdated();
      await pollBuildUntilSettled(persona.id, async (message) => {
        setNotice(message);
        await onUpdated();
      });
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "启动生成失败。");
    } finally {
      setBuildBusy(false);
    }
  }

  return (
    <div className="personaDetailOverlay" role="presentation" onMouseDown={onClose}>
      <section
        className="personaDetailModal surfaceTransition"
        role="dialog"
        aria-modal="true"
        aria-label={`${persona.name} 详情`}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="personaDetailHero">
          <div className="catalogPersonaAvatar large">
            <PersonaCardAvatar card={card} />
          </div>
          <div>
            <p className="eyebrow">{persona.is_public ? "公开分身" : "私有分身"}</p>
            <h2>{persona.name}</h2>
            <div className="personaTagRow">
              {persona.identity_tags.map((tag) => (
                <span key={tag}>{tag}</span>
              ))}
            </div>
          </div>
        </div>
        <p>{persona.description || persona.short_description}</p>
        <div className="traceLine">
          <span>状态</span>
          <strong>{personaRuntimeStatusLabel(persona.runtime_status)}</strong>
        </div>
        <div className="traceLine">
          <span>公开状态</span>
          <strong>{persona.is_public ? "已公开" : "私有"}</strong>
        </div>
        {persona.is_public && persona.published_at ? (
          <div className="traceLine">
            <span>公开时间</span>
            <strong>{formatPublishedAt(persona.published_at)}</strong>
          </div>
        ) : null}
        {notice ? <p className="sessionNotice">{notice}</p> : null}
        <div className="personaDetailActions">
          <button type="button" className="ghostButton" onClick={onClose}>
            关闭
          </button>
          <button
            type="button"
            className="ghostButton"
            disabled={buildDisabled}
            onClick={() => void runBuild()}
            title={persona.runtime_status === "building" ? "正在生成，请稍候" : undefined}
          >
            {buildBusy || persona.runtime_status === "building" ? <RefreshCw size={15} className="spinIcon" /> : null}
            {persona.runtime_status === "building" ? "正在生成" : buildActionLabel}
          </button>
          <button
            type="button"
            className="ghostButton"
            disabled={busy || (!persona.is_public && persona.runtime_status !== "ready")}
            onClick={() => void togglePublish()}
            title={persona.runtime_status !== "ready" && !persona.is_public ? "请先生成完成后再公开" : undefined}
          >
            {persona.is_public ? "取消公开" : "公开分身"}
          </button>
          <button
            type="button"
            className="primaryAction"
            disabled={persona.runtime_status !== "ready"}
            onClick={() => onEnter(card)}
          >
            进入会话
          </button>
        </div>
      </section>
    </div>
  );
}

export function PersonaPlatformGateway({
  systemPersonas,
  loading,
  offline,
  currentUser,
  initialView = "home",
  onNavigate,
  onEnter,
  onLogout,
  onAdminUsers,
  theme
}: PersonaPlatformGatewayProps) {
  const [view, setView] = useState<PlatformView>(initialView);
  const [searchText, setSearchText] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [publicSort, setPublicSort] = useState<PublicCatalogSort>("published_at");
  const [publicLimit, setPublicLimit] = useState(PUBLIC_PAGE_SIZE);
  const [detailPersona, setDetailPersona] = useState<UserPersonaDetail | null>(null);
  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [notice, setNotice] = useState("");

  const systemCards = useMemo(() => systemPersonas.map(cardFromPersonaProfile), [systemPersonas]);

  useEffect(() => {
    setView(initialView);
  }, [initialView]);

  function goToView(nextView: PlatformView) {
    setView(nextView);
    onNavigate?.(nextView);
  }

  useEffect(() => {
    setPublicLimit(PUBLIC_PAGE_SIZE);
  }, [publicSort, searchQuery]);

  const publicQuery = useQuery({
    queryKey: ["persona-catalog-public", searchQuery, publicSort, publicLimit],
    queryFn: () =>
      fetchPublicUserPersonas({
        query: searchQuery,
        limit: publicLimit,
        offset: 0,
        sort: publicSort
      }),
    enabled: view === "public",
    staleTime: 30_000
  });

  const mineQuery = useQuery({
    queryKey: ["user-personas-mine"],
    queryFn: fetchMyUserPersonas,
    enabled: view === "mine",
    staleTime: 20_000
  });

  function enterCard(card: PersonaCatalogCard) {
    if (card.runtime_status !== "ready") {
      setNotice(enterBlockedMessage(card.runtime_status));
      return;
    }
    onEnter(profileFromPersonaCard(card));
  }

  const headerActions = (
    <div className="platformHeaderActions">
      {currentUser.role === "admin" ? (
        <button type="button" className="pillButton subtle" onClick={onAdminUsers}>
          用户管理
        </button>
      ) : null}
      <button type="button" className="dangerTextButton" onClick={onLogout}>
        退出登录
      </button>
    </div>
  );

  if (view === "home") {
    return (
      <main className={`personaGateway personaPlatformGateway personaPlatformHome surfaceTransition theme-${theme}`}>
        <ThemeArtifacts theme={theme} />
        <section className="platformHero">
          <div>
            <p className="eyebrow">Web虚拟分身</p>
            <h1>选择你要进入的分身世界</h1>
            <p>和公开分身交谈，或管理你自己创建的虚拟分身。</p>
          </div>
          {headerActions}
        </section>
        <section className="platformEntryGrid">
          <button type="button" className="platformEntryCard" onClick={() => goToView("public")}>
            <Search size={30} />
            <strong>与公开的虚拟分身交谈</strong>
            <span>搜索系统默认分身和其他用户公开的分身。</span>
          </button>
          <button type="button" className="platformEntryCard" onClick={() => goToView("mine")}>
            <Sparkles size={30} />
            <strong>我创建的虚拟分身</strong>
            <span>上传资料，构建并管理自己的虚拟分身。</span>
          </button>
        </section>
      </main>
    );
  }

  if (view === "mine") {
    const myPersonas = mineQuery.data?.personas ?? [];
    return (
      <main className={`personaGateway personaPlatformGateway personaPlatformMine surfaceTransition theme-${theme}`}>
        <ThemeArtifacts theme={theme} />
        <header className="catalogHeader">
          <button type="button" className="ghostButton" onClick={() => goToView("home")}>
            返回
          </button>
          <div>
            <p className="eyebrow">我的分身</p>
            <h1>我创建的虚拟分身</h1>
          </div>
          {headerActions}
        </header>
        {notice ? <p className="sessionNotice">{notice}</p> : null}
        <section className={`myPersonaGrid ${myPersonas.length ? "" : "empty"}`}>
          {myPersonas.map((persona) => (
            <PersonaCatalogCardView
              key={persona.id}
              card={cardFromUserPersonaDetail(persona)}
              onEnter={enterCard}
              onDetail={() => setDetailPersona(persona)}
            />
          ))}
          <button type="button" className="createPersonaCard" onClick={() => setCreateDialogOpen(true)}>
            <Plus size={34} />
            <strong>试着创建自己的虚拟分身！</strong>
            <span>上传资料，先生成可追溯的解析结果。</span>
          </button>
        </section>
        {detailPersona ? (
          <UserPersonaDetailDialog
            persona={detailPersona}
            onClose={() => setDetailPersona(null)}
            onEnter={enterCard}
            onUpdated={async () => {
              const refreshedMine = await mineQuery.refetch();
              await publicQuery.refetch();
              const updated = refreshedMine.data?.personas.find((item) => item.id === detailPersona.id);
              if (updated) {
                setDetailPersona(updated);
              }
            }}
          />
        ) : null}
        {createDialogOpen ? (
          <CreateUserPersonaDialog onClose={() => setCreateDialogOpen(false)} onCreated={() => void mineQuery.refetch()} />
        ) : null}
      </main>
    );
  }

  const publicCards = publicQuery.data?.results ?? [];
  const publicTotal = publicQuery.data?.total ?? 0;
  const canLoadMorePublic = publicCards.length < publicTotal;
  const filteredSystemCards = searchQuery
    ? systemCards.filter((card) => cardMatchesQuery(card, searchQuery))
    : systemCards;
  return (
    <main className={`personaGateway personaPlatformGateway personaPlatformPublic surfaceTransition theme-${theme}`}>
      <ThemeArtifacts theme={theme} />
      <header className="catalogHeader">
        <button type="button" className="ghostButton" onClick={() => goToView("home")}>
          返回
        </button>
        <div>
          <p className="eyebrow">公开分身</p>
          <h1>与公开的虚拟分身交谈</h1>
        </div>
        {headerActions}
      </header>
      {offline ? <p className="authError">后端暂不可用，正在使用本地兜底分身。</p> : null}
      <form
        className="personaSearchForm"
        onSubmit={(event) => {
          event.preventDefault();
          setSearchQuery(searchText.trim());
        }}
      >
        <Search size={22} />
        <input
          value={searchText}
          onChange={(event) => setSearchText(event.target.value)}
          placeholder="搜索虚拟分身、职业、风格或主题"
        />
        <button type="submit" className="primaryAction">
          搜索
        </button>
      </form>
      <div className="catalogToolbar" aria-label="公开分身排序">
        <span>
          {searchQuery ? `搜索：${searchQuery}` : "全部社区公开分身"}
          {publicTotal ? ` · ${publicTotal} 个` : ""}
        </span>
        <div className="segmentedControl">
          <button
            type="button"
            className={publicSort === "published_at" ? "active" : ""}
            onClick={() => setPublicSort("published_at")}
          >
            最新公开
          </button>
          <button
            type="button"
            className={publicSort === "score" ? "active" : ""}
            onClick={() => setPublicSort("score")}
          >
            分数优先
          </button>
        </div>
      </div>
      <section className="catalogSection">
        <h2>系统默认虚拟分身</h2>
        <div className="catalogGrid">
          {(loading ? [] : filteredSystemCards).map((card) => (
            <PersonaCatalogCardView key={card.id} card={card} onEnter={enterCard} />
          ))}
        </div>
        {searchQuery && !filteredSystemCards.length ? <p className="sessionEmpty">系统默认分身里没有匹配项。</p> : null}
      </section>
      <section className="catalogSection">
        <h2>社区公开分身</h2>
        <div className="catalogGrid">
          {publicCards.map((card) => (
            <PersonaCatalogCardView key={card.id} card={card} onEnter={enterCard} />
          ))}
        </div>
        {!publicQuery.isLoading && !publicCards.length ? (
          <p className="sessionEmpty">
            {searchQuery ? "没有找到匹配的社区公开分身。" : "暂时还没有社区公开分身。ready 分身公开后会出现在这里。"}
          </p>
        ) : null}
        {canLoadMorePublic ? (
          <button
            type="button"
            className="ghostButton catalogLoadMore"
            onClick={() => setPublicLimit((current) => current + PUBLIC_PAGE_SIZE)}
          >
            加载更多
          </button>
        ) : null}
      </section>
    </main>
  );
}

function enterBlockedMessage(status: PersonaCatalogCard["runtime_status"]) {
  if (status === "draft") return "这个分身还是草稿，请先打开详情并生成分身。";
  if (status === "building") return "这个分身正在生成，完成后才能进入对话。";
  if (status === "error") return "这个分身上次生成失败，请先打开详情并重新生成。";
  return "这个分身暂时不能进入对话。";
}

async function pollBuildUntilSettled(
  personaId: string,
  onTick: (message: string) => Promise<void>
) {
  const deadline = Date.now() + 180_000;
  while (Date.now() < deadline) {
    await wait(1800);
    const build = await fetchUserPersonaBuild(personaId);
    if (build.status === "succeeded") {
      await onTick("生成完成，现在可以公开分身或进入对话。");
      return;
    }
    if (build.status === "failed") {
      await onTick(build.error ? `生成失败：${build.error}` : "生成失败，请检查资料和模型配置。");
      return;
    }
    await onTick(`正在生成：${build.phase || "处理中"} ${Math.round(build.progress * 100)}%`);
  }
  await onTick("生成仍在继续，请稍后刷新查看状态。");
}

function wait(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}
