from __future__ import annotations

from pathlib import Path

import pytest

from legal_redactor.detectors import detect_standard_regex_candidates
from legal_redactor.pipeline import map_case_number


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "public_spc"
PUBLIC_SPC_CASES = (
    (
        "01_四川中成煤炭建设（集团）有限责任公司与成都泓昌嘉泰房地产有限公司建设工程施工合同纠_纷案.txt",
        "（2021）最高法民再188号",
        "《中华人民共和国合同法》第二百八十六条",
    ),
    (
        "02_江苏南通二建集团有限公司与上海农村商业银行股份有限公司浦东分行等建设工程施工合同纠_纷案.txt",
        "（2021）最高法民申3629号",
        "《中华人民共和国民事诉讼法》第二百条第一项、第三项、第六项",
    ),
    (
        "03_江苏南通六建建设集团有限公司与衡水鸿泰房地产开发有限公司建设工程施工合同纠纷案.txt",
        "（2018）最高法民申6278 号",
        "《中华人民共和国民事诉讼法》第二百零五条",
    ),
)


@pytest.mark.parametrize(("filename", "spc_case_number", "legal_citation"), PUBLIC_SPC_CASES)
def test_public_spc_documents_lock_deterministic_rule_contracts(
    filename: str,
    spc_case_number: str,
    legal_citation: str,
) -> None:
    text = (FIXTURE_DIR / filename).read_text(encoding="utf-8")

    assert "最高人民法院" in text
    assert legal_citation in text

    candidates = detect_standard_regex_candidates(text)
    case_numbers = [candidate.text for candidate in candidates if candidate.type == "case_number"]

    assert spc_case_number in case_numbers
    assert map_case_number(spc_case_number, {}) == spc_case_number
    assert legal_citation in text
