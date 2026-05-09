"""Manual smoke test for Stage 1 with a simple Cournot description."""

from agent.parser import Parser


SIMPLE_GAME = """
# Simple Cournot duopoly

Two firms F1 and F2 produce a homogeneous good. Market inverse demand is
P = a - q1 - q2, where a > 0. Firm i has marginal cost ci.

The firms simultaneously choose quantities q1 and q2 to maximize profit:
- F1 profit: (P - c1) * q1
- F2 profit: (P - c2) * q2
"""


def main():
    parser = Parser(auto_save=False)
    stage1 = parser.parse_stage1_text(SIMPLE_GAME)

    basics = stage1.basics
    print(stage1.summary_markdown())
    basics.assert_valid()
    print("\n[OK] Stage 1 cross-reference validation passed.")


if __name__ == "__main__":
    main()
