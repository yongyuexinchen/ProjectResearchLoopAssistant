import json
import re
from pathlib import Path
from os import walk
from typing import Any

from app.tools.file_tools import read_text_excerpt
from app.tools.path_policy import should_skip_path, to_relative_posix


MANIFEST_FILE_NAMES = {"go.mod", "package.json", "pom.xml", "pyproject.toml", "requirements.txt"}
MANIFEST_EXCERPT_CHARS = 20_000

# 依赖名 -> 报告使用的技术栈标签。只做名称匹配，不访问网络，也不解析版本。
FRAMEWORK_ALIASES = {
    "fastapi": "fastapi",
    "flask": "flask",
    "django": "django",
    "starlette": "starlette",
    "langgraph": "langgraph",
    "langchain": "langchain",
    "langchain-core": "langchain",
    "sqlalchemy": "sqlalchemy",
    "pydantic": "pydantic",
    "pytest": "pytest",
    "next": "nextjs",
    "react": "react",
    "vue": "vue",
    "express": "express",
    "mermaid": "mermaid",
    "pymysql": "mysql",
    "mysqlclient": "mysql",
    "mysql-connector-python": "mysql",
    "redis": "redis",
    "celery": "celery",
}

DEPENDENCY_FILE_NAMES = {
    "go.mod",
    "package-lock.json",
    "package.json",
    "pom.xml",
    "pyproject.toml",
    "requirements.txt",
    "uv.lock",
}
CONFIG_FILE_NAMES = {
    "docker-compose.yml",
    "Dockerfile",
    "eslint.config.js",
    "next.config.js",
    "next.config.mjs",
    "next.config.ts",
    "pytest.ini",
    "tsconfig.json",
}
ENTRYPOINT_FILE_NAMES = {
    "app.py",
    "main.py",
    "server.py",
    "manage.py",
    "index.js",
    "index.jsx",
    "index.ts",
    "index.tsx",
    "main.js",
    "main.jsx",
    "main.ts",
    "main.tsx",
    "server.js",
    "server.ts",
    "server.mjs",
}
ENTRYPOINT_RELATIVE_PATHS = {
    "app/main.py",
    "manage.py",
    "src/index.js",
    "src/index.jsx",
    "src/index.ts",
    "src/index.tsx",
    "src/main.js",
    "src/main.jsx",
    "src/main.ts",
    "src/main.tsx",
    "src/server.js",
    "src/server.ts",
    "server.js",
    "server.ts",
    "app/page.tsx",
    "app/layout.tsx",
    "src/app/page.tsx",
    "src/app/layout.tsx",
    "pages/_app.tsx",
    "src/pages/_app.tsx",
    "pages/index.tsx",
    "src/pages/index.tsx",
    "src/App.tsx",
    "src/App.jsx",
}

CODE_EXTENSIONS = {
    ".c",
    ".cc",
    ".cpp",
    ".cs",
    ".go",
    ".java",
    ".js",
    ".jsx",
    ".kt",
    ".mjs",
    ".php",
    ".py",
    ".rb",
    ".rs",
    ".svelte",
    ".swift",
    ".ts",
    ".tsx",
    ".vue",
}
NON_CODE_PATH_PARTS = {
    "__pycache__",
    ".next",
    ".nuxt",
    ".svelte-kit",
    "assets",
    "coverage",
    "dist",
    "doc",
    "docs",
    "node_modules",
    "public",
    "scratch",
    "static",
    "target",
    "third_party",
    "vendor",
}
STACK_SKIP_PARTS = {
    ".github",
    "doc",
    "docs",
    "example",
    "examples",
    "hack",
    "test",
    "testdata",
    "tests",
    "third_party",
    "vendor",
}
SCRIPT_ENTRY_RE = re.compile(
    r"(?:^|\s)(?:node|nodemon|tsx|ts-node|next|vite)\s+(?:--?\S+\s+)*([\w./-]+\.(?:[cm]?[jt]sx?))"
)
ENTRYPOINT_SKIP_PARTS = {
    "docs",
    "doc",
    "examples",
    "hack",
    "staging",
    "test",
    "tests",
    "third_party",
    "vendor",
}


