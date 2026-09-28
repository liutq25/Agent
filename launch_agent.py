"""Windows one-click local launcher for CogniTutor-DS."""
import ctypes
import importlib.util
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
HOST = "127.0.0.1"
PORT = 8000
URL = f"http://{HOST}:{PORT}/"


def notice(message: str, title: str = "知学 CogniTutor-DS") -> None:
    if os.name == "nt":
        ctypes.windll.user32.MessageBoxW(None, message, title, 0x10)
    else:
        print(f"{title}: {message}", file=sys.stderr)


def running_ours() -> bool:
    try:
        with urllib.request.urlopen(f"{URL}api/health", timeout=1.5) as response:
            if response.status != 200 or b'"status":"ok"' not in response.read():
                return False
        with urllib.request.urlopen(f"{URL}openapi.json", timeout=1.5) as response:
            return "知学 CogniTutor-DS" in response.read().decode("utf-8")
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def port_in_use() -> bool:
    with socket.socket() as sock:
        return sock.connect_ex((HOST, PORT)) == 0


def main() -> int:
    from app.config import load_local_env
    load_local_env()
    if running_ours():
        webbrowser.open(URL)
        return 0
    if port_in_use():
        notice(f"端口 {PORT} 已被其他程序占用。请关闭占用程序后重试。")
        return 1
    for package in ("fastapi", "uvicorn", "httpx", "langgraph", "yaml"):
        if importlib.util.find_spec(package) is None:
            notice(f"缺少运行依赖 {package}。请在项目目录执行：\npython -m pip install -r requirements.txt -i https://pypi.org/simple")
            return 1
    data = ROOT / "data"
    data.mkdir(exist_ok=True)
    log = data / "server.log"
    env = os.environ.copy()
    env.setdefault("MOCK_LLM", "true")
    kwargs = {"cwd": ROOT, "env": env, "stdin": subprocess.DEVNULL}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    with log.open("ab") as output:
        process = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", HOST,
                                    "--port", str(PORT)], stdout=output, stderr=subprocess.STDOUT, **kwargs)
    for _ in range(40):
        if running_ours():
            webbrowser.open(URL)
            return 0
        if process.poll() is not None:
            break
        time.sleep(0.25)
    notice(f"启动失败。请查看日志：\n{log}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
