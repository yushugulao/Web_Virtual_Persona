import type {
  AdminUsersResponse,
  AuthChallengeProof,
  AuthChallengePurpose,
  AuthChallengeResponse,
  AuthUser,
  BrowserAcceptanceMatrixResponse,
  ChatResponse,
  ChatSessionMessagesResponse,
  ChatSessionSummary,
  EvidenceCardStats,
  EvalRunListItem,
  EvalRunResponse,
  HiddenThinkingDeltaEvent,
  LoginResponse,
  MemoryListResponse,
  MemoryStatsResponse,
  PersonaCatalogPublicResponse,
  PersonaCatalogRecommendedResponse,
  PersonaCatalogSearchResponse,
  PersonaMaterialsResponse,
  PersonaProfile,
  PersonaTurnFeedbackPayload,
  PersonaTurnFeedbackResponse,
  PersonaTurnFeedbackStatsResponse,
  StatusResponse,
  StreamStageEvent,
  ThemePreferenceResponse,
  ThinkingEffort,
  UserPersonaCommunicationImportResponse,
  UserPersonaDraftCreatePayload,
  UserPersonaEmailImportPayload,
  UserPersonaBuildArtifactsResponse,
  UserPersonaBuildStatusResponse,
  UserPersonaDetail,
  UserPersonaFileItem,
  UserPersonaFileListResponse,
  UserPersonaListResponse
} from "./types";

const API_BASE =
  import.meta.env.VITE_API_BASE_URL ?? (import.meta.env.DEV ? "http://127.0.0.1:8001" : "");

let authTokenProvider: (() => string | null) | null = () =>
  typeof window === "undefined" ? null : window.localStorage.getItem("persona_rag_auth_token");

export function setAuthTokenProvider(provider: () => string | null): void {
  authTokenProvider = provider;
}

function authHeaders(): HeadersInit {
  const token = authTokenProvider?.();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

function jsonHeaders(): HeadersInit {
  return { "Content-Type": "application/json", ...authHeaders() };
}

async function parseApiError(response: Response, fallback: string): Promise<Error> {
  try {
    const body = await response.json();
    if (typeof body?.detail === "string") {
      return new Error(body.detail);
    }
    if (Array.isArray(body?.detail)) {
      const validationMessages = body.detail
        .map((issue: unknown) => formatValidationIssue(issue))
        .filter((message: string | null): message is string => Boolean(message));
      if (validationMessages.length > 0) {
        return new Error(`${fallback}：${validationMessages.join("；")}`);
      }
    }
  } catch {
    // Use the fallback below when the backend returns a non-JSON error.
  }
  return new Error(`${fallback}：${response.status}`);
}

function formatValidationIssue(issue: unknown): string | null {
  if (!issue || typeof issue !== "object") return null;
  const record = issue as {
    loc?: unknown[];
    msg?: string;
    type?: string;
    ctx?: { min_length?: number; max_length?: number; ge?: number; le?: number };
  };
  const field = Array.isArray(record.loc) ? String(record.loc[record.loc.length - 1] ?? "") : "";
  const label = validationFieldLabels[field] ?? "输入内容";
  if (record.type === "missing") {
    return `请填写${label}`;
  }
  if (record.type === "string_too_short") {
    return `${label}至少 ${record.ctx?.min_length ?? ""} 个字符`.trim();
  }
  if (record.type === "string_too_long") {
    return `${label}最多 ${record.ctx?.max_length ?? ""} 个字符`.trim();
  }
  if (record.type === "literal_error") {
    return `${label}不是可用选项`;
  }
  if (record.type?.includes("bool")) {
    return `${label}必须是真或假`;
  }
  return record.msg ? `${label}：${record.msg}` : null;
}

const validationFieldLabels: Record<string, string> = {
  email: "邮箱",
  username: "用户名",
  password: "密码",
  role: "角色",
  status: "账号状态",
  email_verified: "邮箱激活状态",
  send_verification: "发送验证邮件选项",
  must_change_password: "改密要求"
};

async function sha256Hex(input: string): Promise<string> {
  if (!globalThis.crypto?.subtle) {
    throw new Error("当前浏览器不支持本地安全校验，请换用现代浏览器。");
  }
  const bytes = new TextEncoder().encode(input);
  const digest = await globalThis.crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest))
    .map((value) => value.toString(16).padStart(2, "0"))
    .join("");
}

