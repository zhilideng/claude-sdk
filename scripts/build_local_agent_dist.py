"""构建本地连接器分发包。

源码包用于开发调试或用户已安装 Python 的场景；二进制包用于最终用户
无需本机 Python 环境即可运行。二进制包依赖 PyInstaller，需在目标平台
或 CI 矩阵中分别构建。
"""

from __future__ import annotations

import argparse
import os
import platform
import subprocess
import sys
import tempfile
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "dist" / "local-agent"
SOURCE_BUNDLE_FILES = (
    "local_tool_agent.py",
    "run_local_tool_agent.sh",
    "run_local_tool_agent.bat",
    "run_local_tool_agent.ps1",
)
SUPPORTED_PLATFORM_TAGS = {
    "linux-x64",
    "macos-arm64",
    "macos-x64",
    "windows-x64",
}


def detect_platform_tag() -> str:
    """识别当前构建机器的平台标签。"""
    system = platform.system().lower()
    machine = platform.machine().lower()
    if system == "linux" and machine in {"x86_64", "amd64"}:
        return "linux-x64"
    if system == "darwin" and machine in {"arm64", "aarch64"}:
        return "macos-arm64"
    if system == "darwin" and machine in {"x86_64", "amd64"}:
        return "macos-x64"
    if system == "windows" and machine in {"amd64", "x86_64"}:
        return "windows-x64"
    raise RuntimeError(f"不支持的构建平台: system={system}, machine={machine}")


def build_source_bundle(output_dir: Path = DEFAULT_OUTPUT_DIR) -> Path:
    """构建需要 Python 运行时的源码脚本包。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = output_dir / "claude-sdk-local-agent-source.zip"
    with ZipFile(bundle_path, mode="w", compression=ZIP_DEFLATED) as bundle:
        for file_name in SOURCE_BUNDLE_FILES:
            bundle.write(SCRIPTS_DIR / file_name, arcname=file_name)
    return bundle_path


def binary_artifact_name(platform_tag: str) -> str:
    """返回平台 raw binary 文件名。"""
    suffix = ".exe" if platform_tag.startswith("windows") else ""
    return f"claude-sdk-local-agent-{platform_tag}{suffix}"


def executable_archive_name(platform_tag: str) -> str:
    """返回压缩包内可执行文件名。"""
    return "claude-sdk-local-agent.exe" if platform_tag.startswith("windows") else "claude-sdk-local-agent"


def build_binary_zip(
    output_dir: Path,
    *,
    platform_tag: str,
    executable_path: Path,
) -> Path:
    """把 PyInstaller 产物整理为 raw executable 与 zip 两种分发形态。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_binary_path = output_dir / binary_artifact_name(platform_tag)
    raw_binary_path.write_bytes(executable_path.read_bytes())
    try:
        raw_binary_path.chmod(executable_path.stat().st_mode)
    except OSError:
        pass

    executable_name = executable_archive_name(platform_tag)
    bundle_path = output_dir / f"claude-sdk-local-agent-{platform_tag}.zip"
    with ZipFile(bundle_path, mode="w", compression=ZIP_DEFLATED) as bundle:
        bundle.write(raw_binary_path, arcname=executable_name)
        bundle.writestr(
            "README.txt",
            "\n".join(
                [
                    "claude-sdk local agent",
                    "",
                    "Run:",
                    f"./{executable_name} --server http://<claude-sdk-server>",
                    "",
                    "Windows users can run the .exe from CMD or PowerShell.",
                ]
            ),
        )
    return bundle_path


def ensure_pyinstaller_available() -> None:
    """确认当前 Python 环境可用 PyInstaller。"""
    result = subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "当前环境未安装 PyInstaller，请先执行: "
            f"{sys.executable} -m pip install -r requirements-local-agent-build.txt"
        )


def build_binary_bundle(
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    *,
    platform_tag: str | None = None,
) -> Path:
    """构建当前平台可执行文件包。"""
    tag = platform_tag or detect_platform_tag()
    if tag not in SUPPORTED_PLATFORM_TAGS:
        raise RuntimeError(f"不支持的平台标签: {tag}")
    ensure_pyinstaller_available()

    output_dir.mkdir(parents=True, exist_ok=True)
    executable_name = executable_archive_name(tag)

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        dist_path = temp_path / "dist"
        work_path = temp_path / "build"
        spec_path = temp_path / "spec"
        env = os.environ.copy()
        env["PYINSTALLER_CONFIG_DIR"] = str(temp_path / "pyinstaller-config")
        subprocess.run(
            [
                sys.executable,
                "-m",
                "PyInstaller",
                "--onefile",
                "--clean",
                "--name",
                executable_name,
                "--distpath",
                str(dist_path),
                "--workpath",
                str(work_path),
                "--specpath",
                str(spec_path),
                str(SCRIPTS_DIR / "local_tool_agent.py"),
            ],
            cwd=REPO_ROOT,
            env=env,
            check=True,
        )
        executable_path = dist_path / executable_name
        if not executable_path.exists():
            raise RuntimeError(f"未找到 PyInstaller 产物: {executable_path}")

        return build_binary_zip(output_dir, platform_tag=tag, executable_path=executable_path)


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(description="构建 claude-sdk 本地连接器分发包")
    parser.add_argument(
        "--mode",
        choices=["source", "binary", "all"],
        default="source",
        help="source=源码包，binary=当前平台二进制包，all=两者都构建",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="输出目录，默认 dist/local-agent",
    )
    parser.add_argument(
        "--platform-tag",
        choices=sorted(SUPPORTED_PLATFORM_TAGS),
        default=None,
        help="二进制包平台标签；通常由构建机自动识别",
    )
    return parser.parse_args()


def main() -> None:
    """脚本入口。"""
    args = parse_args()
    outputs: list[Path] = []
    if args.mode in {"source", "all"}:
        outputs.append(build_source_bundle(args.output_dir))
    if args.mode in {"binary", "all"}:
        outputs.append(build_binary_bundle(args.output_dir, platform_tag=args.platform_tag))

    for output in outputs:
        print(output)


if __name__ == "__main__":
    main()
