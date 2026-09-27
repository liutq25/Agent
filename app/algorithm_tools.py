"""Deterministic data structure traces; no student code is executed here."""
from __future__ import annotations

from collections import deque
from copy import deepcopy
from typing import Callable


def _result(name: str, params: dict, steps: list[dict], final: dict, complexity: str) -> dict:
    return {"algorithm": name, "input_data": params, "steps": steps,
            "final_result": final, "complexity": {"time": complexity}, "metadata": {"deterministic": True}}


def _numbers(value, *, max_size=30) -> list[int]:
    if not isinstance(value, list) or len(value) > max_size or any(type(x) is not int for x in value):
        raise ValueError("请输入最多 30 个整数的数组")
    return value.copy()


def _operations(params: dict, allowed: set[str]) -> list[list]:
    ops = params.get("operations")
    if not isinstance(ops, list) or len(ops) > 30:
        raise ValueError("operations 必须是不超过 30 步的列表")
    for item in ops:
        if not isinstance(item, list) or not item or item[0] not in allowed:
            raise ValueError("操作格式或名称无效")
        if len(item) != (2 if item[0] in {"push", "enqueue"} else 1):
            raise ValueError("操作参数数量无效")
        if len(item) == 2 and type(item[1]) is not int:
            raise ValueError("元素必须为整数")
    return ops


def simulate_stack(params: dict) -> dict:
    state, outputs, steps = [], [], []
    for op in _operations(params, {"push", "pop"}):
        if op[0] == "push":
            state.append(op[1]); output = None
        else:
            output = state.pop() if state else None
            outputs.append(output)
        steps.append({"operation": op, "state": state.copy(), "output": output})
    return _result("simulate_stack", params, steps, {"state": state, "outputs": outputs}, "O(k)")


def validate_stack_pop_sequence(params: dict) -> dict:
    pushes = _numbers(params.get("pushes"))
    pops = _numbers(params.get("pops"))
    if len(pushes) != len(pops):
        raise ValueError("入栈与出栈序列长度必须相同")
    stack, steps, index = [], [], 0
    for value in pushes:
        stack.append(value)
        steps.append({"operation": ["push", value], "state": stack.copy()})
        while stack and index < len(pops) and stack[-1] == pops[index]:
            out = stack.pop(); index += 1
            steps.append({"operation": ["pop"], "state": stack.copy(), "output": out})
    return _result("validate_stack_pop_sequence", params, steps,
                   {"valid": index == len(pops)}, "O(n)")


def simulate_queue(params: dict) -> dict:
    state, outputs, steps = deque(), [], []
    for op in _operations(params, {"enqueue", "dequeue"}):
        if op[0] == "enqueue":
            state.append(op[1]); output = None
        else:
            output = state.popleft() if state else None
            outputs.append(output)
        steps.append({"operation": op, "state": list(state), "output": output})
    return _result("simulate_queue", params, steps,
                   {"state": list(state), "outputs": outputs}, "O(k)")


def simulate_circular_queue(params: dict) -> dict:
    capacity = params.get("capacity")
    if type(capacity) is not int or not 1 <= capacity <= 30:
        raise ValueError("capacity 必须是 1 到 30 的整数")
    cells, front, size, outputs, steps = [None] * capacity, 0, 0, [], []
    for op in _operations(params, {"enqueue", "dequeue"}):
        output = None
        if op[0] == "enqueue":
            if size == capacity:
                raise ValueError("循环队列已满")
            cells[(front + size) % capacity] = op[1]; size += 1
        else:
            if size == 0:
                raise ValueError("循环队列为空")
            output = cells[front]; cells[front] = None
            front = (front + 1) % capacity; size -= 1; outputs.append(output)
        steps.append({"operation": op, "state": cells.copy(), "front": front,
                      "rear": (front + size) % capacity, "output": output})
    return _result("simulate_circular_queue", params, steps,
                   {"state": cells, "outputs": outputs, "front": front}, "O(k)")


def linked_list_insert_trace(params: dict) -> dict:
    values = _numbers(params.get("values"))
    index, value = params.get("index"), params.get("value")
    if type(index) is not int or not 0 <= index <= len(values) or type(value) is not int:
        raise ValueError("索引或插入值无效")
    steps = [{"operation": "visit", "state": values.copy(), "index": i} for i in range(index)]
    values.insert(index, value)
    steps.append({"operation": "link_insert", "state": values.copy(), "index": index})
    return _result("linked_list_insert_trace", params, steps, {"values": values}, "O(n) 定位 + O(1) 修改链接")


