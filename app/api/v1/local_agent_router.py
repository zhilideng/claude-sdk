"""本地工具中继 API 路由（v1）。"""

from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi import APIRouter, Query
from fastapi.responses import Response

from app.exceptions import BizValidationError
from app.schemas.local_agent import (
    LocalAgentPollIn,
    LocalAgentTaskCompleteIn,
    LocalAgentTaskCreateIn,
)
from app.services.local_agent_service import get_local_agent_hub
from app.utils.common import ApiResponse

router = APIRouter(prefix="/local-agent", tags=["local-agent"])

LOCAL_AGENT_SCRIPT_NAMES = (
    "local_tool_agent.py",
    "run_local_tool_agent.sh",
    "run_local_tool_agent.bat",
    "run_local_tool_agent.ps1",
)
LOCAL_AGENT_BINARY_PLATFORMS = {
    "linux-x64",
    "macos-arm64",
    "macos-x64",
    "windows-x64",
}
LOCAL_AGENT_DIST_DIR = Path(__file__).resolve().parents[3] / "dist" / "local-agent"
LOCAL_AGENT_INSTALL_SCRIPT = r'''#!/usr/bin/env sh
set -eu

SERVER_URL="${1:-}"
if [ -z "$SERVER_URL" ]; then
  echo "Usage: $0 <claude-sdk-server-url> [agent-name]" >&2
  exit 2
fi
AGENT_NAME="${2:-local-agent}"

detect_platform() {
  os="$(uname -s 2>/dev/null | tr '[:upper:]' '[:lower:]')"
  arch="$(uname -m 2>/dev/null | tr '[:upper:]' '[:lower:]')"
  case "$os" in
    linux*) os_tag="linux" ;;
    darwin*) os_tag="macos" ;;
    mingw*|msys*|cygwin*) os_tag="windows" ;;
    *) echo "Unsupported OS: $os" >&2; exit 1 ;;
  esac
  case "$arch" in
    x86_64|amd64) arch_tag="x64" ;;
    arm64|aarch64)
      if [ "$os_tag" = "linux" ]; then
        echo "Unsupported arch for MVP: $os_tag-$arch" >&2
        exit 1
      fi
      arch_tag="arm64"
      ;;
    *) echo "Unsupported arch: $arch" >&2; exit 1 ;;
  esac
  echo "$os_tag-$arch_tag"
}

download_file() {
  url="$1"
  output="$2"
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL "$url" -o "$output"
    return
  fi
  if command -v wget >/dev/null 2>&1; then
    wget -q "$url" -O "$output"
    return
  fi
  echo "curl or wget is required to download claude-sdk local agent" >&2
  exit 1
}

platform="$(detect_platform)"
case "$platform" in
  windows-*) exe_name="claude-sdk-local-agent.exe" ;;
  *) exe_name="claude-sdk-local-agent" ;;
esac

install_dir="${CLAUDE_SDK_LOCAL_AGENT_HOME:-$HOME/.claude-sdk/local-agent}"
mkdir -p "$install_dir"
binary_path="$install_dir/$exe_name"
download_url="${SERVER_URL%/}/v1/local-agent/binary?platform=$platform"

echo "Downloading claude-sdk local agent for $platform..."
download_file "$download_url" "$binary_path"
chmod +x "$binary_path" 2>/dev/null || true
echo "Starting claude-sdk local agent..."
exec "$binary_path" --server "$SERVER_URL" --agent-name "$AGENT_NAME"
'''


def build_local_agent_source_bundle() -> bytes:
    """打包供最终用户下载到本机执行的连接器脚本。"""
    scripts_dir = Path(__file__).resolve().parents[3] / "scripts"
    buffer = BytesIO()
    with ZipFile(buffer, mode="w", compression=ZIP_DEFLATED) as bundle:
        for script_name in LOCAL_AGENT_SCRIPT_NAMES:
            script_path = scripts_dir / script_name
            bundle.write(script_path, arcname=script_name)
    return buffer.getvalue()


