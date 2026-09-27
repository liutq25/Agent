"""Deterministic teaching loop for the initial data structures curriculum."""
import re
from dataclasses import dataclass, asdict


CONCEPTS = {
    "array_insert": {"name": "顺序表插入", "module": "线性表", "prerequisites": ["array_access"], "card": "顺序表可按下标 O(1) 访问；在中间插入通常要移动后续元素，最坏 O(n)。"},
    "array_access": {"name": "顺序表随机访问", "module": "线性表", "prerequisites": [], "card": "连续存储的顺序表通过地址计算实现 O(1) 下标访问。"},
    "linked_insert": {"name": "链表插入", "module": "线性表", "prerequisites": [], "card": "已持有目标位置的前驱节点时，改指针可 O(1) 插入；寻找节点可能需要 O(n)。"},
    "stack_lifo": {"name": "栈的后进先出", "module": "栈", "prerequisites": [], "card": "栈遵循 LIFO：最后入栈的元素最先弹出。"},
    "queue_fifo": {"name": "队列的先进先出", "module": "队列", "prerequisites": [], "card": "队列遵循 FIFO：最先入队的元素最先出队。"},
    "binary_search": {"name": "二分查找", "module": "查找", "prerequisites": ["array_access"], "card": "二分查找要求有序且可随机访问；每轮将搜索区间缩小一半。"},
    "bfs": {"name": "广度优先搜索", "module": "图", "prerequisites": ["queue_fifo"], "card": "BFS 用队列按距离层次访问顶点。"},
    "dfs": {"name": "深度优先搜索", "module": "图", "prerequisites": ["stack_lifo"], "card": "DFS 沿一条路径深入，再回溯。"},
}

QUESTIONS = {
    "array-insert": {"concept_id": "array_insert", "task_type": "COMPLEXITY", "question": "顺序表能 O(1) 下标访问，因此在中间插入元素也一定是 O(1) 吗？请解释。", "reference": "不一定；插入时需要移动后续元素，最坏 O(n)。"},
    "linked-insert": {"concept_id": "linked_insert", "task_type": "COMPLEXITY", "question": "已知链表前驱节点时插入的时间复杂度是多少？若还需查找该节点呢？", "reference": "已知前驱为 O(1)，查找前驱通常 O(n)。"},
    "stack-trace": {"concept_id": "stack_lifo", "task_type": "TRACE", "question": "栈依次 push 1、push 2、pop、push 3、pop，两个 pop 的输出是什么？", "reference": "2,3", "tool": "stack", "operations": [["push",1],["push",2],["pop"],["push",3],["pop"]]},
    "queue-trace": {"concept_id": "queue_fifo", "task_type": "TRACE", "question": "队列依次 enqueue 1、enqueue 2、dequeue、enqueue 3、dequeue，两个 dequeue 的输出是什么？", "reference": "1,2", "tool": "queue", "operations": [["enqueue",1],["enqueue",2],["dequeue"],["enqueue",3],["dequeue"]]},
}

MISCONCEPTIONS = {
    "M_ARRAY_INSERT_O1": {"concept_id": "array_insert", "name": "将随机访问复杂度误用于中间插入"},
    "M_LINKED_MEMORY": {"concept_id": "linked_insert", "name": "认为链表节点在内存中连续"},
    "M_LINKED_SEARCH_O1": {"concept_id": "linked_insert", "name": "忽略查找前驱节点的代价"},
    "M_STACK_FIFO": {"concept_id": "stack_lifo", "name": "把栈当成先进先出"},
    "M_QUEUE_LIFO": {"concept_id": "queue_fifo", "name": "把队列当成后进先出"},
}


def simulate(kind, operations):
    state, outputs, trace = [], [], []
    for index, (op, *rest) in enumerate(operations, 1):
        if op in ("push", "enqueue"):
            state.append(rest[0])
            value = None
        elif op in ("pop", "dequeue"):
            value = state.pop() if kind == "stack" else state.pop(0)
            outputs.append(value)
        else:
            raise ValueError(f"unsupported operation: {op}")
        trace.append({"step": index, "operation": op, "value": value, "state": state.copy()})
    return {"outputs": outputs, "trace": trace}


def first_divergence(expected, actual):
    for i in range(max(len(expected), len(actual))):
        left = expected[i] if i < len(expected) else None
        right = actual[i] if i < len(actual) else None
        if left != right:
            return {"step": i + 1, "expected": left, "actual": right}
    return None


