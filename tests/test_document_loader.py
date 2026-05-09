"""document_loader 的冒烟测试。"""

from pathlib import Path
from agent.parser import load_document
from agent.llm.config import load_llm_config


def test_load_text_file(tmp_path):
    """txt 文件应该走 plain_text 路径。"""
    config = load_llm_config()
    provider_config = config.get_provider_config(config.default_provider)
    
    # 创建临时文件
    p = tmp_path / "test.txt"
    p.write_text("Hello, this is a test.", encoding="utf-8")
    
    result = load_document(p, provider_config)
    
    assert result.loaded_via == "plain_text"
    assert not result.degraded
    assert len(result.content_blocks) == 1
    assert result.content_blocks[0]["type"] == "text"
    assert "Hello" in result.content_blocks[0]["text"]
    print(f"✓ plain text: {result.loaded_via}")


def test_load_unsupported_extension(tmp_path):
    """不支持的扩展名应该报错。"""
    import pytest
    
    config = load_llm_config()
    provider_config = config.get_provider_config(config.default_provider)
    
    p = tmp_path / "test.xyz"
    p.write_text("dummy", encoding="utf-8")
    
    try:
        load_document(p, provider_config)
    except ValueError as e:
        assert "不支持的文件类型" in str(e)
        print(f"✓ unsupported extension correctly raised: {e}")
        return
    
    raise AssertionError("应该抛 ValueError 但没抛")


def test_load_nonexistent_file():
    """不存在的文件应该报 FileNotFoundError。"""
    config = load_llm_config()
    provider_config = config.get_provider_config(config.default_provider)
    
    try:
        load_document("/nonexistent/file.pdf", provider_config)
    except FileNotFoundError as e:
        print(f"✓ nonexistent file correctly raised: {e}")
        return
    
    raise AssertionError("应该抛 FileNotFoundError")


if __name__ == "__main__":
    import tempfile
    
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        test_load_text_file(tmp_path)
        test_load_unsupported_extension(tmp_path)
    
    test_load_nonexistent_file()
    print("\n所有 smoke tests 通过。")