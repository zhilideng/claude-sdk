"""用户本机轻量工具中继脚本。

脚本不运行 LLM，也不持有 Claude Code SDK。它只从远端服务轮询任务，
在用户电脑的 ``root_path`` 下执行动作，并把结果回传给服务端。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path
from typing import Any
from urllib import error, request


def resolve_root_path(root_path: str) -> Path:
    """解析任务根目录，确保它在用户本机存在。"""
    path = Path(root_path).expanduser().resolve()
    if not path.exists():
        raise ValueError(f"root_path 不存在: {path}")
    if not path.is_dir():
        raise ValueError(f"root_path 不是文件夹: {path}")
    return path


def resolve_payload_path(root: Path, payload: dict[str, Any]) -> Path:
    """把动作 payload 中的 path 解析到 root_path 内。"""
    raw_path = str(payload.get("path") or "").strip()
    if not raw_path:
        raise ValueError("payload.path 不能为空")

    path = Path(raw_path).expanduser()
    resolved = path.resolve() if path.is_absolute() else (root / path).resolve()
    if resolved != root and root not in resolved.parents:
        raise ValueError("payload.path 越过 root_path")
    return resolved


def execute_local_task(task: dict[str, Any]) -> dict[str, Any]:
    """执行单个本地任务并返回可直接回传服务端的结果。"""
    try:
        root = resolve_root_path(str(task.get("root_path") or ""))
        action = str(task.get("action") or "")
        payload = task.get("payload") if isinstance(task.get("payload"), dict) else {}
        timeout_seconds = int(task.get("timeout_seconds") or payload.get("timeout_seconds") or 120)

        if action == "ping_path":
            return succeeded({"root_path": str(root), "exists": True})
        if action == "list_tree":
            return succeeded(list_tree(root, payload))
        if action == "shell":
            return run_shell(root, payload, timeout_seconds)
        if action == "read_file":
            return read_file(root, payload)
        if action == "write_file":
            return write_file(root, payload)
        if action == "apply_patch":
            return apply_patch(root, payload, timeout_seconds)
        raise ValueError(f"不支持的本地动作: {action}")
    except Exception as exc:
        return failed(str(exc))


def succeeded(result: dict[str, Any]) -> dict[str, Any]:
    """构造成功回传体。"""
    return {"status": "succeeded", "result": result, "error": None}


def failed(message: str, result: dict[str, Any] | None = None) -> dict[str, Any]:
    """构造失败回传体。"""
    return {"status": "failed", "result": result or {}, "error": message}


def list_tree(root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    """列出 root_path 下的目录结构摘要。"""
    max_depth = int(payload.get("max_depth") or 3)
    max_entries = int(payload.get("max_entries") or 200)
    entries: list[dict[str, Any]] = []

    for item in root.rglob("*"):
        relative = item.relative_to(root)
        if len(relative.parts) > max_depth:
            continue
        entries.append(
            {
                "path": relative.as_posix(),
                "type": "dir" if item.is_dir() else "file",
                "size": item.stat().st_size if item.is_file() else None,
            }
        )
        if len(entries) >= max_entries:
            break

    return {"root_path": str(root), "entries": entries, "truncated": len(entries) >= max_entries}


def run_shell(root: Path, payload: dict[str, Any], timeout_seconds: int) -> dict[str, Any]:
    """在 root_path 下执行 shell 命令。"""
    args = payload.get("args")
    if isinstance(args, list) and args:
        command_args = [str(item) for item in args]
        result = subprocess.run(
            command_args,
            cwd=root,
            shell=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        data = {
            "args": command_args,
            "cwd": str(root),
            "exit_code": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
        if result.returncode == 0:
            return succeeded(data)
        return failed(f"命令退出码 {result.returncode}", data)

    command = str(payload.get("command") or "").strip()
    if not command:
        raise ValueError("payload.args 或 payload.command 不能为空")

    result = subprocess.run(
        command,
        cwd=root,
        shell=True,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )
    data = {
        "command": command,
        "cwd": str(root),
        "exit_code": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }
    if result.returncode == 0:
        return succeeded(data)
    return failed(f"命令退出码 {result.returncode}", data)


def read_file(root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    """读取 root_path 下的文本文件。"""
    target = resolve_payload_path(root, payload)
    max_bytes = int(payload.get("max_bytes") or 2_000_000)
    raw = target.read_bytes()
    truncated = len(raw) > max_bytes
    content = raw[:max_bytes].decode(str(payload.get("encoding") or "utf-8"), errors="replace")
    return succeeded(
        {
            "path": str(target),
            "content": content,
            "truncated": truncated,
            "size": len(raw),
        }
    )


def write_file(root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    """写入 root_path 下的文本文件。"""
    target = resolve_payload_path(root, payload)
    content = str(payload.get("content") or "")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding=str(payload.get("encoding") or "utf-8"))
    return succeeded({"path": str(target), "bytes": len(content.encode("utf-8"))})


def apply_patch(root: Path, payload: dict[str, Any], timeout_seconds: int) -> dict[str, Any]:
    """把 unified diff 应用到 root_path。"""
    patch_text = str(payload.get("patch") or "")
    if not patch_text.strip():
        raise ValueError("payload.patch 不能为空")

    attempts = [
        ["git", "apply", "--whitespace=nowarn"],
        ["patch", "-p0"],
    ]
    errors: list[str] = []
    for command in attempts:
        try:
            result = subprocess.run(
                command,
                cwd=root,
                input=patch_text,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
        except FileNotFoundError as exc:
            errors.append(f"{command[0]} 不存在: {exc}")
            continue
        if result.returncode == 0:
            return succeeded(
                {
                    "command": " ".join(command),
                    "stdout": result.stdout,
                    "stderr": result.stderr,
                }
            )
        errors.append(f"{' '.join(command)}: {result.stderr.strip() or result.stdout.strip()}")

    return failed("补丁应用失败", {"errors": errors})


def request_json(
    server_url: str,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """调用服务端 JSON API 并解开统一响应 data。"""
    body = json.dumps(payload or {}, ensure_ascii=False).encode("utf-8")
    req = request.Request(
        f"{server_url.rstrip('/')}{path}",
        data=body if method.upper() != "GET" else None,
        method=method.upper(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with request.urlopen(req, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"服务端请求失败: HTTP {exc.code} {detail}") from exc

    if not isinstance(data, dict) or data.get("code", 500) >= 400:
        raise RuntimeError(f"服务端返回异常: {data}")
    return data.get("data")


def poll_once(server_url: str, agent_name: str) -> bool:
    """轮询并执行一个任务；没有任务时返回 False。"""
    data = request_json(
        server_url,
        "POST",
        "/v1/local-agent/poll",
        {"agent_name": agent_name},
    )
    task = data.get("task") if isinstance(data, dict) else None
    if not task:
        return False

    print(
        "local tool agent task received: "
        f"id={task.get('id')} action={task.get('action')} root_path={task.get('root_path')}",
        flush=True,
    )
    result = execute_local_task(task)
    request_json(
        server_url,
        "POST",
        f"/v1/local-agent/tasks/{task['id']}/complete",
        result,
    )
    print(
        f"local tool agent task completed: id={task.get('id')} status={result.get('status')}",
        flush=True,
    )
    return True


def should_log_heartbeat(now: float, last_logged_at: float, interval: float) -> bool:
    """判断是否需要打印空闲心跳日志。"""
    return interval > 0 and now - last_logged_at >= interval


def run_loop(
    server_url: str,
    agent_name: str,
    poll_interval: float,
    heartbeat_interval: float,
) -> None:
    """持续轮询服务端任务。"""
    print(f"local tool agent started: server={server_url} agent={agent_name}", flush=True)
    last_heartbeat_at = 0.0
    while True:
        try:
            has_task = poll_once(server_url, agent_name)
            if not has_task:
                now = time.monotonic()
                if should_log_heartbeat(now, last_heartbeat_at, heartbeat_interval):
                    print(
                        "local tool agent heartbeat ok: waiting for tasks...",
                        flush=True,
                    )
                    last_heartbeat_at = now
                time.sleep(poll_interval)
        except KeyboardInterrupt:
            print("local tool agent stopped", flush=True)
            return
        except Exception as exc:
            print(f"local tool agent error: {exc}", flush=True)
            time.sleep(poll_interval)


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(description="claude-sdk 本地工具中继脚本")
    parser.add_argument("--server", required=True, help="远端 claude-sdk 服务地址")
    parser.add_argument("--agent-name", default="local-agent", help="本地脚本实例名")
    parser.add_argument("--poll-interval", type=float, default=1.0, help="空队列轮询间隔秒数")
    parser.add_argument("--heartbeat-interval", type=float, default=30.0, help="空闲心跳日志间隔秒数")
    return parser.parse_args()


def main() -> None:
    """脚本入口。"""
    args = parse_args()
    run_loop(args.server, args.agent_name, args.poll_interval, args.heartbeat_interval)


if __name__ == "__main__":
    main()
