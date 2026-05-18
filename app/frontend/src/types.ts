export type Citation = {
  chunk_id: string;
  doc_id: string;
  title: string;
  source_path: string;
  section_path: string;
  preview: string;
  score: number;
  trust_level: string;
  privacy_level: string;
};

export type TimingBreakdown = {
  ingest_ms: number;
  retrieval_ms: number;
  rerank_ms: number;
  context_ms: number;
  generation_ms: number;
  verification_ms: number;
  total_ms: number;
};

export type VerificationClaim = {
  text: string;
  support_score: number;
  supported: boolean;
  best_citation_ids: string[];
};

export type VerificationResult = {
  claim_count: number;
  supported_claim_count: number;
  unsupported_claim_count: number;
  claim_support_rate: number;
  unsupported_claims: string[];
  claims: VerificationClaim[];
};

export type RetrievalTrace = {
  original_query: string;
  persona_id: string;
  requested_persona_id?: string | null;
  rewritten_queries: string[];
  candidates: Citation[];
  selected_chunk_ids: string[];
  notes: string[];
};

export type ChatResponse = {
  answer: string;
  mode: string;
  confidence: string;
  thinking_effort?: ThinkingEffort;
  follow_up_questions?: string[];
  citations: Citation[];
  memory_citations?: MemoryCitation[];
  retrieval_trace: RetrievalTrace;
  verification: VerificationResult;
  timings: TimingBreakdown;
  model: string;
  request_id: string;
  session_id: string;
  diagnostics?: ChatDiagnostics | null;
};

export type ChatSessionSummary = {
  session_id: string;
  user_id?: string | null;
  persona_id: string;
  persona_name?: string | null;
  title: string;
  created_at: number;
  last_seen_at: number;
  message_count: number;
  last_message_preview: string;
  status: "active" | "archived" | "deleted";
  archived_at?: number | null;
  deleted_at?: number | null;
  opening_message?: string | null;
};

export type ChatSessionMessage = {
  id: string;
  request_id: string;
  session_id: string;
  persona_id: string;
  role: "user" | "assistant";
  content: string;
  ts: number;
  model?: string | null;
  mode?: string | null;
  confidence?: string | null;
  diagnostics?: ChatDiagnostics | null;
  follow_up_questions?: string[];
};

export type ChatSessionMessagesResponse = {
  session: ChatSessionSummary;
  messages: ChatSessionMessage[];
};

export type HiddenThinkingEvent = {
  event_id: string;
  phase: string;
  model: string;
  provider: string;
  source: string;
  content: string;
  elapsed_ms: number;
  sequence: number;
};

export type VisibleAnswerSource = {
  phase: string;
  source: string;
  model: string;
  preview: string;
  elapsed_ms: number;
};

export type ChatDiagnostics = {
  enabled: boolean;
  hidden_thinking_events: HiddenThinkingEvent[];
  final_answer_source?: string | null;
  visible_answer_sources?: VisibleAnswerSource[];
  thinking_budget?: number | null;
  thinking_tokens_observed?: number | null;
  thinking_budget_ratio?: number | null;
  thinking_budget_stop_reason?: string | null;
  thinking_budget_overshoot_tokens?: number | null;
};

export type HiddenThinkingDeltaEvent = {
  kind:
    | "hidden_thinking_delta"
    | "phase_started"
    | "phase_finished"
    | "phase_cancelled"
    | "heartbeat"
    | "visible_answer_source"
    | "final_answer_selected"
    | "thinking_budget_progress";
  event_id?: string;
  phase?: string;
  model?: string;
  provider?: string;
  source?: string;
  delta?: string;
  elapsed_ms?: number;
  sequence?: number;
  thinking_budget?: number | null;
  thinking_tokens_observed?: number | null;
  thinking_budget_ratio?: number | null;
  thinking_budget_stop_reason?: string | null;
  thinking_budget_overshoot_tokens?: number | null;
};

export type MemoryCitation = {
  memory_id: string;
  user_id?: string;
  session_id?: string;
  persona_id: string;
  scope: string;
  memory_type: string;
  content: string;
  confidence: number;
};

export type ThinkingEffort = "low" | "medium" | "high";

export type UserRole = "admin" | "user";

export type UserStatus = "pending_verification" | "active" | "disabled";

export type AuthUser = {
  id: string;
  email: string;
  username: string;
  role: UserRole;
  status: UserStatus;
  email_verified: boolean;
  must_change_password: boolean;
  created_at: string;
  updated_at: string;
  last_login_at?: string | null;
  theme_preference?: "black_gray" | "klee_bomb";
};

export type LoginResponse = {
  token: string;
  token_type: "bearer";
  expires_at: string;
  user: AuthUser;
};