@dataclass
class Diagnosis:
    answer_status: str
    concept_ids: list[str]
    misconception_ids: list[str]
    evidence_spans: list[str]
    first_divergence: dict | None
    confidence: float
    teaching_action: str
    response: str
    tool_used: str | None = None


def diagnose(question_id, answer, explanation="", student_trace=None, attempt=1):
    q = QUESTIONS[question_id]
    text = f"{answer} {explanation}".lower()
    concept = q["concept_id"]
    evidence, misconceptions, divergence, tool = [], [], None, None
    if q["task_type"] == "TRACE":
        tool = q["tool"]
        expected = simulate(tool, q["operations"])["outputs"]
        actual = student_trace if student_trace is not None else [int(x) for x in re.findall(r"\d+", answer)]
        divergence = first_divergence(expected, actual)
        if not actual:
            status = "INSUFFICIENT_EVIDENCE"
        elif divergence:
            status = "INCORRECT"
            misconceptions = ["M_STACK_FIFO" if tool == "stack" else "M_QUEUE_LIFO"]
            evidence = [answer]
        else:
            status = "CORRECT" if explanation.strip() else "PARTIALLY_CORRECT"
            evidence = [answer]
    elif question_id == "array-insert":
        mentions_move = bool(re.search(r"移动|挪动|移位|shift", text))
        says_linear = bool(re.search(r"o\s*\(?n\)?|线性|最坏.*n", text))
        says_constant = bool(re.search(r"o\s*\(?1\)?|常数", text)) and not bool(re.search(r"不是|不一定|并非|不对|不能.*o\s*\(?1\)?", text))
        if not text.strip(): status = "INSUFFICIENT_EVIDENCE"
        elif mentions_move and says_linear: status = "CORRECT"; evidence = [answer, explanation] if explanation else [answer]
        elif says_constant and not mentions_move: status = "INCORRECT"; misconceptions = ["M_ARRAY_INSERT_O1"]; evidence = [answer]
        else: status = "INSUFFICIENT_EVIDENCE"; evidence = [answer]
    else:
        known = bool(re.search(r"o\s*\(?1\)?|常数", text))
        search = bool(re.search(r"查找|遍历|寻找", text))
        linear = bool(re.search(r"o\s*\(?n\)?|线性", text))
        memory = bool(re.search(r"连续|挨着", text)) and not bool(re.search(r"不是连续|不连续|并非连续", text))
        if not text.strip(): status = "INSUFFICIENT_EVIDENCE"
        elif known and search and linear: status = "CORRECT"; evidence = [answer]
        elif memory or (known and not search):
            status = "INCORRECT"; evidence = [answer]
            misconceptions = ["M_LINKED_MEMORY" if memory else "M_LINKED_SEARCH_O1"]
        else: status = "INSUFFICIENT_EVIDENCE"; evidence = [answer]
    action = "CHALLENGE" if status == "CORRECT" else ("PROBE" if attempt <= 1 else "HINT1" if attempt == 2 else "HINT2" if attempt == 3 else "EXPLAIN")
    if action == "CHALLENGE": response = "你的推理有依据。换一个边界情况：如果数据规模翻倍，结论会怎样变化？"
    elif action == "PROBE" and divergence: response = f"请重新检查第 {divergence['step']} 次输出：此时容器中哪个元素应先离开？"
    elif action == "PROBE" and question_id == "array-insert": response = "在下标 2 插入一个新元素后，原来从下标 2 开始的元素要发生什么变化？"
    elif action == "PROBE": response = "你是否已经持有前驱节点？如果没有，定位它需要什么操作？"
    elif action == "HINT1": response = "先画出每一步的容器状态，再只检查发生变化的位置。"
    elif action == "HINT2": response = f"参考知识卡：{CONCEPTS[concept]['card']} 请据此重新解释。"
    else: response = f"关键原理：{CONCEPTS[concept]['card']} 现在请用自己的话复述。"
    return asdict(Diagnosis(status, [concept], misconceptions, [e for e in evidence if e], divergence,
        0.9 if status in ("CORRECT", "INCORRECT") else 0.3, action, response, tool))


def recommend(profile):
    mastery = profile.get("mastery", {})
    ranked = sorted(QUESTIONS.items(), key=lambda item: (mastery.get(item[1]["concept_id"], 0.5), item[0]))
    return [{"id": key, **value} for key, value in ranked[:3]]