function wait(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

export async function fetchAuthChallenge(purpose: AuthChallengePurpose): Promise<AuthChallengeResponse> {
  const params = new URLSearchParams({ purpose });
  const response = await fetch(`${API_BASE}/auth/challenge?${params.toString()}`);
  if (!response.ok) {
    throw await parseApiError(response, "人机校验初始化失败");
  }
  return response.json();
}

export async function solveAuthChallenge(purpose: AuthChallengePurpose): Promise<AuthChallengeProof> {
  const challenge = await fetchAuthChallenge(purpose);
  if (challenge.algorithm === "slider-puzzle-v1") {
    if (typeof challenge.slider_target_x !== "number") {
      throw new Error("滑块校验初始化失败，请刷新后重试。");
    }
    const startedAt = Date.now();
    const remaining = Math.max(0, challenge.min_elapsed_ms);
    if (remaining > 0) {
      await wait(remaining);
    }
    return {
      challenge_id: challenge.challenge_id,
      challenge_nonce: challenge.nonce,
      challenge_answer: challenge.slider_target_x,
      challenge_elapsed_ms: Date.now() - startedAt
    };
  }
  if (challenge.algorithm !== "sha256-prefix-zero") {
    throw new Error("未知的人机校验算法。");
  }
  const startedAt = Date.now();
  const prefix = "0".repeat(challenge.difficulty);
  let counter = 0;
  while (counter < Number.MAX_SAFE_INTEGER) {
    const digest = await sha256Hex(`${challenge.challenge_id}:${challenge.nonce}:${counter}`);
    if (digest.startsWith(prefix)) {
      const elapsed = Date.now() - startedAt;
      const remaining = Math.max(0, challenge.min_elapsed_ms - elapsed);
      if (remaining > 0) {
        await wait(remaining);
      }
      return {
        challenge_id: challenge.challenge_id,
        challenge_nonce: challenge.nonce,
        challenge_counter: counter,
        challenge_elapsed_ms: Date.now() - startedAt
      };
    }
    counter += 1;
    if (counter % 750 === 0) {
      await wait(0);
    }
  }
  throw new Error("人机校验计算失败，请刷新后重试。");
}

export async function fetchStatus(): Promise<StatusResponse> {
  const response = await fetch(`${API_BASE}/status`, { headers: authHeaders() });
  if (!response.ok) {
    throw await parseApiError(response, "状态请求失败");
  }
  return response.json();
}

export async function fetchPersonas(): Promise<PersonaProfile[]> {
  const response = await fetch(`${API_BASE}/personas`, { headers: authHeaders() });
  if (!response.ok) {
    throw await parseApiError(response, "交谈对象请求失败");
  }
  return response.json();
}

export async function fetchPersonaMaterials(personaId: string): Promise<PersonaMaterialsResponse> {
  const response = await fetch(`${API_BASE}/personas/${encodeURIComponent(personaId)}/materials`, {
    headers: authHeaders()
  });
  if (!response.ok) {
    throw await parseApiError(response, "对象档案请求失败");
  }
  return response.json();
}

export async function searchPersonaCatalog(query: string, limit = 24): Promise<PersonaCatalogSearchResponse> {
  const params = new URLSearchParams({ q: query, limit: String(limit) });
  const response = await fetch(`${API_BASE}/persona-catalog/search?${params.toString()}`, {
    headers: authHeaders()
  });
  if (!response.ok) {
    throw await parseApiError(response, "虚拟分身搜索失败");
  }
  return response.json();
}

export async function fetchRecommendedPublicPersonas(limit = 5): Promise<PersonaCatalogRecommendedResponse> {
  const params = new URLSearchParams({ limit: String(limit) });
  const response = await fetch(`${API_BASE}/persona-catalog/recommended?${params.toString()}`, {
    headers: authHeaders()
  });
  if (!response.ok) {
    throw await parseApiError(response, "公开分身推荐失败");
  }
  return response.json();
}

export async function fetchPublicUserPersonas(options: {
  query?: string;
  limit?: number;
  offset?: number;
  sort?: "published_at" | "score";
} = {}): Promise<PersonaCatalogPublicResponse> {
  const params = new URLSearchParams({
    q: options.query ?? "",
    limit: String(options.limit ?? 24),
    offset: String(options.offset ?? 0),
    sort: options.sort ?? "published_at"
  });
  const response = await fetch(`${API_BASE}/persona-catalog/public?${params.toString()}`, {
    headers: authHeaders()
  });
  if (!response.ok) {
    throw await parseApiError(response, "公开分身列表请求失败");
  }
  return response.json();
}

export async function fetchMyUserPersonas(): Promise<UserPersonaListResponse> {
  const response = await fetch(`${API_BASE}/user-personas/mine`, { headers: authHeaders() });
  if (!response.ok) {
    throw await parseApiError(response, "我的虚拟分身列表请求失败");
  }
  return response.json();
}

export async function createUserPersonaDraft(
  payload: UserPersonaDraftCreatePayload
): Promise<UserPersonaDetail> {
  const response = await fetch(`${API_BASE}/user-personas/drafts`, {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify(payload)
  });
  if (!response.ok) {
    throw await parseApiError(response, "创建虚拟分身草稿失败");
  }
  return response.json();
}

export async function fetchUserPersonaDetail(personaId: string): Promise<UserPersonaDetail> {
  const response = await fetch(`${API_BASE}/user-personas/${encodeURIComponent(personaId)}`, {
    headers: authHeaders()
  });
  if (!response.ok) {
    throw await parseApiError(response, "虚拟分身详情请求失败");
  }
  return response.json();
}

export async function publishUserPersona(personaId: string): Promise<UserPersonaDetail> {
  const response = await fetch(`${API_BASE}/user-personas/${encodeURIComponent(personaId)}/publish`, {
    method: "POST",
    headers: authHeaders()
  });
  if (!response.ok) {
    throw await parseApiError(response, "公开虚拟分身失败");
  }
  return response.json();
}

export async function unpublishUserPersona(personaId: string): Promise<UserPersonaDetail> {
  const response = await fetch(`${API_BASE}/user-personas/${encodeURIComponent(personaId)}/unpublish`, {
    method: "POST",
    headers: authHeaders()
  });
  if (!response.ok) {
    throw await parseApiError(response, "取消公开虚拟分身失败");
  }
  return response.json();
}

export async function fetchUserPersonaFiles(personaId: string): Promise<UserPersonaFileListResponse> {
  const response = await fetch(`${API_BASE}/user-personas/${encodeURIComponent(personaId)}/files`, {
    headers: authHeaders()
  });
  if (!response.ok) {
    throw await parseApiError(response, "读取分身上传文件失败");
  }
  return response.json();
}

export function uploadUserPersonaFile(
  personaId: string,
  file: File,
  onProgress?: (progress: { loaded: number; total: number; speedKbps: number }) => void,
  signal?: AbortSignal
): Promise<UserPersonaFileItem> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    const formData = new FormData();
    const startedAt = performance.now();
    let settled = false;
    const cleanup = () => {
      signal?.removeEventListener("abort", abortUpload);
    };
    const settleReject = (error: Error) => {
      if (settled) return;
      settled = true;
      cleanup();
      reject(error);
    };
    const settleResolve = (value: UserPersonaFileItem) => {
      if (settled) return;
      settled = true;
      cleanup();
      resolve(value);
    };
    const abortUpload = () => xhr.abort();
    formData.append("file", file);
    xhr.open("POST", `${API_BASE}/user-personas/${encodeURIComponent(personaId)}/files`);
    const token = authTokenProvider?.();
    if (token) {
      xhr.setRequestHeader("Authorization", `Bearer ${token}`);
    }
    xhr.upload.onprogress = (event) => {
      if (!event.lengthComputable) return;
      const elapsedSeconds = Math.max(0.001, (performance.now() - startedAt) / 1000);
      onProgress?.({
        loaded: event.loaded,
        total: event.total,
        speedKbps: event.loaded / 1024 / elapsedSeconds
      });
    };
    xhr.onerror = () => settleReject(new Error("上传文件失败"));
    xhr.onabort = () => settleReject(new Error("上传已中止"));
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          settleResolve(JSON.parse(xhr.responseText));
        } catch {
          settleReject(new Error("上传响应解析失败"));
        }
        return;
      }
      try {
        const body = JSON.parse(xhr.responseText);
        settleReject(new Error(typeof body?.detail === "string" ? body.detail : `上传文件失败：${xhr.status}`));
      } catch {
        settleReject(new Error(`上传文件失败：${xhr.status}`));
      }
    };
    if (signal?.aborted) {
      abortUpload();
      return;
    }
    signal?.addEventListener("abort", abortUpload, { once: true });
    xhr.send(formData);
  });
}