export type ThemePreferenceResponse = {
  theme: "black_gray" | "klee_bomb";
  source: "default" | "ip_user" | "user";
};

export type AuthChallengePurpose = "register" | "login" | "resend_verification";

export type AuthChallengeResponse = {
  challenge_id: string;
  purpose: AuthChallengePurpose;
  nonce: string;
  algorithm: "sha256-prefix-zero" | "slider-puzzle-v1";
  difficulty: number;
  issued_at: string;
  expires_at: string;
  min_elapsed_ms: number;
  prompt: string;
  slider_track_width?: number | null;
  slider_piece_size?: number | null;
  slider_target_x?: number | null;
  slider_target_y?: number | null;
  slider_tolerance?: number | null;
  slider_image_url?: string | null;
  slider_image_label?: string | null;
  slider_decoys?: Array<{ x: number; y: number }>;
};

export type AuthChallengeProof = {
  challenge_id: string;
  challenge_nonce: string;
  challenge_counter?: number;
  challenge_answer?: number;
  challenge_elapsed_ms: number;
};

export type AdminUsersResponse = {
  users: AuthUser[];
};

export type EffortRuntimePlan = {
  model: string;
  model_ready: boolean;
  timeout_seconds: number;
  num_predict: number;
  think: boolean;
  thinking_budget?: number | null;
  display_thinking_budget?: number | null;
  refinement_passes: number;
};

export type StatusResponse = {
  env: string;
  model_provider: string;
  generation_model: string;
  quality_generation_model?: string | null;
  quality_generation_min_effort?: ThinkingEffort;
  quality_generation_think?: boolean | null;
  quality_generation_refinement_passes?: number | null;
  model_timeout_seconds: number;
  model_keep_alive: string;
  model_think: boolean;
  model_num_predict: number;
  model_temperature: number;
  model_top_p: number;
  effort_runtime_plans?: Partial<Record<ThinkingEffort, EffortRuntimePlan>>;
  active_generation?: ActiveGenerationStatus | null;
  loaded_ollama_models?: LoadedOllamaModelStatus[];
  post_persona_alignment_enabled: boolean;
  post_persona_alignment_event_rows: number;
  post_persona_alignment_reason_counts: Record<string, number>;
  persona_first_enabled: boolean;
  persona_first_event_rows: number;
  persona_first_mode_counts: Record<string, number>;
  embedding_model: string;
  retrieval_mode: string;
  query_rewrite_enabled: boolean;
  local_reranker_enabled: boolean;
  source_selector_enabled: boolean;
  source_selector_intent_filter_enabled: boolean;
  source_selector_top_k: number;
  reranker_backend: string;
  reranker_model: string;
  reranker_hf_model: string;
  reranker_enabled: boolean;
  deepseek_api_key_configured?: boolean;
  ollama_base_url: string;
  ollama_models_dir: string;
  model_server_ready: boolean;
  generation_model_ready: boolean;
  quality_generation_model_ready?: boolean;
  embedding_model_ready: boolean;
  reranker_model_ready: boolean;
  corpus_dir: string;
  data_dir: string;
  sqlite_path: string;
  corpus_ready: boolean;
  index_ready: boolean;
  dense_index_ready: boolean;
  metadata_store_ready: boolean;
  document_rows: number;
  chunk_rows: number;
  session_rows: number;
  retrieval_event_rows: number;
  chat_event_rows: number;
  eval_run_rows: number;
  eval_case_result_rows: number;
  evidence_card_rows?: number;
  evidence_card_audit_rows?: number;
  memory_item_rows?: number;
  memory_audit_event_rows?: number;
  resource_usage?: ResourceUsage;
};

export type ActiveGenerationStatus = {
  call_id: string;
  phase: string;
  model: string;
  provider: string;
  source: string;
  elapsed_ms: number;
  last_event_age_ms: number;
};

export type LoadedOllamaModelStatus = {
  name: string;
  model: string;
  size_vram?: number | null;
  size?: number | null;
  processor?: string | null;
  expires_at?: string | null;
};

export type ResourceUsage = {
  cpu_percent?: number | null;
  process_cpu_percent?: number | null;
  memory_total_mb?: number | null;
  memory_used_mb?: number | null;
  memory_percent?: number | null;
  process_memory_mb?: number | null;
  data_disk_total_gb?: number | null;
  data_disk_free_gb?: number | null;
  data_disk_percent?: number | null;
  model_disk_total_gb?: number | null;
  model_disk_free_gb?: number | null;
  model_disk_percent?: number | null;
  gpu_name?: string | null;
  gpu_util_percent?: number | null;
  gpu_memory_total_mb?: number | null;
  gpu_memory_used_mb?: number | null;
  gpu_memory_free_mb?: number | null;
  gpu_memory_percent?: number | null;
  gpu_temperature_c?: number | null;
  gpu_power_draw_w?: number | null;
};

