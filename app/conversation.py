"""Tutor response generation, kept separate from evidence-based diagnosis."""
import re
from .providers import MockProvider


def is_coding_request(text: str) -> bool:
    return bool(re.search(r"```|(^|\s)def\s+\w+|代码|编程|程序|函数|伪代码|实现|写出|写一个|调试", text, re.I))


def enforce_no_full_code(answer: str) -> str:
    """A final output guard for programming help, independent of the model prompt."""
    answer = re.sub(r"```[\s\S]*?```", "[完整代码已隐藏，请先尝试实现关键步骤]", answer)
    kept = []
    for line in answer.splitlines():
        if re.match(r"^\s*(?:def|class|import|from|for|while|if|elif|else|return|try|except)\b", line):
            continue
        if re.match(r"^\s*[a-zA-Z_][\w]*(?:\[[^\]]+\])?\s*(?:\+|-|\*|/)?=\s*[^=]", line):
            continue
        kept.append(line)
    return "\n".join(kept).strip() or "我可以帮你分析思路和错误。请先给出你目前的实现或遇到的具体问题。"


async def answer_question(provider, text: str, history: list[dict], cards: list[str],
                          context_hint: str = "", code_stage: int = 0,
                          coding_context: bool = False) -> str:
    coding = coding_context or is_coding_request(text)
    stage_instruction = [
        "本轮使用反问：解释所需概念后，只提出一个能推动学生自己完成下一步的关键问题。",
        "本轮使用反例：解释当前问题后，给一个最小反例或边界输入，让学生检查自己的方案。",
        "本轮使用线索：解释当前问题后，给出算法结构、关键变量或局部修改方向。",
    ][min(code_stage, 2)] if coding else ""
    if isinstance(provider, MockProvider):
        if cards:
            return "演示模式只能提供简要知识卡：" + " ".join(cards) + "\n" + (
                stage_instruction if coding else "要获得完整的对话解答，请配置模型 API。")
        return "当前是演示模式，知识卡尚未覆盖这个问题。配置模型 API 后可进行开放式回答与诊断。"
    system = ("你是《数据结构》课程的对话式助教。当前任务是完整回答学生这轮的问题。"
              "先给明确结论，再解释原理、关键步骤、必要条件；适合时给具体例子或代码。"
              "若问题含错误前提，先指出正确事实并解释，不要沿用错误前提。"
              "分析线性表操作时区分顺序表和链表、单次和重复操作、已知位置和需要定位；"
              "例如顺序表删除后移动元素最坏 O(n)，而已知链表前驱时改链接可 O(1)。"
              "讲解 Python 二分查找边界时，中间下标必须使用整数除法 //，不能用产生浮点数的 /。"
              "结合最近对话理解‘那’‘这个’等指代，保持主题连续。"
              "不要以反问或测验代替回答；诊断追问由另一个模块决定。"
              "若学生请求编写或调试代码，先回答原理和错误原因，再给当前级别的提示；"
              "不得给出可直接提交的完整函数、完整程序或成块代码。"
              + stage_instruction +
              "学生提问本身不能证明其不会。若知识卡不足，请根据可靠的数据结构知识回答并说明不确定处。\n"
              + context_hint + "\n知识卡：" + "\n".join(cards))
    answer = await provider.chat([{"role": "system", "content": system}, *history[-8:],
                                  {"role": "user", "content": text}], temperature=0.2, max_tokens=1600)
    if not answer or not answer.strip():
        raise RuntimeError("Model returned an empty answer")
    return enforce_no_full_code(answer) if coding else answer.strip()
