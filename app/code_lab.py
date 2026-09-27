"""Small Python exercise runner. Student code executes only inside Docker."""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path


EXERCISES = {
    "binary-search": {
        "title": "二分查找",
        "concept_id": "BINARY_SEARCH",
        "function": "binary_search",
        "task": "实现 binary_search(nums, target)：在升序数组中返回目标下标；不存在时返回 -1。",
        "tests": [
            {"name": "中间命中", "args": [[1, 3, 5, 7], 5], "expected": 2},
            {"name": "左端命中", "args": [[1, 3, 5, 7], 1], "expected": 0},
            {"name": "右端命中", "args": [[1, 3, 5, 7], 7], "expected": 3},
            {"name": "目标不存在", "args": [[1, 3, 5, 7], 4], "expected": -1},
            {"name": "空数组", "args": [[], 4], "expected": -1},
        ],
        "hints": [
            "反问：每一轮比较后，目标可能仍在区间的哪一半？区间边界应怎样更新？",
            "反例：用空数组和目标恰在最右端的数组走一遍，你的循环是否都能正确结束？",
            "线索：保持闭区间 [left, right]；比较 nums[mid] 后排除不可能的一半，结束后返回 -1。",
        ],
    },
    "valid-parentheses": {
        "title": "括号匹配",
        "concept_id": "STACK_LIFO",
        "function": "is_valid_parentheses",
        "task": "实现 is_valid_parentheses(s)：只含 ()[]{} 的字符串，全部正确配对时返回 True。",
        "tests": [
            {"name": "普通嵌套", "args": ["([])"], "expected": True},
            {"name": "错误交叉", "args": ["([)]"], "expected": False},
            {"name": "多余右括号", "args": [")"], "expected": False},
            {"name": "多余左括号", "args": ["(("], "expected": False},
            {"name": "空字符串", "args": [""], "expected": True},
        ],
        "hints": [
            "反问：遇到右括号时，最先需要核对的是此前哪个还未配对的左括号？",
            "反例：用 `([)]` 逐字符检查；只统计每种括号数量为什么会误判？",
            "线索：用栈保存未匹配的左括号；遇到右括号时检查栈顶；扫描结束后栈应为空。",
        ],
    },
}


RUNNER = r'''
import json, runpy
from pathlib import Path
spec = json.loads(Path('/work/spec.json').read_text(encoding='utf-8'))
try:
    namespace = runpy.run_path('/work/student.py')
    func = namespace.get(spec['function'])
    if not callable(func):
        raise AttributeError('未找到要求的函数：' + spec['function'])
    cases = []
    for case in spec['tests']:
        try:
            actual = func(*case['args'])
            passed = actual == case['expected']
            cases.append({'name': case['name'], 'args': case['args'], 'expected': case['expected'],
                          'actual': actual if type(actual) in (int, str, bool, float, type(None), list, dict) else repr(actual),
                          'passed': passed})
        except BaseException as error:
            cases.append({'name': case['name'], 'args': case['args'], 'expected': case['expected'],
                          'actual': None, 'passed': False,
                          'error': type(error).__name__ + ': ' + str(error)[:200]})
    print('RESULT_JSON:' + json.dumps({'status': 'TESTED', 'cases': cases}, ensure_ascii=False, default=str))
except BaseException as error:
    print('RESULT_JSON:' + json.dumps({'status': 'ERROR', 'error': type(error).__name__ + ': ' + str(error)[:200],
                                      'cases': []}, ensure_ascii=False))
'''