export async function deleteUserPersonaFile(personaId: string, fileId: string): Promise<{ message: string }> {
  const response = await fetch(
    `${API_BASE}/user-personas/${encodeURIComponent(personaId)}/files/${encodeURIComponent(fileId)}`,
    {
      method: "DELETE",
      headers: authHeaders()
    }
  );
  if (!response.ok) {
    throw await parseApiError(response, "删除上传文件失败");
  }
  return response.json();
}

export async function importUserPersonaEmailSource(
  personaId: string,
  payload: UserPersonaEmailImportPayload
): Promise<UserPersonaCommunicationImportResponse> {
  const response = await fetch(`${API_BASE}/user-personas/${encodeURIComponent(personaId)}/email/import`, {
    method: "POST",
    headers: { ...authHeaders(), "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  if (!response.ok) {
    throw await parseApiError(response, "导入邮箱来源失败");
  }
  return response.json();
}

export async function importUserPersonaQqSource(
  personaId: string,
  files: File[]
): Promise<UserPersonaCommunicationImportResponse> {
  const formData = new FormData();
  for (const file of files) {
    formData.append("files", file);
  }
  const response = await fetch(`${API_BASE}/user-personas/${encodeURIComponent(personaId)}/qq/import`, {
    method: "POST",
    headers: authHeaders(),
    body: formData
  });
  if (!response.ok) {
    throw await parseApiError(response, "导入 QQ 聊天记录失败");
  }
  return response.json();
}

export async function startUserPersonaBuild(personaId: string): Promise<UserPersonaBuildStatusResponse> {
  const response = await fetch(`${API_BASE}/user-personas/${encodeURIComponent(personaId)}/build`, {
    method: "POST",
    headers: authHeaders()
  });
  if (!response.ok) {
    throw await parseApiError(response, "启动虚拟分身生成失败");
  }
  return response.json();
}

export async function rebuildUserPersona(personaId: string): Promise<UserPersonaBuildStatusResponse> {
  const response = await fetch(`${API_BASE}/user-personas/${encodeURIComponent(personaId)}/rebuild`, {
    method: "POST",
    headers: authHeaders()
  });
  if (!response.ok) {
    throw await parseApiError(response, "重新生成虚拟分身失败");
  }
  return response.json();
}

export async function fetchUserPersonaBuild(personaId: string): Promise<UserPersonaBuildStatusResponse> {
  const response = await fetch(`${API_BASE}/user-personas/${encodeURIComponent(personaId)}/build`, {
    headers: authHeaders()
  });
  if (!response.ok) {
    throw await parseApiError(response, "读取虚拟分身生成状态失败");
  }
  return response.json();
}

export async function fetchUserPersonaBuildArtifacts(
  personaId: string
): Promise<UserPersonaBuildArtifactsResponse> {
  const response = await fetch(`${API_BASE}/user-personas/${encodeURIComponent(personaId)}/build-artifacts`, {
    headers: authHeaders()
  });
  if (!response.ok) {
    throw await parseApiError(response, "读取虚拟分身生成报告失败");
  }
  return response.json();
}

export async function fetchEvidenceStats(): Promise<EvidenceCardStats> {
  const response = await fetch(`${API_BASE}/evidence/stats`, { headers: authHeaders() });
  if (!response.ok) {
    throw await parseApiError(response, "证据卡片统计请求失败");
  }
  return response.json();
}

export async function sendChat(
  message: string,
  sessionId?: string,
  personaId = "local_persona",
  thinkingEffort: ThinkingEffort = "low"
): Promise<ChatResponse> {
  const response = await fetch(`${API_BASE}/chat`, {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify({
      message,
      session_id: sessionId,
      persona_id: personaId,
      thinking_effort: thinkingEffort,
      top_k: 6,
      debug: true
    })
  });
  if (!response.ok) {
    throw await parseApiError(response, "对话请求失败");
  }
  return response.json();
}

export async function fetchChatSessions(
  sort: "recent" | "persona" = "recent",
  status: "active" | "archived" | "all" = "active"
): Promise<ChatSessionSummary[]> {
  const params = new URLSearchParams({ sort, status });
  const response = await fetch(`${API_BASE}/chat/sessions?${params.toString()}`, {
    headers: authHeaders()
  });
  if (!response.ok) {
    throw await parseApiError(response, "会话列表请求失败");
  }
  return response.json();
}

export async function createChatSession(
  personaId: string,
  title?: string
): Promise<ChatSessionSummary> {
  const response = await fetch(`${API_BASE}/chat/sessions`, {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify({ persona_id: personaId, title })
  });
  if (!response.ok) {
    throw await parseApiError(response, "新建会话失败");
  }
  return response.json();
}

export async function fetchChatSessionMessages(sessionId: string): Promise<ChatSessionMessagesResponse> {
  const response = await fetch(`${API_BASE}/chat/sessions/${encodeURIComponent(sessionId)}/messages`, {
    headers: authHeaders()
  });
  if (!response.ok) {
    throw await parseApiError(response, "会话消息请求失败");
  }
  return response.json();
}

export async function archiveChatSession(sessionId: string): Promise<ChatSessionSummary> {
  const response = await fetch(`${API_BASE}/chat/sessions/${encodeURIComponent(sessionId)}/archive`, {
    method: "POST",
    headers: authHeaders()
  });
  if (!response.ok) {
    throw await parseApiError(response, "归档会话失败");
  }
  return response.json();
}

export async function restoreChatSessionApi(sessionId: string): Promise<ChatSessionSummary> {
  const response = await fetch(`${API_BASE}/chat/sessions/${encodeURIComponent(sessionId)}/restore`, {
    method: "POST",
    headers: authHeaders()
  });
  if (!response.ok) {
    throw await parseApiError(response, "恢复会话失败");
  }
  return response.json();
}

export async function deleteChatSession(sessionId: string): Promise<{ message: string }> {
  const response = await fetch(`${API_BASE}/chat/sessions/${encodeURIComponent(sessionId)}`, {
    method: "DELETE",
    headers: authHeaders()
  });
  if (!response.ok) {
    throw await parseApiError(response, "删除会话失败");
  }
  return response.json();
}

export async function releaseEffortModel(thinkingEffort: ThinkingEffort): Promise<void> {
  const response = await fetch(`${API_BASE}/chat/release-effort-model`, {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify({ thinking_effort: thinkingEffort })
  });
  if (!response.ok) {
    throw await parseApiError(response, "模型释放请求失败");
  }
}

export async function releaseRuntimeModels(options: {
  thinkingEffort?: ThinkingEffort;
  includeEmbedding?: boolean;
  includeAllGenerationModels?: boolean;
}): Promise<{
  released_models: string[];
  still_loaded_models: string[];
  attempted_models: string[];
  elapsed_ms: number;
  ok: boolean;
}> {
  const response = await fetch(`${API_BASE}/chat/release-runtime-models`, {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify({
      thinking_effort: options.thinkingEffort,
      include_embedding: options.includeEmbedding ?? false,
      include_all_generation_models: options.includeAllGenerationModels ?? false
    })
  });
  if (!response.ok) {
    throw await parseApiError(response, "运行模型释放请求失败");
  }
  return response.json();
}

export async function fetchEvalRuns(): Promise<EvalRunListItem[]> {
  const response = await fetch(`${API_BASE}/eval/runs?limit=5`, { headers: authHeaders() });
  if (!response.ok) {
    throw await parseApiError(response, "评测记录请求失败");
  }
  return response.json();
}

export async function fetchMemoryItems(
  personaId?: string,
  sessionId?: string,
  scope: "session" | "user_global" | "all" = "session"
): Promise<MemoryListResponse> {
  const params = new URLSearchParams({ scope });
  if (personaId) params.set("persona_id", personaId);
  if (sessionId) params.set("session_id", sessionId);
  const response = await fetch(`${API_BASE}/memory/items?${params.toString()}`, {
    headers: authHeaders()
  });
  if (!response.ok) {
    throw await parseApiError(response, "记忆列表请求失败");
  }
  return response.json();
}

export async function fetchMemoryStats(
  personaId?: string,
  sessionId?: string,
  scope: "session" | "user_global" | "all" = "session"
): Promise<MemoryStatsResponse> {
  const params = new URLSearchParams({ scope });
  if (personaId) params.set("persona_id", personaId);
  if (sessionId) params.set("session_id", sessionId);
  const suffix = params.toString() ? `?${params.toString()}` : "";
  const response = await fetch(`${API_BASE}/memory/stats${suffix}`, { headers: authHeaders() });
  if (!response.ok) {
    throw await parseApiError(response, "记忆统计请求失败");
  }
  return response.json();
}

export async function proposeMemory(
  content: string,
  personaId: string,
  sessionId?: string
): Promise<void> {
  const response = await fetch(`${API_BASE}/memory/propose`, {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify({ content, persona_id: personaId, session_id: sessionId })
  });
  if (!response.ok) {
    throw await parseApiError(response, "记忆提议失败");
  }
}

export async function updateMemoryStatus(
  memoryId: string,
  action: "approve" | "reject" | "retract",
  sessionId?: string
): Promise<void> {
  const params = new URLSearchParams();
  if (sessionId) params.set("session_id", sessionId);
  const suffix = params.toString() ? `?${params.toString()}` : "";
  const response = await fetch(`${API_BASE}/memory/${encodeURIComponent(memoryId)}/${action}${suffix}`, {
    method: "POST",
    headers: authHeaders()
  });
  if (!response.ok) {
    throw await parseApiError(response, "记忆操作失败");
  }
}

export async function runEval(mode: "retrieval" | "chat" | "judge" = "retrieval"): Promise<EvalRunResponse> {
  const response = await fetch(`${API_BASE}/eval/run`, {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify({
      mode,
      include_results: false
    })
  });
  if (!response.ok) {
    throw await parseApiError(response, "评测执行失败");
  }
  return response.json();
}

export async function submitPersonaTurnFeedback(
  payload: PersonaTurnFeedbackPayload
): Promise<PersonaTurnFeedbackResponse> {
  const response = await fetch(`${API_BASE}/feedback/persona-turn`, {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify(payload)
  });
  if (!response.ok) {
    throw await parseApiError(response, "反馈保存失败");
  }
  return response.json();
}

export async function fetchPersonaFeedbackStats(): Promise<PersonaTurnFeedbackStatsResponse> {
  const response = await fetch(`${API_BASE}/feedback/stats?recent_limit=5`, { headers: authHeaders() });
  if (!response.ok) {
    throw await parseApiError(response, "反馈统计请求失败");
  }
  return response.json();
}

export async function fetchBrowserAcceptanceMatrix(): Promise<BrowserAcceptanceMatrixResponse> {
  const response = await fetch(`${API_BASE}/feedback/browser-acceptance-matrix`, {
    headers: authHeaders()
  });
  if (!response.ok) {
    throw await parseApiError(response, "浏览器验收矩阵请求失败");
  }
  return response.json();
}

export async function registerAccount(payload: {
  email: string;
  username: string;
  password: string;
  website?: string;
  challenge?: AuthChallengeProof;
}): Promise<{ message: string }> {
  const { challenge, ...registerPayload } = payload;
  const response = await fetch(`${API_BASE}/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...registerPayload, ...challenge })
  });
  if (!response.ok) {
    throw await parseApiError(response, "注册失败");
  }
  return response.json();
}

export async function verifyEmail(payload: { email: string; code: string }): Promise<AuthUser> {
  const response = await fetch(`${API_BASE}/auth/verify-email`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  if (!response.ok) {
    throw await parseApiError(response, "邮箱验证失败");
  }
  return response.json();
}

export async function resendVerification(
  email: string,
  website = "",
  challenge?: AuthChallengeProof
): Promise<{ message: string }> {
  const response = await fetch(`${API_BASE}/auth/resend-verification`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, website, ...challenge })
  });
  if (!response.ok) {
    throw await parseApiError(response, "重发验证码失败");
  }
  return response.json();
}

export async function loginAccount(payload: {
  login: string;
  password: string;
  website?: string;
  challenge?: AuthChallengeProof;
}): Promise<LoginResponse> {
  const { challenge, ...loginPayload } = payload;
  const response = await fetch(`${API_BASE}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...loginPayload, ...challenge })
  });
  if (!response.ok) {
    throw await parseApiError(response, "登录失败");
  }
  return response.json();
}

