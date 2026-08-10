from pathlib import Path

SETUP_SCRIPT = Path(__file__).parents[1] / "setup.sh"


def test_setup_only_offers_supported_llm_keys() -> None:
    script = SETUP_SCRIPT.read_text(encoding="utf-8")

    assert "GEMINI_API_KEY" not in script
    for key_name in (
        "DEEPSEEK_API_KEY",
        "DASHSCOPE_API_KEY",
        "MOONSHOT_API_KEY",
        "XIAOMI_API_KEY",
        "OPENROUTER_API_KEY",
        "OPENAI_API_KEY",
    ):
        assert key_name in script


def test_setup_uses_valid_backend_commands_and_hides_keys() -> None:
    script = SETUP_SCRIPT.read_text(encoding="utf-8")

    assert "python -m application.py" not in script
    assert "python application.py" in script
    assert "read -r -s tavily_key" in script
    assert "read -r -s llm_key" in script
