import { FormEvent, useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { CircleSlash, FileSearch, FileText, Plus, RefreshCw, X } from "lucide-react";
import {
  createUserPersonaDraft,
  deleteUserPersonaFile,
  fetchUserPersonaBuild,
  fetchUserPersonaFiles,
  rebuildUserPersona,
  startUserPersonaBuild,
  uploadUserPersonaFile
} from "../api";
import {
  formatBytes,
  parseStatusLabel,
  USER_PERSONA_MAX_FILE_SIZE,
  USER_PERSONA_MAX_FILES,
  USER_PERSONA_SUPPORTED_EXTENSIONS
} from "../frontendText";
import type { UserPersonaBuildStatusResponse, UserPersonaDetail, UserPersonaFileItem } from "../types";

type UploadCandidate = {
  id: string;
  file: File;
  progress: number;
  speedKbps: number | null;
  status: "queued" | "uploading" | "uploaded" | "failed";
  error?: string;
  backendFile?: UserPersonaFileItem;
};

type CreateUserPersonaDialogProps = {
  onClose: () => void;
  onCreated: (persona: UserPersonaDetail) => void;
};

function fileExtension(file: File) {
  return file.name.split(".").pop()?.toLowerCase() ?? "";
}

export function CreateUserPersonaDialog({ onClose, onCreated }: CreateUserPersonaDialogProps) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [webSearchEnabled, setWebSearchEnabled] = useState(false);
  const [files, setFiles] = useState<UploadCandidate[]>([]);
  const [createdDraft, setCreatedDraft] = useState<UserPersonaDetail | null>(null);
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [deletingFileIds, setDeletingFileIds] = useState<Set<string>>(() => new Set());
  const [buildStarted, setBuildStarted] = useState(false);
  const [buildBusy, setBuildBusy] = useState(false);
  const uploadControllers = useRef<Map<string, AbortController>>(new Map());
  const removedCandidates = useRef<Set<string>>(new Set());

  const parsedFilesQuery = useQuery({
    queryKey: ["user-persona-files", createdDraft?.id],
    queryFn: () => fetchUserPersonaFiles(createdDraft!.id),
    enabled: Boolean(createdDraft?.id),
    refetchInterval: createdDraft ? 1800 : false
  });

  const buildQuery = useQuery({
    queryKey: ["user-persona-build", createdDraft?.id],
    queryFn: () => fetchUserPersonaBuild(createdDraft!.id),
    enabled: Boolean(createdDraft?.id && buildStarted),
    retry: false,
    refetchInterval: (query) => {
      const data = query.state.data as UserPersonaBuildStatusResponse | undefined;
      return data?.status === "queued" || data?.status === "running" ? 1800 : false;
    }
  });

  useEffect(() => {
    const persona = buildQuery.data?.persona;
    if (!persona) return;
    setCreatedDraft(persona);
    onCreated(persona);
  }, [buildQuery.data?.persona, onCreated]);

  function addFiles(nextFiles: FileList | File[]) {
    const incoming = Array.from(nextFiles);
    const accepted: UploadCandidate[] = [];
    const errors: string[] = [];
    const currentCount = files.length;

    for (const file of incoming) {
      const extension = fileExtension(file);
      if (currentCount + accepted.length >= USER_PERSONA_MAX_FILES) {
        errors.push("最多上传 20 个文件。");
        break;
      }
      if (file.size > USER_PERSONA_MAX_FILE_SIZE) {
        errors.push(`${file.name} 超过 50MB。`);
        continue;
      }
      if (!USER_PERSONA_SUPPORTED_EXTENSIONS.includes(extension)) {
        errors.push(`${file.name} 的格式暂不支持。`);
        continue;
      }
      accepted.push({
        id: globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${accepted.length}`,
        file,
        progress: 0,
        speedKbps: null,
        status: "queued"
      });
    }

    if (accepted.length) {
      setFiles((current) => [...current, ...accepted]);
    }
    if (errors.length) {
      setNotice(Array.from(new Set(errors)).join(" "));
    }
  }

  async function ensureDraft() {
    if (createdDraft) return createdDraft;
    const draft = await createUserPersonaDraft({
      name: name.trim(),
      description: description.trim(),
      web_search_enabled: webSearchEnabled
    });
    setCreatedDraft(draft);
    onCreated(draft);
    return draft;
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!name.trim()) {
      setNotice("请先填写分身名称。");
      return;
    }
    setBusy(true);
    setNotice("");
    try {
      const draft = await ensureDraft();
      for (const item of files.filter((candidate) => candidate.status === "queued" || candidate.status === "failed")) {
        if (removedCandidates.current.has(item.id)) {
          continue;
        }
        const controller = new AbortController();
        uploadControllers.current.set(item.id, controller);
        setFiles((current) =>
          current.map((candidate) =>
            candidate.id === item.id ? { ...candidate, status: "uploading", error: undefined } : candidate
          )
        );
        try {
          const uploaded = await uploadUserPersonaFile(draft.id, item.file, ({ loaded, total, speedKbps }) => {
            if (removedCandidates.current.has(item.id)) return;
            setFiles((current) =>
              current.map((candidate) =>
                candidate.id === item.id
                  ? {
                      ...candidate,
                      progress: total ? loaded / total : candidate.progress,
                      speedKbps,
                      status: "uploading"
                    }
                  : candidate
              )
            );
          }, controller.signal);
          if (removedCandidates.current.has(item.id)) {
            await deleteUserPersonaFile(draft.id, uploaded.file_id).catch(() => undefined);
            continue;
          }
          setFiles((current) =>
            current.map((candidate) =>
              candidate.id === item.id
                ? {
                    ...candidate,
                    progress: 1,
                    speedKbps: null,
                    status: "uploaded",
                    backendFile: uploaded
                  }
                : candidate
            )
          );
        } catch (error) {
          if (removedCandidates.current.has(item.id)) {
            continue;
          }
          setFiles((current) =>
            current.map((candidate) =>
              candidate.id === item.id
                ? {
                    ...candidate,
                    speedKbps: null,
                    status: "failed",
                    error: error instanceof Error ? error.message : "上传失败"
                  }
                : candidate
            )
          );
        } finally {
          uploadControllers.current.delete(item.id);
        }
      }
      await parsedFilesQuery.refetch();
      setNotice("资料已上传。解析会在后台继续，下一阶段会用这些结果生成知识库。");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "创建分身草稿失败。");
    } finally {
      setBusy(false);
    }
  }

  async function startBuild() {
    if (!name.trim()) {
      setNotice("请先填写分身名称。");
      return;
    }
    if (hasPendingLocalUploads) {
      setNotice("请先上传已选择的文件，再开始生成分身。");
      return;
    }
    if (hasParsingFiles) {
      setNotice("文件仍在解析中，请稍后再开始生成。");
      return;
    }
    setBuildBusy(true);
    setNotice("");
    try {
      const draft = await ensureDraft();
      const response = buildQuery.data?.status === "failed"
        ? await rebuildUserPersona(draft.id)
        : await startUserPersonaBuild(draft.id);
      setBuildStarted(true);
      if (response.persona) {
        setCreatedDraft(response.persona);
        onCreated(response.persona);
      }
      await buildQuery.refetch();
      setNotice("已开始生成虚拟分身。");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "启动分身生成失败。");
    } finally {
      setBuildBusy(false);
    }
  }

  async function removeCandidate(item: UploadCandidate) {
    removedCandidates.current.add(item.id);
    uploadControllers.current.get(item.id)?.abort();
    uploadControllers.current.delete(item.id);
    setFiles((current) => current.filter((candidate) => candidate.id !== item.id));
    if (!createdDraft || !item.backendFile) {
      return;
    }
    await removeBackendFile(item.backendFile.file_id, item.file.name);
  }

  async function removeBackendFile(fileId: string, filename: string) {
    if (!createdDraft || deletingFileIds.has(fileId)) return;
    setDeletingFileIds((current) => new Set(current).add(fileId));
    setNotice("");
    try {
      await deleteUserPersonaFile(createdDraft.id, fileId);
      setFiles((current) => current.filter((candidate) => candidate.backendFile?.file_id !== fileId));
      await parsedFilesQuery.refetch();
      setNotice(`${filename} 已删除。`);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "删除文件失败。");
    } finally {
      setDeletingFileIds((current) => {
        const next = new Set(current);
        next.delete(fileId);
        return next;
      });
    }
  }

  const hasPendingLocalUploads = files.some((item) => item.status === "queued" || item.status === "uploading");
  const remoteFiles = parsedFilesQuery.data?.files ?? [];
  const hasParsingFiles = remoteFiles.some((file) => ["queued", "parsing"].includes(file.parse_status));
  const build = buildQuery.data;
  const buildProgress = Math.max(0, Math.min(1, build?.progress ?? 0));
  const buildIsRunning = build?.status === "queued" || build?.status === "running";
  const buildSucceeded = build?.status === "succeeded" || createdDraft?.runtime_status === "ready";
  const buildFailed = build?.status === "failed" || createdDraft?.runtime_status === "error";

  return (
    <div className="personaDetailOverlay" role="presentation" onMouseDown={onClose}>
      <section
        className="personaDetailModal createPersonaModal surfaceTransition"
        role="dialog"
        aria-modal="true"
        aria-label="创建虚拟分身"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <button type="button" className="iconButton personaDetailClose" onClick={onClose} aria-label="关闭">
          <CircleSlash size={16} />
        </button>
        <form className="createPersonaForm" onSubmit={submit}>
          <div>
            <p className="eyebrow">创建虚拟分身</p>
            <h2>先上传一切能代表它的资料</h2>
            <p>
              本阶段只完成强文件读取与上传底座；上传后会生成 Markdown、结构块和 provenance，
              后续再进入整理、分类和知识库生成。
            </p>
          </div>
          <label>
            <span>分身名称</span>
            <input value={name} onChange={(event) => setName(event.target.value)} maxLength={120} required />
          </label>
          <label>
            <span>分身基本描述</span>
            <textarea
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              placeholder="用几个词或者几句话来描述你要蒸馏的对象，如“和蔼可亲”、“对于事物有独特的见解”、“是一名工程师”等等"
              rows={4}
            />
          </label>
          <label className="createPersonaCheck">
            <input
              type="checkbox"
              checked={webSearchEnabled}
              onChange={(event) => setWebSearchEnabled(event.target.checked)}
            />
            联网搜索更多信息
          </label>
          <div className="uploadIntro">
            上传你能想到的一切信息，包括简历、代码、对话记录、截图等与分身相关的一切
          </div>
          <label
            className="personaUploadDropzone"
            onDragOver={(event) => event.preventDefault()}
            onDrop={(event) => {
              event.preventDefault();
              addFiles(event.dataTransfer.files);
            }}
          >
            <input
              type="file"
              multiple
              onChange={(event) => {
                if (event.target.files) addFiles(event.target.files);
                event.currentTarget.value = "";
              }}
            />
            <Plus size={34} />
            <strong>点击选择文件，或拖拽文件到这里</strong>
            <small>支持 {USER_PERSONA_SUPPORTED_EXTENSIONS.join("、")}；最多 20 个，单个 50MB。</small>
          </label>
          {files.length ? (
            <div className="uploadFileList" aria-label="上传文件列表">
              {files.map((item) => (
                <div key={item.id} className={`uploadFileRow ${item.status}`}>
                  <FileText size={16} />
                  <span>
                    <strong>{item.file.name}</strong>
                    <small>
                      {formatBytes(item.file.size)}
                      {item.backendFile ? ` · ${parseStatusLabel(item.backendFile.parse_status)}` : ""}
                      {item.error ? ` · ${item.error}` : ""}
                    </small>
                  </span>
                  <div className="uploadProgressCell">
                    <div className="uploadProgressTrack">
                      <i style={{ width: `${Math.round(item.progress * 100)}%` }} />
                    </div>
                    <small>
                      {item.status === "uploaded"
                        ? "上传完成"
                      : item.status === "uploading" && item.speedKbps !== null
                          ? `${item.speedKbps.toFixed(1)} kB/s`
                          : item.status === "failed"
                            ? "上传失败"
                            : "等待上传"}
                    </small>
                  </div>
                  <button
                    type="button"
                    className="uploadFileRemove"
                    onClick={() => void removeCandidate(item)}
                    aria-label={item.status === "uploading" ? `中止上传 ${item.file.name}` : `删除 ${item.file.name}`}
                    title={item.status === "uploading" ? "中止上传" : "删除文件"}
                  >
                    <X size={15} />
                  </button>
                </div>
              ))}
            </div>
          ) : null}
          {parsedFilesQuery.data?.files?.length ? (
            <div className="parsedFileSummary">
              {parsedFilesQuery.data.files.map((file) => (
                <div key={file.file_id} className="parsedFileRow">
                  <span>
                    {file.original_filename} · {parseStatusLabel(file.parse_status)}
                    {file.quality_score ? ` · 质量 ${Math.round(file.quality_score * 100)}%` : ""}
                    {file.warnings.length ? " · 需复查" : ""}
                  </span>
                  <button
                    type="button"
                    className="uploadFileRemove"
                    disabled={deletingFileIds.has(file.file_id)}
                    onClick={() => void removeBackendFile(file.file_id, file.original_filename)}
                    aria-label={`删除 ${file.original_filename}`}
                    title="删除文件"
                  >
                    {deletingFileIds.has(file.file_id) ? <RefreshCw size={14} className="spinIcon" /> : <X size={15} />}
                  </button>
                </div>
              ))}
            </div>
          ) : null}
          {notice ? <p className="sessionNotice">{notice}</p> : null}
          <div className="personaBuildPanel" aria-label="虚拟分身生成状态">
            <div className="personaBuildHeader">
              <strong>生成分身知识库</strong>
              <span>
                {buildSucceeded
                  ? "创建完成"
                  : buildFailed
                    ? "生成失败"
                    : buildIsRunning
                      ? build?.phase || "生成中"
                      : "等待开始"}
              </span>
            </div>
            <div className="uploadProgressTrack personaBuildTrack">
              <i style={{ width: `${Math.round((buildSucceeded ? 1 : buildProgress) * 100)}%` }} />
            </div>
            <small>
              {buildSucceeded
                ? `已生成 ${createdDraft?.evidence_card_count ?? build?.evidence_card_count ?? 0} 张证据卡。`
                : buildFailed
                  ? build?.error || createdDraft?.build_error || "请检查资料质量后重试。"
                  : buildIsRunning
                    ? "正在整理资料、提取事实、生成语气与证据卡。"
                    : "上传资料完成后，可以启动 DeepSeek V4 Pro 构建。"}
            </small>
          </div>
          <div className="personaDetailActions">
            <button type="button" className="ghostButton" onClick={onClose}>
              取消
            </button>
            <button type="submit" className="primaryAction" disabled={busy}>
              {busy ? <RefreshCw size={16} className="spinIcon" /> : <FileSearch size={16} />}
              {createdDraft ? "继续上传资料" : "创建草稿并上传"}
            </button>
            <button
              type="button"
              className="primaryAction"
              disabled={busy || buildBusy || buildIsRunning || hasPendingLocalUploads || hasParsingFiles}
              onClick={() => void startBuild()}
            >
              {buildBusy || buildIsRunning ? <RefreshCw size={16} className="spinIcon" /> : <FileSearch size={16} />}
              {buildFailed ? "重新生成" : buildSucceeded ? "已创建完成" : "开始生成分身"}
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}
