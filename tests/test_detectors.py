"""Behavior regressions for legal_redactor.detectors rule recall.

Covers high-value, low-false-positive gaps: party role+name+action boundaries,
phone OCR separators, bank branch organization surfaces, and title lines that
only contain “纠纷一案”. Negative cases protect statutes and judicial interpretations.
"""

from __future__ import annotations

from legal_redactor.detectors import (
    detect_heuristic_ner_candidates,
    detect_inline_party_person_list_candidates,
    detect_party_candidates,
    detect_regex_candidates,
    detect_title_candidates,
    extract_organization_entities,
)


def test_party_role_name_action_boundary_recall() -> None:
    """角色+姓名+动作句应只取姓名，不再把“到庭作证/不服判决”并入实体。"""
    cases = {
        "证人刘芳到庭作证。": "刘芳",
        "证人 刘芳到庭作证。": "刘芳",
        "上诉人陈戊靖不服原审判决。": "陈戊靖",
        "利害关系人王芳提出异议。": "王芳",
        "复议申请人陈戊靖申请复议。": "陈戊靖",
        "案外人刘某提出执行异议。": "刘某",
    }
    for text, name in cases.items():
        party, _ = detect_party_candidates(text)
        assert any(c.text == name and c.type == "person" for c in party), text
        assert not any(name in c.text and c.text != name for c in party), text

    inline = detect_inline_party_person_list_candidates("第三人张三、李四、王五参加诉讼。")
    assert {c.text for c in inline} >= {"张三", "李四", "王五"}


def test_phone_ocr_space_and_dash_variants() -> None:
    """手机号允许 OCR/排版常见的空格、连字符分隔，且不误伤短数字。"""
    spaced = detect_regex_candidates("联系电话：138 0013 8000")
    dashed = detect_regex_candidates("电话：138-0013-8000")
    plain = detect_regex_candidates("手机号：13800138000")

    assert any(c.type == "phone" and "138" in c.text and "8000" in c.text for c in spaced)
    assert any(c.type == "phone" and "138-0013-8000" in c.text for c in dashed)
    assert any(c.type == "phone" and "13800138000" in c.text for c in plain)

    short = detect_regex_candidates("电话：138-0013-800")
    assert not any(c.type == "phone" for c in short)


def test_org_bank_branch_and_law_reference_guards() -> None:
    """银行分行/分公司应整段召回；法条与司法解释名称不得被当成机构。"""
    bank = "中国建设银行股份有限公司石家庄分行"
    branch = "河北建工集团有限责任公司第一分公司"
    noisy = "郝亚雄去跟天津市慕尚园林绿化工程有限公司"

    bank_orgs = [c.text for c in detect_heuristic_ner_candidates(bank) if c.type == "organization"]
    assert bank in bank_orgs
    assert extract_organization_entities(bank)[0][0] == bank

    branch_orgs = [
        c.text for c in detect_heuristic_ner_candidates(branch) if c.type == "organization"
    ]
    assert branch in branch_orgs

    noisy_orgs = [c.text for c in detect_heuristic_ner_candidates(noisy) if c.type == "organization"]
    assert "天津市慕尚园林绿化工程有限公司" in noisy_orgs
    assert not any(text.startswith("郝亚雄") for text in noisy_orgs)

    law_texts = [
        "根据公司法相关规定，应当依法办理。",
        "根据《中华人民共和国公司法》第五条之规定",
        "依照《最高人民法院关于适用〈中华人民共和国民事诉讼法〉的解释》第九十条",
        "根据《中华人民共和国民法典》第五百七十七条之规定",
    ]
    for text in law_texts:
        orgs = [c for c in detect_heuristic_ner_candidates(text) if c.type == "organization"]
        assert orgs == [], text
        assert extract_organization_entities(text) == [], text


def test_title_dispute_case_without_judgment_keyword() -> None:
    """标题行仅有“纠纷一案”而无“判决书”时，仍应解析双方当事人。"""
    text = "张三与李四民间借贷纠纷一案"
    candidates = detect_title_candidates(text)
    names = {c.text for c in candidates if c.type == "person"}
    assert "张三" in names
    assert "李四" in names

    law = "本院认为，根据《中华人民共和国民法典》第五百七十七条之规定，应予支持。"
    assert detect_title_candidates(law) == []