def read_local_agent_binary_bundle(platform: str) -> bytes:
    """读取部署时预构建的平台二进制包。"""
    if platform not in LOCAL_AGENT_BINARY_PLATFORMS:
        raise BizValidationError("不支持的本地连接器平台")

    artifact_path = LOCAL_AGENT_DIST_DIR / f"claude-sdk-local-agent-{platform}.zip"
    if not artifact_path.exists():
        raise BizValidationError(
            f"本地连接器二进制包尚未构建: {artifact_path.name}"
        )
    return artifact_path.read_bytes()


def read_local_agent_raw_binary(platform: str) -> tuple[str, bytes]:
    """读取供 install.sh 直接下载的 raw executable。"""
    if platform not in LOCAL_AGENT_BINARY_PLATFORMS:
        raise BizValidationError("不支持的本地连接器平台")

    suffix = ".exe" if platform.startswith("windows") else ""
    filename = f"claude-sdk-local-agent-{platform}{suffix}"
    artifact_path = LOCAL_AGENT_DIST_DIR / filename
    if not artifact_path.exists():
        raise BizValidationError(
            f"本地连接器二进制文件尚未构建: {filename}"
        )
    return filename, artifact_path.read_bytes()


@router.get("/install.sh")
async def download_local_agent_install_script() -> Response:
    """下载最终用户只需执行一次的 shell bootstrap 脚本。"""
    return Response(
        content=LOCAL_AGENT_INSTALL_SCRIPT,
        media_type="text/x-shellscript; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="claude-sdk-local-agent.sh"',
        },
    )


@router.get("/binary")
async def download_local_agent_binary(
    platform: str = Query(..., description="预构建平台：linux-x64/macos-arm64/macos-x64/windows-x64"),
) -> Response:
    """下载免 Python 的 raw executable，供 install.sh 直接落盘启动。"""
    filename, content = read_local_agent_raw_binary(platform)
    return Response(
        content=content,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@router.get("/download")
async def download_local_agent_bundle(
    platform: str = Query(
        "source",
        description="source 或预构建平台：linux-x64/macos-arm64/macos-x64/windows-x64",
    ),
) -> Response:
    """下载用户本机运行的跨平台本地工具连接器脚本包。"""
    if platform == "source":
        filename = "claude-sdk-local-agent-source.zip"
        content = build_local_agent_source_bundle()
    else:
        filename = f"claude-sdk-local-agent-{platform}.zip"
        content = read_local_agent_binary_bundle(platform)

    return Response(
        content=content,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@router.post("/tasks")
async def create_local_agent_task(payload: LocalAgentTaskCreateIn) -> dict:
    """创建一个等待用户本机脚本执行的任务。"""
    task = await get_local_agent_hub().create_task(payload)
    return ApiResponse.ok(task).to_payload()


@router.get("/tasks/{task_id}")
async def get_local_agent_task(task_id: str) -> dict:
    """查询本地执行任务状态与结果。"""
    task = await get_local_agent_hub().get_task(task_id)
    return ApiResponse.ok(task).to_payload()


@router.post("/tasks/{task_id}/wait")
async def wait_local_agent_task(
    task_id: str,
    timeout_seconds: float = Query(30.0, gt=0, le=3600),
) -> dict:
    """等待本地执行任务完成，便于服务端 agent 同步拿到工具结果。"""
    task = await get_local_agent_hub().wait_task(task_id, timeout_seconds)
    return ApiResponse.ok(task).to_payload()


@router.get("/agents")
async def list_local_agents() -> dict:
    """查询本地脚本实例最近心跳状态。"""
    data = await get_local_agent_hub().list_agents()
    return ApiResponse.ok(data).to_payload()


@router.post("/poll")
async def poll_local_agent_task(payload: LocalAgentPollIn) -> dict:
    """本地脚本轮询一个待执行任务。"""
    data = await get_local_agent_hub().poll(payload.agent_name)
    return ApiResponse.ok(data).to_payload()


@router.post("/tasks/{task_id}/complete")
async def complete_local_agent_task(
    task_id: str,
    payload: LocalAgentTaskCompleteIn,
) -> dict:
    """本地脚本回传任务执行结果。"""
    task = await get_local_agent_hub().complete_task(task_id, payload)
    return ApiResponse.ok(task).to_payload()