export type StreamStageEvent = {
  key: string;
  label: string;
  elapsed_ms: number;
  detail?: string;
};

export type EvidenceCardStats = {
  total_cards: number;
  manifest_total_cards?: number | null;
  manifest_matches_store: boolean;
  by_persona: Record<string, number>;
  by_trust_level: Record<string, number>;
  source_title_count: number;
  audited_sync_events: number;
};

export type PersonaProfile = {
  id: string;
  name: string;
  subtitle: string;
  description: string;
  avatar_label: string;
  avatar_url?: string | null;
  identity_tags?: string[];
  source_note: string;
  boundary_note: string;
  corpus_paths: string[];
  retrieval_prefixes?: string[];
  raw_source_paths?: string[];
  source_urls?: string[];
  suggested_questions: string[];
  kind?: PersonaCardKind;
  is_owner?: boolean;
  is_public?: boolean;
  published_at?: number | null;
};

export type PersonaCardKind = "system" | "user";
export type UserPersonaStatus = "draft" | "building" | "ready" | "error";
export type UserPersonaBuildStatus = "queued" | "running" | "succeeded" | "failed";

export type PersonaCatalogCard = {
  id: string;
  name: string;
  avatar_url?: string | null;
  avatar_label: string;
  identity_tags: string[];
  short_description: string;
  kind: PersonaCardKind;
  runtime_status: UserPersonaStatus;
  score: number;
  is_owner: boolean;
  is_public?: boolean;
  published_at?: number | null;
};

export type UserPersonaDetail = PersonaCatalogCard & {
  owner_user_id: string;
  description: string;
  is_public: boolean;
  web_search_enabled?: boolean;
  source_depth?: string;
  evidence_card_count?: number;
  build_error?: string;
  created_at: number;
  updated_at: number;
  published_at?: number | null;
};

export type PersonaCatalogSearchResponse = {
  query: string;
  results: PersonaCatalogCard[];
};

export type PersonaCatalogRecommendedResponse = {
  candidates_considered: number;
  results: PersonaCatalogCard[];
};

export type PersonaCatalogPublicResponse = {
  query: string;
  sort: "published_at" | "score";
  offset: number;
  limit: number;
  total: number;
  results: PersonaCatalogCard[];
};

export type UserPersonaListResponse = {
  personas: UserPersonaDetail[];
};

export type UserPersonaDraftCreatePayload = {
  name: string;
  description: string;
  web_search_enabled: boolean;
};

export type UserPersonaFileItem = {
  file_id: string;
  persona_id: string;
  original_filename: string;
  mime_type: string;
  extension: string;
  size_bytes: number;
  sha256: string;
  upload_status: string;
  parse_status: string;
  parser_chain: string[];
  quality_score: number;
  warnings: string[];
  error_message: string;
  page_count?: number | null;
  created_at: number;
  updated_at: number;
};

export type UserPersonaFileListResponse = {
  files: UserPersonaFileItem[];
  max_files: number;
  max_file_size_bytes: number;
  supported_extensions: string[];
};

export type UserPersonaParsedFileResponse = {
  file: UserPersonaFileItem;
  markdown: string;
  blocks: Array<Record<string, unknown>>;
  provenance: Array<Record<string, unknown>>;
  diagnostics: Array<Record<string, unknown>>;
  parser_candidates: Array<Record<string, unknown>>;
  quality_summary: Record<string, unknown>;
};

export type UserPersonaBuildStatusResponse = {
  build_id: string;
  persona_id: string;
  status: UserPersonaBuildStatus;
  phase: string;
  progress: number;
  model: string;
  artifact_dir: string;
  source_depth: string;
  evidence_card_count: number;
  error: string;
  quality_summary: Record<string, unknown>;
  created_at: number;
  updated_at: number;
  finished_at?: number | null;
  persona?: UserPersonaDetail | null;
};

export type UserPersonaBuildArtifactsResponse = {
  build: UserPersonaBuildStatusResponse;
  source_bundle: Record<string, unknown>;
  quality_summary: Record<string, unknown>;
  generated_files: string[];
  report_markdown: string;
};

export type PersonaMaterialDocument = {
  doc_id: string;
  title: string;
  source_path: string;
  source_type: string;
  trust_level: string;
  privacy_level: string;
  chunk_count: number;
  sections: string[];
  preview: string;
};

export type PersonaMaterialsResponse = {
  persona_id: string;
  requested_persona_id?: string | null;
  corpus_paths: string[];
  retrieval_prefixes: string[];
  raw_source_paths: string[];
  source_urls: string[];
  documents: PersonaMaterialDocument[];
};

