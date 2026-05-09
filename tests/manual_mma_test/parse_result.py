"""验证 Python 能正确读取 Mathematica 输出的 JSON。"""

import json
from pathlib import Path


def parse_cournot_result(json_path: Path) -> dict:
    """读取并验证 cournot_result.json。"""
    with open(json_path, "r", encoding="utf-8") as f:
        result = json.load(f)
    
    print(f"读取文件: {json_path}")
    print(f"场景 ID: {result['scenario_id']}")
    print(f"状态: {result['status']}")
    
    if result["status"] != "success":
        print(f"求解未成功，failed_at: {result.get('failed_at')}")
        return result
    
    print("\n均衡解:")
    for key, value in result["equilibrium"].items():
        print(f"  {key} = {value}")
    
    print("\n利润:")
    for key, value in result["profits"].items():
        print(f"  {key} = {value}")
    
    print("\nSanity checks:")
    for key, value in result["sanity_checks"].items():
        is_zero = value.strip() == "0"
        marker = "✓" if is_zero else "✗"
        print(f"  {marker} {key} = {value}")
    
    if result.get("warnings"):
        print("\n警告:")
        for w in result["warnings"]:
            print(f"  - {w}")
    
    return result


def verify_known_answer(result: dict) -> None:
    """验证已知答案：q1* 应该是 (a - 2*c1 + c2)/3。"""
    if result["status"] != "success":
        print("\n[VERIFY] 跳过：求解未成功")
        return
    
    q1_star_str = result["equilibrium"]["q1_star"]
    expected_forms = [
        "(a - 2*c1 + c2)/3",
        "(a - 2 c1 + c2)/3",
        "1/3 (a - 2 c1 + c2)",
        "1/3*(a - 2*c1 + c2)",
        # Mathematica 可能用其他等价形式输出，这里只做粗略匹配
    ]
    
    print("\n[VERIFY] 验证 q1* 的形式")
    print(f"  实际输出: {q1_star_str}")
    print(f"  期望形式（任一即可）:")
    for form in expected_forms:
        print(f"    - {form}")
    
    # 不做严格相等判断（Mathematica 输出格式可能变体），只做提示
    matched = any(form in q1_star_str.replace(" ", "") 
                  for form in [f.replace(" ", "") for f in expected_forms])
    if matched:
        print("  ✓ 输出形式匹配预期之一")
    else:
        print("  ⚠ 输出形式未严格匹配预期，请人工核对")
        print("    （这不一定是错——Mathematica 可能给出等价的不同形式）")


if __name__ == "__main__":
    script_dir = Path(__file__).parent
    json_path = script_dir / "cournot_result.json"
    
    if not json_path.exists():
        print(f"错误：找不到 {json_path}")
        print("请先在 Mathematica 中运行 cournot_test.wl 生成结果文件。")
        exit(1)
    
    result = parse_cournot_result(json_path)
    verify_known_answer(result)
    
    print("\n[OK] Python 解析完成。")