def linked_list_delete_trace(params: dict) -> dict:
    values = _numbers(params.get("values"))
    index = params.get("index")
    if type(index) is not int or not 0 <= index < len(values):
        raise ValueError("删除索引无效")
    steps = [{"operation": "visit", "state": values.copy(), "index": i} for i in range(index)]
    removed = values.pop(index)
    steps.append({"operation": "unlink", "state": values.copy(), "index": index})
    return _result("linked_list_delete_trace", params, steps,
                   {"values": values, "removed": removed}, "O(n) 定位 + O(1) 修改链接")


def binary_search_trace(params: dict) -> dict:
    values = _numbers(params.get("values"))
    target = params.get("target")
    if type(target) is not int or values != sorted(values):
        raise ValueError("target 必须是整数，values 必须有序")
    left, right, steps = 0, len(values) - 1, []
    while left <= right:
        mid = (left + right) // 2
        steps.append({"operation": "compare", "state": {"left": left, "mid": mid, "right": right,
                                                         "value": values[mid]}})
        if values[mid] == target:
            return _result("binary_search_trace", params, steps, {"index": mid}, "O(log n)")
        if values[mid] < target: left = mid + 1
        else: right = mid - 1
    return _result("binary_search_trace", params, steps, {"index": -1}, "O(log n)")


def bst_search(params: dict) -> dict:
    values = _numbers(params.get("values"))
    target = params.get("target")
    if type(target) is not int:
        raise ValueError("target 必须是整数")
    tree, steps = {}, []
    for value in values:
        node = tree
        while "value" in node:
            if value == node["value"]: break
            node = node.setdefault("left" if value < node["value"] else "right", {})
        if "value" not in node: node["value"] = value
    node = tree
    while "value" in node:
        value = node["value"]
        steps.append({"operation": "compare", "state": {"node": value, "target": target}})
        if value == target: break
        node = node.get("left" if target < value else "right", {})
    return _result("bst_search", params, steps,
                   {"found": "value" in node, "tree": tree}, "O(h)，最坏 O(n)")


