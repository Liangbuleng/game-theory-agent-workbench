"""完整查看 docx 抽取的内容，并存到文件方便检查。"""

from pathlib import Path
from agent.parser import load_document
from agent.llm.config import load_llm_config


def main():
    # === 配置路径（按你的实际路径改） ===
    paper_path = "papers/模型.docx"
    output_path = "output/extracted_text.md"
    
    # === 加载 ===
    config = load_llm_config()
    provider_config = config.get_provider_config(config.default_provider)
    
    print(f"使用 provider: {config.default_provider}")
    print(f"输入文件: {paper_path}")
    print()
    
    result = load_document(paper_path, provider_config)
    
    # === 打印元信息 ===
    print(f"Loaded via: {result.loaded_via}")
    print(f"Degraded: {result.degraded}")
    print(f"Number of content blocks: {len(result.content_blocks)}")
    print()
    
    if result.warnings:
        print("警告：")
        for w in result.warnings:
            print(f"  - {w}")
        print()
    
    # === 把抽取的全文写到文件 ===
    text = result.content_blocks[0].get("text", "")
    
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(text)
    
    # === 打印关键统计 ===
    char_count = len(text)
    line_count = text.count("\n") + 1
    
    print(f"全文字符数: {char_count}")
    print(f"行数: {line_count}")
    print(f"已写入: {output_path}")
    print()
    
    # === 控制台打印一些代表性段落 ===
    # 找含 "demand" 或 "profit" 等关键词的段落，看公式抽取效果
    keywords = ["demand", "Demand", "profit", "Profit", "D1", "D2", "π", "p1", "p2", "w1"]
    
    print("=" * 60)
    print("关键词搜索（看公式抽取情况）：")
    print("=" * 60)
    
    lines = text.split("\n")
    for i, line in enumerate(lines):
        for kw in keywords:
            if kw in line:
                print(f"L{i}: {line[:300]}")
                break  # 同一行只匹配一次
    
    print()
    print("=" * 60)
    print(f"完整文本已保存到 {output_path}")
    print("请打开该文件查看抽取效果")
    print("=" * 60)


if __name__ == "__main__":
    main()