def sandbox_ready() -> bool:
    if not shutil.which("docker"):
        return False
    try:
        result = subprocess.run(["docker", "image", "inspect", "python:3.12-alpine"],
                                capture_output=True, timeout=3, check=False)
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def run_tests(exercise_id: str, source: str) -> dict:
    exercise = EXERCISES[exercise_id]
    if not sandbox_ready():
        return {"status": "SANDBOX_UNAVAILABLE", "cases": [],
                "message": "安全运行环境尚未就绪。请安装并启动 Docker，并预先准备 python:3.12-alpine 镜像。代码未在本机执行。"}
    if len(source) > 12000:
        raise ValueError("代码超过 12000 字符限制")
    with tempfile.TemporaryDirectory(prefix="cognitutor-code-") as temporary:
        folder = Path(temporary)
        container_name = "cognitutor-code-" + uuid.uuid4().hex
        (folder / "student.py").write_text(source, encoding="utf-8")
        (folder / "spec.json").write_text(json.dumps({
            "function": exercise["function"], "tests": exercise["tests"]}, ensure_ascii=False), encoding="utf-8")
        (folder / "runner.py").write_text(RUNNER, encoding="utf-8")
        command = ["docker", "run", "--rm", "--name", container_name,
                   "--pull=never", "--network=none", "--read-only",
                   "--cpus=0.5", "--memory=128m", "--pids-limit=32", "--cap-drop=ALL",
                   "--security-opt=no-new-privileges", "--user=65534:65534",
                   "--tmpfs=/tmp:rw,noexec,nosuid,size=16m",
                   "--mount", f"type=bind,src={folder.resolve()},dst=/work,readonly",
                   "--workdir=/work", "python:3.12-alpine", "python", "-I", "/work/runner.py"]
        try:
            process = subprocess.run(command, capture_output=True, text=True, timeout=8,
                                     encoding="utf-8", errors="replace", check=False)
        except subprocess.TimeoutExpired:
            try:
                subprocess.run(["docker", "rm", "-f", container_name], capture_output=True,
                               timeout=3, check=False)
            except (OSError, subprocess.TimeoutExpired):
                pass
            return {"status": "TIMEOUT", "cases": [], "message": "运行超过 8 秒，已终止。请检查是否存在死循环。"}
        except OSError:
            return {"status": "SANDBOX_UNAVAILABLE", "cases": [], "message": "无法启动隔离运行环境；代码未执行。"}
    marker = "RESULT_JSON:"
    output = process.stdout[:20000]
    if marker not in output:
        return {"status": "ERROR", "cases": [],
                "message": "程序未产生可核验结果；请检查语法或运行时错误。",
                "stderr": process.stderr[-1000:]}
    try:
        result = json.loads(output.rsplit(marker, 1)[1].splitlines()[0])
    except (ValueError, IndexError):
        return {"status": "ERROR", "cases": [], "message": "运行结果格式无效。"}
    if result.get("status") == "TESTED":
        cases = result.get("cases")
        expected = exercise["tests"]
        if not isinstance(cases, list) or len(cases) != len(expected) or any(
            not isinstance(actual, dict) or actual.get("name") != spec["name"] or
            actual.get("args") != spec["args"] or actual.get("expected") != spec["expected"] or
            not isinstance(actual.get("passed"), bool)
            for actual, spec in zip(cases, expected)
        ):
            return {"status": "ERROR", "cases": [], "message": "测试结果不完整，未计入掌握度。"}
    elif result.get("status") != "ERROR":
        return {"status": "ERROR", "cases": [], "message": "无法核验运行结果。"}
    return result


def feedback(exercise: dict, result: dict, stage: int) -> str:
    if result["status"] == "SANDBOX_UNAVAILABLE":
        return result["message"]
    if result["status"] == "TIMEOUT":
        return result["message"] + "\n" + exercise["hints"][min(stage, 2)]
    if result["status"] == "ERROR":
        return "代码未通过运行：" + result.get("error", result.get("message", "未知错误")) + "\n" + exercise["hints"][min(stage, 2)]
    failed = next((case for case in result["cases"] if not case["passed"]), None)
    if not failed:
        return "全部测试通过。请再想一想输入规模增大时的复杂度和边界条件。"
    detail = f"首先失败：{failed['name']}，输入 {failed['args']}；预期 {failed['expected']}，实际 {failed['actual']}。"
    if failed.get("error"):
        detail += "运行错误：" + failed["error"] + "。"
    return detail + "\n" + exercise["hints"][min(stage, 2)]