def heapify(params: dict) -> dict:
    values = _numbers(params.get("values"))
    steps = []
    def sink(start, size):
        i = start
        while 2 * i + 1 < size:
            child = 2 * i + 1
            if child + 1 < size and values[child + 1] > values[child]: child += 1
            if values[i] >= values[child]: break
            values[i], values[child] = values[child], values[i]
            steps.append({"operation": "swap", "state": values.copy(), "indices": [i, child]})
            i = child
    for i in range(len(values) // 2 - 1, -1, -1): sink(i, len(values))
    return _result("heapify", params, steps, {"heap": values}, "O(n)")


def _graph(params: dict) -> tuple[dict[str, list[str]], str]:
    graph, start = params.get("graph"), params.get("start")
    if not isinstance(graph, dict) or len(graph) > 30 or not isinstance(start, str) or start not in graph:
        raise ValueError("graph 或 start 无效")
    if any(not isinstance(key, str) or not isinstance(neighbors, list) or
           any(not isinstance(v, str) or v not in graph for v in neighbors)
           for key, neighbors in graph.items()):
        raise ValueError("图邻接表无效")
    return graph, start


def bfs_trace(params: dict) -> dict:
    graph, start = _graph(params)
    queue, seen, order, steps = deque([start]), {start}, [], []
    while queue:
        node = queue.popleft(); order.append(node)
        for neighbor in graph[node]:
            if neighbor not in seen: seen.add(neighbor); queue.append(neighbor)
        steps.append({"operation": "visit", "state": {"current": node, "queue": list(queue), "visited": order.copy()}})
    return _result("bfs_trace", params, steps, {"order": order}, "O(V+E)")


def dfs_trace(params: dict) -> dict:
    graph, start = _graph(params)
    stack, seen, order, steps = [start], set(), [], []
    while stack:
        node = stack.pop()
        if node in seen: continue
        seen.add(node); order.append(node)
        stack.extend(reversed(graph[node]))
        steps.append({"operation": "visit", "state": {"current": node, "stack": stack.copy(), "visited": order.copy()}})
    return _result("dfs_trace", params, steps, {"order": order}, "O(V+E)")


def insertion_sort_trace(params: dict) -> dict:
    values = _numbers(params.get("values")); steps = []
    for i in range(1, len(values)):
        key, j = values[i], i - 1
        while j >= 0 and values[j] > key:
            values[j + 1] = values[j]; j -= 1
            steps.append({"operation": "shift", "state": values.copy(), "index": j + 1})
        values[j + 1] = key
        steps.append({"operation": "insert", "state": values.copy(), "index": j + 1})
    return _result("insertion_sort_trace", params, steps, {"values": values}, "O(n²)")


def bubble_sort_trace(params: dict) -> dict:
    values = _numbers(params.get("values")); steps = []
    for end in range(len(values) - 1, 0, -1):
        changed = False
        for i in range(end):
            if values[i] > values[i + 1]:
                values[i], values[i + 1] = values[i + 1], values[i]
                changed = True
                steps.append({"operation": "swap", "state": values.copy(), "indices": [i, i + 1]})
        if not changed: break
    return _result("bubble_sort_trace", params, steps, {"values": values}, "O(n²)，已排序 O(n)")


def _tree(value, depth=0):
    if value is None:
        return None
    if depth > 30 or not isinstance(value, dict) or type(value.get("value")) is not int:
        raise ValueError("二叉树节点格式无效或深度过大")
    return {"value": value["value"], "left": _tree(value.get("left"), depth + 1),
            "right": _tree(value.get("right"), depth + 1)}


def binary_tree_traversal(params: dict) -> dict:
    tree = _tree(params.get("tree"))
    order = params.get("order", "preorder")
    if order not in {"preorder", "inorder", "postorder", "levelorder"}:
        raise ValueError("遍历方式无效")
    values, steps = [], []
    def visit(node):
        if node is None: return
        if order == "preorder": record(node)
        visit(node["left"])
        if order == "inorder": record(node)
        visit(node["right"])
        if order == "postorder": record(node)
    def record(node):
        values.append(node["value"])
        steps.append({"operation": "visit", "state": values.copy(), "node": node["value"]})
    if order == "levelorder":
        queue = deque([tree] if tree else [])
        while queue:
            node = queue.popleft(); record(node)
            if node["left"]: queue.append(node["left"])
            if node["right"]: queue.append(node["right"])
    else:
        visit(tree)
    return _result("binary_tree_traversal", params, steps, {"order": values}, "O(n)")


def reconstruct_binary_tree(params: dict) -> dict:
    preorder, inorder = _numbers(params.get("preorder")), _numbers(params.get("inorder"))
    if len(preorder) != len(inorder) or len(set(preorder)) != len(preorder) or set(preorder) != set(inorder):
        raise ValueError("前序与中序需包含相同且互异的节点")
    steps = []
    def build(pre, ino):
        if not pre: return None
        root = pre[0]; cut = ino.index(root)
        steps.append({"operation": "choose_root", "state": {"root": root, "left": ino[:cut], "right": ino[cut+1:]}})
        return {"value": root, "left": build(pre[1:cut+1], ino[:cut]),
                "right": build(pre[cut+1:], ino[cut+1:])}
    tree = build(preorder, inorder)
    return _result("reconstruct_binary_tree", params, steps, {"tree": tree}, "O(n²) 朴素查找")


def bst_insert(params: dict) -> dict:
    values = _numbers(params.get("values")); tree, steps = {}, []
    for value in values:
        node, path = tree, []
        while "value" in node:
            path.append(node["value"])
            if value == node["value"]: break
            node = node.setdefault("left" if value < node["value"] else "right", {})
        if "value" not in node: node["value"] = value
        steps.append({"operation": "insert", "state": deepcopy(tree), "value": value, "path": path})
    return _result("bst_insert", params, steps, {"tree": tree}, "O(nh)，最坏 O(n²)")


def heap_insert(params: dict) -> dict:
    values = _numbers(params.get("values")); value = params.get("value")
    if type(value) is not int or any(values[(i - 1) // 2] < values[i] for i in range(1, len(values))):
        raise ValueError("values 必须是最大堆，value 必须是整数")
    values.append(value); steps = [{"operation": "append", "state": values.copy()}]
    i = len(values) - 1
    while i > 0 and values[(i - 1) // 2] < values[i]:
        parent = (i - 1) // 2
        values[parent], values[i] = values[i], values[parent]
        steps.append({"operation": "swap", "state": values.copy(), "indices": [parent, i]})
        i = parent
    return _result("heap_insert", params, steps, {"heap": values}, "O(log n)")


def topological_sort_trace(params: dict) -> dict:
    graph = params.get("graph")
    if not isinstance(graph, dict) or len(graph) > 30 or any(
        not isinstance(node, str) or not isinstance(neighbors, list) or len(neighbors) > 30 or
        any(not isinstance(v, str) or v not in graph for v in neighbors)
        for node, neighbors in graph.items()):
        raise ValueError("图邻接表无效")
    indegree = {node: 0 for node in graph}
    for neighbors in graph.values():
        for node in neighbors: indegree[node] += 1
    queue = deque(sorted(node for node, degree in indegree.items() if degree == 0))
    order, steps = [], []
    while queue:
        node = queue.popleft(); order.append(node)
        for neighbor in graph[node]:
            indegree[neighbor] -= 1
            if indegree[neighbor] == 0: queue.append(neighbor)
        steps.append({"operation": "remove_zero_indegree", "state": {"order": order.copy(),
                      "indegree": indegree.copy(), "queue": list(queue)}})
    return _result("topological_sort_trace", params, steps,
                   {"order": order, "acyclic": len(order) == len(graph)}, "O(V+E)")


def hash_insert_trace(params: dict) -> dict:
    values = _numbers(params.get("values")); capacity = params.get("capacity")
    if type(capacity) is not int or not 1 <= capacity <= 60 or len(values) > capacity:
        raise ValueError("哈希表容量必须在 1 到 60 之间且能容纳输入")
    slots, steps = [None] * capacity, []
    for value in values:
        index = value % capacity
        for _ in range(capacity):
            steps.append({"operation": "probe", "state": slots.copy(), "index": index, "value": value})
            if slots[index] is None:
                slots[index] = value
                steps.append({"operation": "insert", "state": slots.copy(), "index": index, "value": value})
                break
            index = (index + 1) % capacity
    return _result("hash_insert_trace", params, steps, {"slots": slots}, "平均 O(n)，最坏 O(n²) 总插入")


def quick_sort_trace(params: dict) -> dict:
    values = _numbers(params.get("values")); steps = []
    def sort(left, right):
        if left >= right: return
        pivot = values[right]; store = left
        for i in range(left, right):
            if values[i] <= pivot:
                values[store], values[i] = values[i], values[store]
                steps.append({"operation": "partition_swap", "state": values.copy(), "indices": [store, i]})
                store += 1
        values[store], values[right] = values[right], values[store]
        steps.append({"operation": "pivot_place", "state": values.copy(), "pivot_index": store})
        sort(left, store - 1); sort(store + 1, right)
    sort(0, len(values) - 1)
    return _result("quick_sort_trace", params, steps, {"values": values}, "平均 O(n log n)，最坏 O(n²)")


def merge_sort_trace(params: dict) -> dict:
    values = _numbers(params.get("values")); steps = []
    def sort(left, right):
        if right - left <= 1: return
        mid = (left + right) // 2
        sort(left, mid); sort(mid, right)
        a, b, merged = left, mid, []
        while a < mid and b < right:
            if values[a] <= values[b]: merged.append(values[a]); a += 1
            else: merged.append(values[b]); b += 1
        merged.extend(values[a:mid]); merged.extend(values[b:right])
        values[left:right] = merged
        steps.append({"operation": "merge", "state": values.copy(), "range": [left, right]})
    sort(0, len(values))
    return _result("merge_sort_trace", params, steps, {"values": values}, "O(n log n)")


def heap_sort_trace(params: dict) -> dict:
    values = _numbers(params.get("values")); steps = []
    def sink(i, size):
        while 2 * i + 1 < size:
            child = 2 * i + 1
            if child + 1 < size and values[child + 1] > values[child]: child += 1
            if values[i] >= values[child]: break
            values[i], values[child] = values[child], values[i]
            steps.append({"operation": "sift_down", "state": values.copy(), "indices": [i, child], "heap_size": size})
            i = child
    for i in range(len(values) // 2 - 1, -1, -1): sink(i, len(values))
    steps.append({"operation": "heap_built", "state": values.copy(), "heap_size": len(values)})
    for end in range(len(values) - 1, 0, -1):
        values[0], values[end] = values[end], values[0]
        steps.append({"operation": "extract_max", "state": values.copy(), "heap_size": end})
        sink(0, end)
    return _result("heap_sort_trace", params, steps, {"values": values}, "O(n log n)")


TOOLS: dict[str, Callable[[dict], dict]] = {
    func.__name__: func for func in (simulate_stack, validate_stack_pop_sequence,
        simulate_queue, simulate_circular_queue, linked_list_insert_trace,
        linked_list_delete_trace, binary_search_trace, bst_search, heapify,
        bfs_trace, dfs_trace, insertion_sort_trace, bubble_sort_trace,
        binary_tree_traversal, reconstruct_binary_tree, bst_insert, heap_insert,
        topological_sort_trace, hash_insert_trace, quick_sort_trace,
        merge_sort_trace, heap_sort_trace)
}


def execute_tool(name: str, params: dict) -> dict:
    if name not in TOOLS:
        raise ValueError("未知算法工具")
    if not isinstance(params, dict):
        raise ValueError("参数必须是 JSON 对象")
    return TOOLS[name](deepcopy(params))


def compare_student_trace(student_trace: list, reference_trace: list[dict]) -> dict:
    if not isinstance(student_trace, list) or len(student_trace) > 500:
        raise ValueError("学生轨迹必须是最多 500 步的列表")
    matched = 0
    for index in range(max(len(student_trace), len(reference_trace))):
        student = student_trace[index] if index < len(student_trace) else None
        expected = reference_trace[index].get("state") if index < len(reference_trace) else None
        if student != expected:
            return {"matched_steps": matched, "first_divergence_index": index,
                    "student_state": student, "expected_state": expected,
                    "difference": f"第 {index + 1} 步状态首次不同"}
        matched += 1
    return {"matched_steps": matched, "first_divergence_index": None,
            "student_state": None, "expected_state": None, "difference": "轨迹一致"}
