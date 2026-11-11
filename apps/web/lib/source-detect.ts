export type SourceType = "local_directory" | "github_repo" | "web_url" | "local_file";

const WINDOWS_PATH_RE = /^(?:[a-zA-Z]:[\\/]|\\\\)/;
const POSIX_PATH_RE = /^(?:\/|\.{1,2}[\\/]|~[\\/])/;

export function detectSourceType(value: string): SourceType | null {
  const trimmed = value.trim();
  if (!trimmed) return null;

  if (/^https?:\/\//i.test(trimmed)) {
    try {
      const url = new URL(trimmed);
      const segments = url.pathname.split("/").filter(Boolean);
      if (url.hostname.toLowerCase() === "github.com" && segments.length === 2) {
        return "github_repo";
      }
      return "web_url";
    } catch {
      return null;
    }
  }

  if (WINDOWS_PATH_RE.test(trimmed) || POSIX_PATH_RE.test(trimmed)) {
    return "local_directory";
  }
  return null;
}

export function sourceTypeMismatch(sourceType: SourceType, value: string): string | null {
  const trimmed = value.trim();
  if (!trimmed) return null;

  const isUrl = /^https?:\/\//i.test(trimmed);
  const isLocalPath = WINDOWS_PATH_RE.test(trimmed) || POSIX_PATH_RE.test(trimmed);
  if (sourceType.startsWith("local_") && isUrl) {
    return "这是网页或仓库链接，不是本地路径。请把资料类型改为「GitHub 仓库」或「网页链接」。";
  }
  if (!sourceType.startsWith("local_") && isLocalPath) {
    return "这是本地路径。请把资料类型改为「本地项目目录」或「本地文档文件」。";
  }
  return null;
}
