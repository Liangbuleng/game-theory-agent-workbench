"""冒烟测试：验证 LLMClient 能成功调一次 LLM。"""

from agent.llm import LLMClient


def test_default_provider_chat():
    """用默认 provider 发一句简单问候，验证返回非空字符串。"""
    client = LLMClient()
    print(f"使用配置：{client.info()}")
    reply = client.ask("用一句话回答：1+1 等于几？")
    print(f"LLM 回复：{reply}")
    assert reply.strip(), "LLM 返回了空字符串"


def test_conversation():
    """验证多轮对话上下文保留。"""
    client = LLMClient()
    conv = client.new_conversation(system="你是数学助手，简短回答。")
    
    conv.add_user("我有两个苹果。")
    conv.send()
    
    conv.add_user("我又买了三个，现在共有几个？")
    reply = conv.send()
    
    print(f"第二轮回复：{reply}")
    # 答案里应该出现 "5" 或 "五"
    assert "5" in reply or "五" in reply, f"回复中未提到正确答案：{reply}"


if __name__ == "__main__":
    test_default_provider_chat()
    print("✓ test_default_provider_chat passed")
    test_conversation()
    print("✓ test_conversation passed")