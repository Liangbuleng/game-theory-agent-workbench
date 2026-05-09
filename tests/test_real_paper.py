"""Manual Stage 1 run for the real paper markdown."""

from pathlib import Path

from agent.parser import Parser


def main():
    parser = Parser(auto_save=False)
    paper_path = "output/model_pandoc.md"

    stage1 = parser.parse_stage1(paper_path, output_dir="output/real_paper", save=True)
    print(stage1.summary_markdown())

    Path("output/real_paper").mkdir(parents=True, exist_ok=True)
    final_path = parser.save_stage1_output(
        stage1,
        output_dir="output/real_paper",
        final=True,
    )
    print(f"\n[Saved] {final_path}")


if __name__ == "__main__":
    main()
