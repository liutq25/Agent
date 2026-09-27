"""Model-directed tool invocation with a strict deterministic allowlist."""
import json
import re

from .algorithm_tools import execute_tool
from .providers import MockProvider


TOOL_TOPICS = {
    "simulate_stack": ("栈", "压栈", "出栈"),
    "simulate_queue": ("队列", "入队", "出队"),
    "binary_search_trace": ("二分",),
    "bst_search": ("BST", "二叉搜索树"),
    "heapify": ("建堆", "堆化", "最大堆"),
    "bfs_trace": ("BFS", "广度优先"),
    "dfs_trace": ("DFS", "深度优先"),
    "insertion_sort_trace": ("插入排序",),
    "bubble_sort_trace": ("冒泡排序",),
    "quick_sort_trace": ("快速排序", "快排"),
    "merge_sort_trace": ("归并排序",),
    "heap_sort_trace": ("堆排序",),
    "heap_insert": ("堆插入",),
    "bst_insert": ("BST插入", "二叉搜索树插入"),
    "topological_sort_trace": ("拓扑排序",),
    "hash_insert_trace": ("哈希插入",),
    "binary_tree_traversal": ("二叉树遍历",),
    "reconstruct_binary_tree": ("重建二叉树",),
}

PARAMETERS = {
    "simulate_stack": {"operations": {"type": "array", "items": {"type": "array"}}},
    "simulate_queue": {"operations": {"type": "array", "items": {"type": "array"}}},
    "binary_search_trace": {"values": {"type": "array", "items": {"type": "integer"}},
                            "target": {"type": "integer"}},
    "bst_search": {"values": {"type": "array", "items": {"type": "integer"}},
                   "target": {"type": "integer"}},
    "heapify": {"values": {"type": "array", "items": {"type": "integer"}}},
    "bfs_trace": {"graph": {"type": "object"}, "start": {"type": "string"}},
    "dfs_trace": {"graph": {"type": "object"}, "start": {"type": "string"}},
    "insertion_sort_trace": {"values": {"type": "array", "items": {"type": "integer"}}},
    "bubble_sort_trace": {"values": {"type": "array", "items": {"type": "integer"}}},
    "quick_sort_trace": {"values": {"type": "array", "items": {"type": "integer"}}},
    "merge_sort_trace": {"values": {"type": "array", "items": {"type": "integer"}}},
    "heap_sort_trace": {"values": {"type": "array", "items": {"type": "integer"}}},
    "heap_insert": {"values": {"type": "array", "items": {"type": "integer"}}, "value": {"type": "integer"}},
    "bst_insert": {"values": {"type": "array", "items": {"type": "integer"}}},
    "topological_sort_trace": {"graph": {"type": "object"}},
    "hash_insert_trace": {"values": {"type": "array", "items": {"type": "integer"}}, "capacity": {"type": "integer"}},
    "binary_tree_traversal": {"tree": {"type": "object"}, "order": {"type": "string"}},
    "reconstruct_binary_tree": {"preorder": {"type": "array", "items": {"type": "integer"}}, "inorder": {"type": "array", "items": {"type": "integer"}}},
}


async def select_and_run_tool(provider, text: str) -> dict | None:
    if isinstance(provider, MockProvider) or not re.search(r"模拟|轨迹|逐步|每一步|步骤|运行过程", text):
        return None
    candidates = [name for name, aliases in TOOL_TOPICS.items()
                  if any(alias.lower() in text.lower() for alias in aliases)]
    if not candidates:
        return None
    tools = [{"type": "function", "function": {
        "name": name, "description": "计算 " + name + " 的确定性操作轨迹；仅在输入足够具体时调用。",
        "parameters": {"type": "object", "properties": PARAMETERS[name],
                       "required": list(PARAMETERS[name])}}} for name in candidates[:3]]
    message = await provider.chat_with_tools([{"role": "user", "content":
        "如果学生给出具体输入并要求算法步骤，请选择一个合适的工具并填入参数。"
        "若输入不足，不调用工具。学生原话：" + text}], tools, tool_choice="auto")
    for call in message.get("tool_calls", []) if isinstance(message, dict) else []:
        func = call.get("function", {})
        name = func.get("name")
        if name not in candidates:
            continue
        try:
            raw = func.get("arguments", "{}")
            arguments = json.loads(raw) if isinstance(raw, str) else raw
            params = arguments.get("params", arguments)
            if isinstance(params, dict) and "values" not in params and "array" in params:
                params["values"] = params.pop("array")
            trace = execute_tool(name, params)
            return {"tool_name": name, "params": params, "trace": trace}
        except (ValueError, TypeError, AttributeError):
            continue
    return None
