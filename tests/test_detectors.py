"""Behavior regressions for deterministic structured-identifier detection."""

from __future__ import annotations

from legal_redactor.detectors import detect_regex_candidates


def test_phone_ocr_space_and_dash_variants() -> None:
    spaced = detect_regex_candidates("联系电话：138 0013 8000")
    dashed = detect_regex_candidates("电话：138-0013-8000")
    plain = detect_regex_candidates("手机号：13800138000")

    assert any(c.type == "phone" and "138" in c.text and "8000" in c.text for c in spaced)
    assert any(c.type == "phone" and "138-0013-8000" in c.text for c in dashed)
    assert any(c.type == "phone" and "13800138000" in c.text for c in plain)
    assert not any(c.type == "phone" for c in detect_regex_candidates("电话：138-0013-800"))


def test_identity_number_and_case_number_remain_deterministic() -> None:
    text = "身份证号110105199001011234，案号（2025）冀01民终123号。"

    candidates = detect_regex_candidates(text)
    by_type = {candidate.type: candidate for candidate in candidates}

    assert by_type["id_number"].text == "身份证号110105199001011234"
    assert by_type["case_number"].text == "（2025）冀01民终123号"
    assert by_type["case_number"].source == "court_case_number_parser"



def test_bank_account_uscc_and_email_remain_deterministic() -> None:
    text = (
        "银行账号6222020202020202020，"
        "统一社会信用代码91110108MA01ABCD1X，"
        "邮箱zhang.san@example.com。"
    )

    candidates = detect_regex_candidates(text)
    by_type = {candidate.type: candidate for candidate in candidates}

    assert by_type["bank_account"].text == "银行账号6222020202020202020"
    assert by_type["unified_social_credit_code"].text == "统一社会信用代码91110108MA01ABCD1X"
    assert by_type["email"].text == "邮箱zhang.san@example.com"


def test_semantic_entities_are_not_discovered_by_structured_rules() -> None:
    text = "原告张三诉星河建设有限公司，项目位于河北省石家庄市。"

    assert detect_regex_candidates(text) == []