export type UiMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  response?: ChatResponse;
  diagnostics?: ChatDiagnostics | null;
  followUpQuestions?: string[];
};

export type FeedbackIssue =
  | "cardiness"
  | "lecture"
  | "too_long"
  | "unnatural"
  | "memory_error"
  | "era_boundary_error"
  | "fact_error"
  | "good"
  | "other";

export type FeedbackSeverity = "low" | "medium" | "high";

export type PersonaTurnFeedbackPayload = {
  persona_id: string;
  persona_name?: string;
  session_id: string;
  request_id: string;
  acceptance_case_id?: string | null;
  user_message: string;
  assistant_answer: string;
  issue: FeedbackIssue;
  severity: FeedbackSeverity;
  note?: string;
  thinking_effort?: ThinkingEffort;
  mode?: string;
  model?: string;
  trace_notes?: string[];
  citation_doc_ids?: string[];
  citation_titles?: string[];
  frontend_url?: string;
};

export type PersonaTurnFeedbackResponse = {
  feedback_id: string;
  message: string;
};

export type PersonaTurnFeedbackRecord = PersonaTurnFeedbackPayload & {
  feedback_id: string;
  created_at: string;
};

export type PersonaTurnFeedbackStatsResponse = {
  total: number;
  negative_total: number;
  positive_total: number;
  invalid_line_count: number;
  by_issue: Record<string, number>;
  by_persona: Record<string, number>;
  by_severity: Record<string, number>;
  by_persona_issue: Record<string, Record<string, number>>;
  latest_records: PersonaTurnFeedbackRecord[];
};

export type BrowserAcceptancePersona = {
  persona_id: string;
  display_name: string;
};

export type BrowserAcceptanceCategory = {
  category_id: string;
  label: string;
  acceptance_focus: string[];
  feedback_labels: string[];
  promotion_target: string;
};

export type BrowserAcceptanceCase = {
  case_id: string;
  persona_id: string;
  category_id: string;
  prompt: string;
  expected_behavior: string;
  watch_for: string[];
};

export type BrowserAcceptanceCaseFeedback = {
  matched_feedback_count: number;
  negative_feedback_count: number;
  positive_feedback_count: number;
  issue_counts: Record<string, number>;
  latest_feedback_id?: string | null;
  latest_issue?: string | null;
  latest_severity?: string | null;
  latest_created_at?: string | null;
};

export type BrowserAcceptanceMatrixResponse = {
  schema_version: string;
  description: string;
  default_thinking_effort: ThinkingEffort;
  personas: BrowserAcceptancePersona[];
  categories: BrowserAcceptanceCategory[];
  cases: BrowserAcceptanceCase[];
  total_cases: number;
  filtered_cases: number;
  by_persona: Record<string, number>;
  by_category: Record<string, number>;
  matched_feedback_records: number;
  tested_cases: number;
  negative_cases: number;
  positive_cases: number;
  case_feedback: Record<string, BrowserAcceptanceCaseFeedback>;
};

export type MemoryItem = {
  id: string;
  user_id?: string;
  session_id?: string;
  persona_id: string;
  scope: string;
  memory_type: string;
  status: string;
  content: string;
  sensitivity: string;
  source: string;
  tags: string[];
  confidence: number;
  created_at: number;
  updated_at: number;
  expires_at?: number | null;
};

export type MemoryListResponse = {
  items: MemoryItem[];
};

export type MemoryStatsResponse = {
  total: number;
  by_persona: Record<string, number>;
  by_session?: Record<string, number>;
  by_status: Record<string, number>;
  by_type: Record<string, number>;
  by_sensitivity: Record<string, number>;
  by_persona_status: Record<string, Record<string, number>>;
  current_session_total?: number;
  current_session_approved?: number;
};

export type EvalRunMetrics = {
  pass_rate: number;
  mean_source_recall: number;
  mean_citation_precision: number;
  top1_accuracy: number;
  mean_mrr: number;
  mean_ndcg: number;
  mean_keyword_coverage: number;
  mean_evidence_overlap: number;
  mean_claim_support_rate: number;
  unsupported_claim_rate: number;
  abstention_accuracy: number;
  language_match_rate: number;
  forbidden_keyword_violation_rate: number;
  judge_pass_rate?: number;
  mean_judge_score?: number;
  weakest_judge_dimension?: string | null;
  weakest_judge_score?: number;
  mean_latency_ms: number;
};

export type EvalRunListItem = {
  run_id: string;
  ts: number;
  status: string;
  mode: string;
  question_count: number;
  passed_count: number;
  failed_count: number;
  metrics: EvalRunMetrics;
};

export type EvalRunResponse = EvalRunListItem & {
  message: string;
  results: unknown[];
  report_path?: string | null;
  report_json_path?: string | null;
};
