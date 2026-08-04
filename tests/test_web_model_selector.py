from legal_redactor.web_templates import render_home_page


def test_model_select_uses_live_manager_default_and_disables_when_empty() -> None:
    two_models = render_home_page(
        "", "", "", [{"id": "first", "label": "First"}, {"id": "second", "label": "Second"}], "second"
    )
    assert 'value="second" selected' in two_models
    assert 'value="first" selected' not in two_models

    unavailable_default = render_home_page(
        "", "", "", [{"id": "first", "label": "First"}, {"id": "second", "label": "Second"}], "gone"
    )
    assert 'value="first" selected' in unavailable_default

    empty = render_home_page("", "", "", [], "qwen3.6-27b-fp8")
    assert '<select id="model-choice" name="model" disabled>' in empty
    assert "暂无可用模型（停止新的脱敏生成）" in empty