def infer_entrypoints(file_paths: set[str] | list[str], tech_stack: set[str] | list[str]) -> list[str]:
    """从文件树和框架名称推断入口；兼容旧扫描结果，不重新读取文件。"""

    paths = {str(path).replace("\\", "/").lstrip("./") for path in file_paths}
    stack = {str(item).lower() for item in tech_stack}
    candidates: list[str] = []

    if "nextjs" in stack or "next" in stack or any(path.endswith(("app/page.tsx", "app/layout.tsx")) for path in paths):
        candidates.extend(
            [
                "src/app/layout.tsx",
                "app/layout.tsx",
                "src/app/page.tsx",
                "app/page.tsx",
                "src/pages/_app.tsx",
                "pages/_app.tsx",
                "src/pages/index.tsx",
                "pages/index.tsx",
                "src/app/page.ts",
                "app/page.ts",
                "src/app/layout.ts",
                "app/layout.ts",
            ]
        )
    if stack & {"react", "vue", "typescript", "javascript"}:
        candidates.extend(
            [
                "src/main.tsx",
                "src/main.jsx",
                "src/index.tsx",
                "src/index.jsx",
                "src/App.tsx",
                "src/App.jsx",
                "src/main.ts",
                "src/main.js",
                "src/index.ts",
                "src/index.js",
            ]
        )
    if stack & {"express", "javascript", "typescript"}:
        candidates.extend(
            [
                "src/server.ts",
                "src/server.js",
                "server.ts",
                "server.js",
                "src/index.ts",
                "src/index.js",
                "index.ts",
                "index.js",
            ]
        )
    candidates.extend(
        [
            "app/main.py",
            "app.py",
            "main.py",
            "manage.py",
            "server.py",
            "src/index.ts",
            "src/index.tsx",
            "src/index.js",
            "src/index.jsx",
            "src/main.ts",
            "src/main.tsx",
            "src/main.js",
            "src/main.jsx",
        ]
    )
    cmd_priority = (
        "kube-apiserver",
        "kube-controller-manager",
        "kube-scheduler",
        "kubelet",
        "kube-proxy",
        "kubectl",
        "kubeadm",
    )
    cmd_candidates = [
        path
        for path in paths
        if path.startswith("cmd/")
        and path.endswith(".go")
        and not path.endswith("_test.go")
        and (
            path.endswith("/main.go")
            or (
                path.count("/") == 2
                and path.rsplit("/", maxsplit=1)[-1].removesuffix(".go")
                in {
                    path.split("/")[1],
                    path.split("/")[1].replace("-", "_"),
                    path.split("/")[1].split("-")[-1],
                }
            )
        )
    ]
    cmd_candidates.sort(
        key=lambda path: (
            0 if any(f"cmd/{name}/" in path for name in cmd_priority) else 1,
            path,
        )
    )
    candidates.extend(cmd_candidates[:10])
    return unique_values(path for path in candidates if path in paths)


def detect_stack(relative_path: str) -> set[str]:
    lowered = relative_path.lower()
    stack: set[str] = set()
    if lowered.endswith(".py") or lowered.endswith("pyproject.toml") or lowered.endswith("requirements.txt"):
        stack.add("python")
    if lowered.endswith((".ts", ".tsx")) or lowered.endswith("tsconfig.json"):
        stack.add("typescript")
    if lowered.endswith((".js", ".jsx")) or lowered.endswith("package.json"):
        stack.add("javascript")
    if lowered.endswith("go.mod") or lowered.endswith(".go"):
        stack.add("go")
    if lowered.endswith("pom.xml") or lowered.endswith(".java"):
        stack.add("java")
    return stack


def is_test_file(relative_path: str) -> bool:
    lowered = relative_path.lower()
    parts = lowered.split("/")
    name = parts[-1]
    return (
        "tests" in parts
        or "test" in parts
        or name.startswith("test_")
        or name.endswith("_test.py")
        or name.endswith("_test.go")
        or ".test." in name
        or ".spec." in name
    )


def is_source_code_path(relative_path: str) -> bool:
    """判断路径是否是源代码文件，排除图片、缓存、构建产物和静态资源。"""

    lowered = relative_path.replace("\\", "/").lower()
    parts = lowered.split("/")
    if any(part in NON_CODE_PATH_PARTS for part in parts):
        return False
    return Path(lowered).suffix in CODE_EXTENSIONS


def is_core_code_path(relative_path: str) -> bool:
    return is_source_code_path(relative_path) and not is_test_file(relative_path)


def is_valid_entrypoint_path(relative_path: str) -> bool:
    parts = {part.lower() for part in str(relative_path).replace("\\", "/").split("/")}
    return not (parts & ENTRYPOINT_SKIP_PARTS)


def unique_values(values) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        item = str(value).strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def normalize_dependency_name(value: str) -> str:
    name = value.strip().lower()
    name = re.split(r"[\s<>=!~;\[\]()@]", name, maxsplit=1)[0]
    return name.strip().strip("\"',")