export async function logoutAccount(): Promise<void> {
  const response = await fetch(`${API_BASE}/auth/logout`, {
    method: "POST",
    headers: authHeaders()
  });
  if (!response.ok) {
    throw await parseApiError(response, "退出登录失败");
  }
}

export async function fetchCurrentUser(): Promise<AuthUser> {
  const response = await fetch(`${API_BASE}/auth/me`, { headers: authHeaders() });
  if (!response.ok) {
    throw await parseApiError(response, "当前账号请求失败");
  }
  return response.json();
}

export async function fetchThemePreference(): Promise<ThemePreferenceResponse> {
  const response = await fetch(`${API_BASE}/auth/theme-preference`);
  if (!response.ok) {
    throw await parseApiError(response, "主题偏好请求失败");
  }
  return response.json();
}

export async function updateThemePreference(theme: ThemePreferenceResponse["theme"]): Promise<ThemePreferenceResponse> {
  const response = await fetch(`${API_BASE}/auth/theme-preference`, {
    method: "PUT",
    headers: jsonHeaders(),
    body: JSON.stringify({ theme })
  });
  if (!response.ok) {
    throw await parseApiError(response, "主题偏好保存失败");
  }
  return response.json();
}

export async function fetchAdminUsers(): Promise<AdminUsersResponse> {
  const response = await fetch(`${API_BASE}/admin/users`, { headers: authHeaders() });
  if (!response.ok) {
    throw await parseApiError(response, "用户列表请求失败");
  }
  return response.json();
}

