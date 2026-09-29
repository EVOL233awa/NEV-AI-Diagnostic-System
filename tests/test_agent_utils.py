"""AgentRunner 纯函数离线测试：ask 选项去重、状态卡合并。"""
from __future__ import annotations

from types import SimpleNamespace

from backend.core.agent.runner import AgentRunner, _strip_unclear_options, normalize_diag


def test_strip_unclear_options_removes_fallback_items() -> None:
    qs = [
        {
            "id": "q1",
            "question": "异响出现在什么工况？",
            "options": ["冷启动异响", "热车后异响", "不清楚", "还没试过", "不确定", 42, None],
        }
    ]
    out = _strip_unclear_options(qs)
    assert out[0]["options"] == ["冷启动异响", "热车后异响"]


def test_strip_unclear_options_keeps_question_without_options() -> None:
    q = {"id": "q2", "question": "请描述具体现象"}
    assert _strip_unclear_options([q])[0] is q


def test_strip_unclear_options_keeps_normal_words() -> None:
    """选项里含正常措辞（如「不确定故障灯是否常亮」之外的普通描述）不受误伤。"""
    qs = [{"options": ["行车时亮起", "停车自检时亮起后熄灭"]}]
    assert _strip_unclear_options(qs)[0]["options"] == qs[0]["options"]


def _runner() -> AgentRunner:
    # _merge_case_notes 不读实例属性，绕过 __init__（避免拉起 provider/工具注册）
    return AgentRunner.__new__(AgentRunner)


def test_merge_case_notes_overwrite_and_append() -> None:
    session = SimpleNamespace(case_notes=None)
    runner = _runner()
    runner._merge_case_notes(session, {"vehicle": "汉 EV 2023", "symptoms": ["续航下降"]})
    runner._merge_case_notes(session, {"vehicle": "汉EV尊享版", "symptoms": ["充电慢"]})
    assert session.case_notes["vehicle"] == "汉EV尊享版"
    assert session.case_notes["symptoms"] == ["续航下降", "充电慢"]


def test_merge_case_notes_dedup_and_type_guard() -> None:
    session = SimpleNamespace(case_notes={"symptoms": ["异响"], "checked": "不是胎噪"})
    runner = _runner()
    runner._merge_case_notes(
        session, {"symptoms": ["异响", "低速咔哒声", 123, ""], "checked": ["已查胎压"]}
    )
    assert session.case_notes["symptoms"] == ["异响", "低速咔哒声"]
    # 字符串旧值迁移为单元素后追加新项（生产修复后的语义）
    assert session.case_notes["checked"] == ["不是胎噪", "已查胎压"]
    # 再次以字符串传入 → 收敛为单项追加
    runner._merge_case_notes(session, {"checked": "悬架检查完毕"})
    assert session.case_notes["checked"] == ["不是胎噪", "已查胎压", "悬架检查完毕"]


def test_merge_case_notes_ignores_empty_vehicle() -> None:
    session = SimpleNamespace(case_notes={"vehicle": "原档案"})
    _runner()._merge_case_notes(session, {"vehicle": "   "})
    assert session.case_notes["vehicle"] == "原档案"


def test_normalize_diag_accepts_string_hypotheses() -> None:
    """实测回归：模型会把 hypotheses 给成字符串数组 → 前端渲染出空列表（2026-09-26）。"""
    diag = normalize_diag(
        {
            "severity": "yellow",
            "summary": "电池功率受限保护",
            "hypotheses": ["低温限功率", {"cause": "OBC 故障", "evidence": ["kb1"]}, 42, None],
            "steps": ["读故障码", 7, "", {"x": 1}],
            "pending_checks": "不是列表",
        }
    )
    # evidence 契约已废弃（车主端不渲染来源详情）：模型带回的 evidence 一并剥除，收敛纯 title
    assert diag["hypotheses"] == [
        {"title": "低温限功率"},
        {"title": "OBC 故障"},
    ]
    assert diag["steps"] == ["读故障码", "7"]
    assert diag["pending_checks"] == []
    assert diag["summary"] == "电池功率受限保护"


def test_normalize_diag_fills_missing_fields() -> None:
    diag = normalize_diag({"severity": "", "summary": None, "hypotheses": "坏的"})
    assert diag["severity"] == "yellow"
    assert diag["summary"] == ""
    assert diag["hypotheses"] == []
    assert diag["steps"] == []
    assert diag["pending_checks"] == []


def test_provider_label_derives_from_base_url() -> None:
    """usage 统计供应商标识跟随实际供应商（superadmin 换槽位后维度不失真）。"""
    from backend.core.providers.llm import provider_label

    assert provider_label("https://api.deepseek.com") == "deepseek.com"
    assert provider_label("https://api.siliconflow.cn/v1") == "siliconflow.cn"
    # 缺 scheme 的 base_url 按 https 补全解析主机名
    assert provider_label("dashscope.aliyuncs.com/compatible-mode/v1") == "dashscope.aliyuncs.com"
    assert provider_label("") == ""
    assert len(provider_label("https://" + "x" * 100 + ".com")) == 32
