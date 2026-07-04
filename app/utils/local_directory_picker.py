"""本机目录选择工具。"""
from pathlib import Path
import subprocess
import sys

from app.exceptions import BizValidationError
from app.schemas.project import LocalDirectoryPickData


def pick_local_directory() -> LocalDirectoryPickData:
    """通过后端所在机器的系统选择器获取真实目录路径。"""
    if sys.platform != "darwin":
        raise BizValidationError("当前后端环境暂不支持系统目录选择器")

    result = subprocess.run(
        [
            "osascript",
            "-e",
            'POSIX path of (choose folder with prompt "选择项目文件夹")',
        ],
        capture_output=True,
        check=False,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        message = result.stderr.strip()
        if "User canceled" in message or result.returncode == 1:
            raise BizValidationError("已取消选择文件夹")
        raise BizValidationError("系统目录选择器调用失败")

    raw_path = result.stdout.strip()
    if not raw_path:
        raise BizValidationError("未选择文件夹")

    directory = Path(raw_path).expanduser().resolve()
    if not directory.is_dir():
        raise BizValidationError("选择的路径不是有效文件夹")

    return LocalDirectoryPickData(name=directory.name or str(directory), path=str(directory))
