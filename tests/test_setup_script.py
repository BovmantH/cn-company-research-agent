from pathlib import Path

SETUP_SCRIPT = Path(__file__).parents[1] / "setup.sh"


def test_setup_only_offers_supported_llm_keys() -> None:
    script = SETUP_SCRIPT.read_text(encoding="utf-8")

    assert "GEMINI_API_KEY" not in script
    for key_name in (
        "OPENCODE_API_KEY",
        "DEEPSEEK_API_KEY",
        "MOONSHOT_API_KEY",
        "DASHSCOPE_API_KEY",
        "ZAI_API_KEY",
        "MINIMAX_API_KEY",
        "MIMO_API_KEY",
        "OPENROUTER_API_KEY",
        "OPENAI_API_KEY",
    ):
        assert key_name in script

    assert "XIAOMI_API_KEY" not in script


def test_setup_prefers_deepseek_and_explains_console_pay_as_you_go() -> None:
    script = SETUP_SCRIPT.read_text(encoding="utf-8")

    assert 'echo "1) DeepSeek' in script
    assert "llm_choice=${llm_choice:-1}" in script
    assert '1) llm_key_name="DEEPSEEK_API_KEY"' in script
    assert "OpenCode Console" in script
    assert "按量付费" in script
    assert "LLM_VENDOR" in script
    assert "限时免费" not in script
    assert "自动付费回退" not in script


def test_setup_uses_valid_backend_commands_and_hides_keys() -> None:
    script = SETUP_SCRIPT.read_text(encoding="utf-8")

    assert "python -m application.py" not in script
    assert "python application.py" in script
    assert "read -r -s tavily_key" in script
    assert "read -r -s llm_key" in script