def detect_frameworks(dependencies: list[str]) -> set[str]:
    detected: set[str] = set()
    for dependency in dependencies:
        normalized = normalize_dependency_name(dependency)
        alias = FRAMEWORK_ALIASES.get(normalized)
        if alias:
            detected.add(alias)
    return detected


def dominant_stack(file_tree: Any, threshold: int = 3) -> list[str]:
    """按核心源码文件数量判断主语言，避免一两个脚本把技术栈带偏。"""

    counts: dict[str, int] = {}
    total_files = 0
    for item in as_list(file_tree):
        path = str(value_of(item, "path", item))
        if value_of(item, "kind", "file") != "file":
            continue
        if not is_core_code_path(path):
            continue
        total_files += 1
        for tag in detect_stack(path):
            counts[tag] = counts.get(tag, 0) + 1
    effective_threshold = max(threshold, int(total_files * 0.1))
    return sorted(tag for tag, count in counts.items() if count >= effective_threshold)


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, (str, bytes, dict)):
        return [value]
    try:
        return list(value)
    except TypeError:
        return [value]


def value_of(item: Any, key: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def extract_manifest(relative_path: str, file_path: Path) -> dict | None:
    """读取依赖清单中的名称、描述和依赖名；解析失败时返回 None，不影响扫描。"""

    try:
        content = read_text_excerpt(file_path, MANIFEST_EXCERPT_CHARS)
    except OSError:
        return None

    name = file_path.name
    manifest: dict = {"path": relative_path, "description": "", "keywords": [], "dependencies": []}
    try:
        if name == "package.json":
            payload = json.loads(content)
            if isinstance(payload, dict):
                manifest["name"] = str(payload.get("name") or "")
                manifest["description"] = str(payload.get("description") or "")
                keywords = payload.get("keywords")
                if isinstance(keywords, list):
                    manifest["keywords"] = [str(item) for item in keywords if isinstance(item, (str, int, float))]
                for section in ("dependencies", "devDependencies", "peerDependencies"):
                    dependencies = payload.get(section)
                    if isinstance(dependencies, dict):
                        manifest["dependencies"].extend(str(key) for key in dependencies)
                scripts = payload.get("scripts")
                if isinstance(scripts, dict):
                    manifest["scripts"] = [str(key) for key in scripts]
                    script_entrypoints: list[str] = []
                    for command in scripts.values():
                        if not isinstance(command, str):
                            continue
                        for match in SCRIPT_ENTRY_RE.finditer(command):
                            script_entrypoints.append(match.group(1).replace("\\", "/"))
                    manifest["entrypoints"] = unique_values(script_entrypoints)
        elif name == "pyproject.toml":
            import tomllib

            payload = tomllib.loads(content)
            project = payload.get("project") if isinstance(payload, dict) else None
            poetry = ((payload.get("tool") or {}).get("poetry") if isinstance(payload, dict) else None)
            if isinstance(project, dict):
                manifest["name"] = str(project.get("name") or "")
                manifest["description"] = str(project.get("description") or "")
                keywords = project.get("keywords")
                if isinstance(keywords, list):
                    manifest["keywords"] = [str(item) for item in keywords]
                dependencies = project.get("dependencies")
                if isinstance(dependencies, list):
                    manifest["dependencies"].extend(str(item) for item in dependencies)
            if isinstance(poetry, dict):
                manifest["name"] = manifest.get("name") or str(poetry.get("name") or "")
                manifest["description"] = manifest.get("description") or str(poetry.get("description") or "")
                dependencies = poetry.get("dependencies")
                if isinstance(dependencies, dict):
                    manifest["dependencies"].extend(str(key) for key in dependencies)
        elif name == "requirements.txt":
            manifest["dependencies"].extend(
                line.strip()
                for line in content.splitlines()
                if line.strip() and not line.strip().startswith(("#", "-", "git+"))
            )
        elif name == "go.mod":
            module_match = re.search(r"^module\s+(\S+)", content, flags=re.MULTILINE)
            if module_match:
                manifest["name"] = module_match.group(1)
            manifest["dependencies"].extend(
                match.group(1)
                for match in re.finditer(r"^\s*([\w.\-/]+)\s+v[\w.\-+]+", content, flags=re.MULTILINE)
            )
        elif name == "pom.xml":
            artifact = re.search(r"<artifactId>([^<]+)</artifactId>", content)
            description = re.search(r"<description>([^<]+)</description>", content)
            if artifact:
                manifest["name"] = artifact.group(1).strip()
            if description:
                manifest["description"] = description.group(1).strip()
    except Exception:
        return None

    manifest["dependencies"] = sorted({dep for dep in manifest["dependencies"] if dep})
    if not (manifest.get("name") or manifest.get("description") or manifest["dependencies"]):
        return None
    return manifest



def scan_codebase(root: Path, max_file_bytes: int, excerpt_chars: int,
                  *, excluded_roots: list[Path] | None = None) -> dict:
    """扫描代码目录的结构线索；不执行脚本，不跟随 symlink。"""

    root = root.resolve()
    excluded = {path.resolve() for path in (excluded_roots or [])
                if path.resolve() != root and path.resolve().is_relative_to(root)}
    tech_stack: set[str] = set()
    dependency_files: list[str] = []
    config_files: list[str] = []
    test_files: list[str] = []
    entrypoint_files: list[str] = []
    file_tree: list[dict] = []
    skipped_items: list[dict] = []
    readme_excerpt: str | None = None
    manifests: list[dict] = []
    manifest_dependencies: list[str] = []
    manifest_entrypoints: list[str] = []

    for current_root_raw, dir_names, file_names in walk(root, topdown=True, followlinks=False):
        current_root = Path(current_root_raw)
        kept_dir_names: list[str] = []
        for dir_name in sorted(dir_names):
            dir_path = current_root / dir_name
            if dir_path.resolve() in excluded:
                skipped_items.append({"path": to_relative_posix(dir_path, root), "reason": "runtime_workspace"})
                continue
            decision = should_skip_path(dir_path, root, max_file_bytes)
            if decision is not None:
                skipped_items.append(decision)
                continue
            kept_dir_names.append(dir_name)
            file_tree.append({"path": to_relative_posix(dir_path, root), "kind": "directory"})
        dir_names[:] = kept_dir_names

        for file_name in sorted(file_names):
            file_path = current_root / file_name
            decision = should_skip_path(file_path, root, max_file_bytes)
            if decision is not None:
                skipped_items.append(decision)
                continue

            relative_path = to_relative_posix(file_path, root)
            lowered_name = file_name.lower()
            file_tree.append(
                {
                    "path": relative_path,
                    "kind": "file",
                    "size_bytes": file_path.stat().st_size,
                }
            )
            path_parts = {part.lower() for part in relative_path.split("/")}
            if not (path_parts & STACK_SKIP_PARTS) and not is_test_file(relative_path):
                tech_stack.update(detect_stack(relative_path))

            if file_name in DEPENDENCY_FILE_NAMES:
                dependency_files.append(relative_path)
            if file_name in MANIFEST_FILE_NAMES:
                manifest = extract_manifest(relative_path, file_path)
                if manifest is not None:
                    manifests.append(manifest)
                    manifest_dependencies.extend(manifest["dependencies"])
                    manifest_entrypoints.extend(manifest.get("entrypoints", []))
            if file_name in CONFIG_FILE_NAMES:
                config_files.append(relative_path)
            if is_test_file(relative_path):
                test_files.append(relative_path)
            if (
                file_name in ENTRYPOINT_FILE_NAMES or relative_path in ENTRYPOINT_RELATIVE_PATHS
            ) and not (path_parts & ENTRYPOINT_SKIP_PARTS):
                entrypoint_files.append(relative_path)
            if readme_excerpt is None and lowered_name.startswith("readme"):
                readme_excerpt = read_text_excerpt(file_path, excerpt_chars)

    file_paths = {item["path"] for item in file_tree if item["kind"] == "file"}
    detected_frameworks = detect_frameworks(manifest_dependencies)
    detected_stack = tech_stack | detected_frameworks
    entrypoint_files.extend(path for path in manifest_entrypoints if path in file_paths)
    entrypoint_files.extend(infer_entrypoints(file_paths, detected_stack))

    return {
        "root_label": root.name,
        "tech_stack": sorted(detected_stack),
        "dependency_files": sorted(dependency_files),
        "config_files": sorted(config_files),
        "test_files": sorted(test_files),
        "entrypoint_files": sorted(unique_values(entrypoint_files)),
        "readme_excerpt": readme_excerpt,
        "file_tree": file_tree,
        "skipped_items": skipped_items,
        "metadata": {
            "root_path": str(root),
            "total_files": sum(1 for item in file_tree if item["kind"] == "file"),
            "total_directories": sum(1 for item in file_tree if item["kind"] == "directory"),
            "manifests": manifests,
        },
    }