export async function createAdminUser(payload: {
  email: string;
  username: string;
  password: string;
  role: "admin" | "user";
  status: "pending_verification" | "active" | "disabled";
  email_verified: boolean;
  send_verification: boolean;
}): Promise<AuthUser> {
  const response = await fetch(`${API_BASE}/admin/users`, {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify(payload)
  });
  if (!response.ok) {
    throw await parseApiError(response, "创建用户失败");
  }
  return response.json();
}

export async function setAdminUserStatus(
  userId: string,
  action: "enable" | "disable"
): Promise<AuthUser> {
  const response = await fetch(`${API_BASE}/admin/users/${encodeURIComponent(userId)}/${action}`, {
    method: "POST",
    headers: authHeaders()
  });
  if (!response.ok) {
    throw await parseApiError(response, "更新用户状态失败");
  }
  return response.json();
}

export async function deleteAdminUser(userId: string): Promise<{ message: string }> {
  const response = await fetch(`${API_BASE}/admin/users/${encodeURIComponent(userId)}`, {
    method: "DELETE",
    headers: authHeaders()
  });
  if (!response.ok) {
    throw await parseApiError(response, "删除用户失败");
  }
  return response.json();
}

export async function resetAdminUserPassword(userId: string, password: string): Promise<AuthUser> {
  const response = await fetch(`${API_BASE}/admin/users/${encodeURIComponent(userId)}/reset-password`, {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify({ password, must_change_password: true })
  });
  if (!response.ok) {
    throw await parseApiError(response, "重置密码失败");
  }
  return response.json();
}

