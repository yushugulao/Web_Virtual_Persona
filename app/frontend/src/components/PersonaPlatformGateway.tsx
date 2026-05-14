import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, BadgeCheck, Plus, Search, Sparkles } from "lucide-react";

import {
  fetchMyUserPersonas,
  fetchRecommendedPublicPersonas,
  publishUserPersona,
  searchPersonaCatalog,
  unpublishUserPersona
} from "../api";
import { personaRuntimeStatusLabel, shortPersonaDescription } from "../frontendText";
import type { AuthUser, PersonaCatalogCard, PersonaProfile, UserPersonaDetail } from "../types";
import type { UiThemeId } from "../themes";
import { ThemeArtifacts } from "./ThemeArtifacts";
import { CreateUserPersonaDialog } from "./CreateUserPersonaDialog";

type PlatformView = "home" | "public" | "mine";

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
    is_owner: false
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
    is_owner: persona.is_owner
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
    suggested_questions: ["你最想让我从哪里开始讲？", "你通常会怎样回答这个问题？", "给我一个简洁的建议。"]
  };
}

function PersonaCardAvatar({ card }: { card: PersonaCatalogCard }) {
  if (card.avatar_url) {
    return <img src={card.avatar_url} alt="" />;
  }
  return <span>{card.avatar_label}</span>;
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
        <small>{card.kind === "user" ? `分数 ${card.score}` : "系统默认分身"}</small>
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
  const card = cardFromUserPersonaDetail(persona);

  async function togglePublish() {
    setBusy(true);
    try {
      if (persona.is_public) {
        await unpublishUserPersona(persona.id);
      } else {
        await publishUserPersona(persona.id);
      }
      await onUpdated();
    } finally {
      setBusy(false);
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
        <div className="personaDetailActions">
          <button type="button" className="ghostButton" onClick={onClose}>
            关闭
          </button>
          <button type="button" className="ghostButton" disabled={busy} onClick={() => void togglePublish()}>
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

  const searchQueryResult = useQuery({
    queryKey: ["persona-catalog-search", searchQuery],
    queryFn: () => searchPersonaCatalog(searchQuery),
    enabled: view === "public" && Boolean(searchQuery.trim()),
    staleTime: 30_000
  });

  const recommendedQuery = useQuery({
    queryKey: ["persona-catalog-recommended"],
    queryFn: () => fetchRecommendedPublicPersonas(5),
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
      setNotice("这个分身还在构建中，暂时不能进入对话。");
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
              await mineQuery.refetch();
              setDetailPersona(null);
            }}
          />
        ) : null}
        {createDialogOpen ? (
          <CreateUserPersonaDialog onClose={() => setCreateDialogOpen(false)} onCreated={() => void mineQuery.refetch()} />
        ) : null}
      </main>
    );
  }

  const searchResults = searchQueryResult.data?.results ?? [];
  const recommendations = recommendedQuery.data?.results ?? [];
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
      {searchQuery ? (
        <section className="catalogSection">
          <h2>搜索结果</h2>
          <div className="catalogGrid">
            {searchResults.map((card) => (
              <PersonaCatalogCardView key={card.id} card={card} onEnter={enterCard} />
            ))}
          </div>
          {!searchQueryResult.isLoading && !searchResults.length ? <p className="sessionEmpty">没有找到匹配分身。</p> : null}
        </section>
      ) : null}
      <section className="catalogSection">
        <h2>系统默认虚拟分身</h2>
        <div className="catalogGrid">
          {(loading ? [] : systemCards).map((card) => (
            <PersonaCatalogCardView key={card.id} card={card} onEnter={enterCard} />
          ))}
        </div>
      </section>
      <section className="catalogSection">
        <h2>其他用户公开的虚拟分身</h2>
        <div className="catalogGrid">
          {recommendations.map((card) => (
            <PersonaCatalogCardView key={card.id} card={card} onEnter={enterCard} />
          ))}
        </div>
        {!recommendations.length ? (
          <p className="sessionEmpty">暂时还没有可推荐的公开分身。等其他用户发布 ready 分身后，这里会随机展示五个。</p>
        ) : null}
      </section>
    </main>
  );
}
