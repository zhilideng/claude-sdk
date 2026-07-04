"""本地项目路径安全工具。"""
from dataclasses import dataclass
from pathlib import Path

from app.exceptions import BizValidationError

SKIP_DIR_NAMES = {".git", "node_modules", "__pycache__", ".venv", "dist", "build", ".next"}


@dataclass(frozen=True)
class ProjectScanSummary:
    """项目浅层扫描摘要。"""

    is_git_repo: bool
    file_count: int
    dir_count: int
    file_samples: list[str]


def resolve_project_path(input_path: str) -> Path:
    """解析并归一化用户输入的项目根路径。"""
    raw_path = input_path.strip()
    if not raw_path:
        raise BizValidationError("本地路径不能为空")

    path_input = Path(raw_path).expanduser()
    if not path_input.is_absolute():
        raise BizValidationError("本地路径必须是绝对路径")

    path = path_input.resolve()
    if not path.exists():
        raise BizValidationError("本地路径不存在")
    if not path.is_dir():
        raise BizValidationError("本地路径必须是文件夹")
    return path


def ensure_allowed_root(path: Path, allowed_roots: list[str]) -> None:
    """确认项目路径位于允许根目录内。"""
    roots = [Path(root).expanduser().resolve() for root in allowed_roots if root.strip()]
    if not roots:
        raise BizValidationError("未配置允许导入的本地根目录")

    for root in roots:
        if path == root or root in path.parents:
            return
    raise BizValidationError("本地路径不在允许导入的目录内")


def ensure_relative_path(root: Path, relative_path: str) -> Path:
    """把相对路径限定在项目根目录内，防止路径逃逸。"""
    if not relative_path.strip():
        raise BizValidationError("文件路径不能为空")

    resolved = (root / relative_path).resolve()
    if resolved != root and root not in resolved.parents:
        raise BizValidationError("文件路径越过项目根目录")
    return resolved


def scan_project_summary(
    path: Path,
    *,
    max_files: int,
    max_samples: int,
) -> ProjectScanSummary:
    """扫描项目摘要，跳过常见大目录。"""
    file_count = 0
    dir_count = 0
    samples: list[str] = []

    for item in path.rglob("*"):
        relative_parts = item.relative_to(path).parts
        if any(part in SKIP_DIR_NAMES for part in relative_parts):
            if item.is_dir():
                continue
            continue

        if item.is_dir():
            dir_count += 1
            continue

        if item.is_file():
            file_count += 1
            if len(samples) < max_samples:
                samples.append(item.relative_to(path).as_posix())
            if file_count >= max_files:
                break

    return ProjectScanSummary(
        is_git_repo=(path / ".git").exists(),
        file_count=file_count,
        dir_count=dir_count,
        file_samples=samples,
    )