export async function streamChat(
  message: string,
  sessionId: string | undefined,
  personaId: string,
  thinkingEffort: ThinkingEffort,
  handlers: {
    onToken: (value: string) => void;
    onFinal: (value: ChatResponse) => void;
    onStage?: (value: StreamStageEvent) => void;
    onDiagnostic?: (value: HiddenThinkingDeltaEvent) => void;
  },
  signal?: AbortSignal
): Promise<void> {
  const response = await fetch(`${API_BASE}/chat/stream`, {
    method: "POST",
    headers: jsonHeaders(),
    signal,
    body: JSON.stringify({
      message,
      session_id: sessionId,
      persona_id: personaId,
      thinking_effort: thinkingEffort,
      top_k: 6,
      debug: true
    })
  });
  if (!response.ok) {
    throw await parseApiError(response, "对话流请求失败");
  }
  if (!response.body) {
    throw new Error("对话流返回了空响应。");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const events = buffer.split("\n\n");
    buffer = events.pop() ?? "";
    for (const event of events) {
      const line = event
        .split("\n")
        .find((item) => item.startsWith("data:"));
      if (!line) continue;
      const payload = JSON.parse(line.slice(5).trim());
      if (payload.type === "token") {
        handlers.onToken(String(payload.value ?? ""));
      } else if (payload.type === "final") {
        handlers.onFinal(payload.value as ChatResponse);
      } else if (payload.type === "stage") {
        handlers.onStage?.(payload.value as StreamStageEvent);
      } else if (payload.type === "diagnostic") {
        handlers.onDiagnostic?.(payload.value as HiddenThinkingDeltaEvent);
      }
    }
  }
}
