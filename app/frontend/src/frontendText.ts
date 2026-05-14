import type { PersonaCatalogCard, UserPersonaFileItem } from "./types";

export const USER_PERSONA_SUPPORTED_EXTENSIONS = [
  "pdf",
  "docx",
  "doc",
  "pptx",
  "ppt",
  "xlsx",
  "xls",
  "csv",
  "tsv",
  "txt",
  "md",
  "html",
  "htm",
  "rtf",
  "png",
  "jpg",
  "jpeg",
  "webp",
  "tif",
  "tiff",
  "bmp",
  "py",
  "js",
  "ts",
  "tsx",
  "jsx",
  "java",
  "cpp",
  "c",
  "h",
  "cs",
  "go",
  "rs",
  "php",
  "rb",
  "swift",
  "kt",
  "sql",
  "json",
  "jsonl",
  "yaml",
  "yml",
  "xml",
  "ini",
  "toml",
  "log"
];

export const USER_PERSONA_MAX_FILES = 20;
export const USER_PERSONA_MAX_FILE_SIZE = 50 * 1024 * 1024;

export function personaRuntimeStatusLabel(status: PersonaCatalogCard["runtime_status"]) {
  if (status === "ready") return "可对话";
  if (status === "building") return "构建中";
  if (status === "error") return "需修复";
  return "草稿";
}

export function parseStatusLabel(status: UserPersonaFileItem["parse_status"] | string) {
  if (status === "parsed") return "解析完成";
  if (status === "parsed_low_quality") return "解析完成，需复查";
  if (status === "needs_ocr_backend") return "需要 OCR/VLM";
  if (status === "ocr_parsing") return "OCR/VLM 解析中";
  if (status === "parsing") return "解析中";
  if (status === "queued") return "等待解析";
  if (status === "failed") return "解析失败";
  return status || "未知";
}

export function formatBytes(value: number) {
  if (value >= 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)} MB`;
  if (value >= 1024) return `${(value / 1024).toFixed(1)} kB`;
  return `${value} B`;
}

export function shortPersonaDescription(description: string, fallback = "用户创建的虚拟分身") {
  const trimmed = description.trim();
  if (!trimmed) return fallback;
  const first = trimmed.split(/[。！？!?]/)[0]?.trim();
  const value = first || trimmed;
  return value.length > 54 ? `${value.slice(0, 53)}...` : value;
}
