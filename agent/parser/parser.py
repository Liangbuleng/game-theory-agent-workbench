"""Stage 1 parser: paper text to GameBasics."""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any, Callable

import yaml
from pydantic import ValidationError

from agent.llm import LLMClient
from agent.llm.conversation import Conversation
from agent.llm.diagnostics import emit_log
from agent.parser.document_loader import LoadResult, load_document
from agent.parser.output_format import (
    STAGE1_EXAMPLE,
    Stage1Output,
    Stage2Output,
    render_compact_stage1_schema_for_prompt,
    render_compact_stage2_schema_for_prompt,
    render_schema_for_prompt,
)
from agent.parser.prompts import (
    BAYESIAN_BACKWARD_INDUCTION_TEMPLATE,
    REPAIR_USER_TEMPLATE,
    STAGE2_REPAIR_USER_TEMPLATE,
    STAGE2_REVISION_USER_TEMPLATE,
    STAGE2_SYSTEM,
    STAGE2_USER_TEMPLATE,
    STAGE1_REVISION_USER_TEMPLATE,
    STAGE1_SYSTEM,
    STAGE1_USER_TEMPLATE,
)
from agent.schemas import GameBasics, GameType, ModelMeta, ModelSpec


class ParseError(Exception):
    """Raised when Stage 1 cannot produce a valid output."""


class Parser:
    """Parser for the redesigned Phase 0 Stage 1 workflow."""

    def __init__(
        self,
        llm_client: LLMClient | None = None,
        max_repair_retries: int = 2,
        output_root: str | Path = "output",
        auto_save: bool = True,
        llm_stream: bool | None = None,
        llm_log: bool | None = None,
    ) -> None:
        self.llm = llm_client or LLMClient(phase="parser")
        self.max_repair_retries = max_repair_retries
        self.output_root = Path(output_root)
        self.auto_save = auto_save
        self.llm_stream = _env_flag("GTA_LLM_STREAM") if llm_stream is None else llm_stream
        self.llm_log = _env_flag("GTA_LLM_LOG") if llm_log is None else llm_log

        self._paper_content: str | None = None
        self._load_result: LoadResult | None = None
        self._stage1_output: Stage1Output | None = None
        self._stage1_output_path: Path | None = None
        self._stage2_output: Stage2Output | None = None
        self._stage2_output_path: Path | None = None
        self._modelspec: ModelSpec | None = None
        self._modelspec_paths: dict[str, Path] = {}

    def parse_stage1(
        self,
        file_path: str | Path,
        *,
        output_dir: str | Path | None = None,
        save: bool | None = None,
    ) -> Stage1Output:
        """Parse a paper/model file into Stage1Output."""

        path = Path(file_path)
        provider_config = self.llm.provider_config
        load_result = load_document(path, provider_config)
        self._load_result = load_result
        paper_content = self._content_blocks_to_text(load_result.content_blocks)

        should_save = self.auto_save if save is None else save
        stage1 = self.parse_stage1_text(paper_content, save=False)
        stage1.basics.source = str(path)
        if should_save:
            self._stage1_output_path = self.save_stage1_output(
                stage1,
                output_dir or self.output_root / path.stem,
            )
        return stage1

    def parse_stage1_text(
        self,
        text: str,
        *,
        output_dir: str | Path | None = None,
        save: bool = False,
    ) -> Stage1Output:
        """Parse plain text or markdown into Stage1Output."""

        self._paper_content = text
        schema_text = render_compact_stage1_schema_for_prompt()
        user_prompt = STAGE1_USER_TEMPLATE.format(
            schema=schema_text,
            example=STAGE1_EXAMPLE,
            paper_content=text,
        )

        conversation = self.llm.new_conversation(system=STAGE1_SYSTEM)
        conversation.add_user(user_prompt)
        if self.llm_log:
            emit_log(
                "[Stage1] prompt_ready "
                f"paper_chars={len(text)} prompt_chars={len(user_prompt)} "
                f"stream={self.llm_stream}"
            )
        raw = conversation.send(stream=self.llm_stream, log=self.llm_log)

        stage1 = self._validate_with_repair(
            raw_output=raw,
            output_class=Stage1Output,
            conversation=conversation,
            cross_validator=lambda obj: obj.assert_valid(),
        )

        self._stage1_output = stage1
        if save and output_dir is not None:
            self._stage1_output_path = self.save_stage1_output(stage1, output_dir)
        return stage1

    def stage1_revise_from_feedback(
        self,
        previous: Stage1Output | None = None,
        *,
        answers: dict[str, str] | None = None,
        free_feedback: str = "",
        paper_content: str | None = None,
        output_dir: str | Path | None = None,
        save: bool | None = None,
    ) -> Stage1Output:
        """Revise a Stage 1 result using user answers and free-form feedback."""

        previous = previous or self._stage1_output
        if previous is None:
            raise ValueError("stage1_revise_from_feedback requires previous output")

        text = paper_content or self._paper_content
        if text is None:
            text = self._load_source_text(previous) or (
                "Original paper text is unavailable. Revise using the previous "
                "Stage1Output and user feedback only."
            )

        schema_text = render_compact_stage1_schema_for_prompt()
        user_prompt = STAGE1_REVISION_USER_TEMPLATE.format(
            schema=schema_text,
            previous_output=previous.model_dump_json(indent=2),
            answers=json.dumps(answers or {}, indent=2, ensure_ascii=False),
            free_feedback=free_feedback or "(No free-form feedback.)",
            paper_content=text,
        )

        conversation = self.llm.new_conversation(system=STAGE1_SYSTEM)
        conversation.add_user(user_prompt)
        if self.llm_log:
            emit_log(
                "[Stage1.5] revision_prompt_ready "
                f"paper_chars={len(text)} prompt_chars={len(user_prompt)} "
                f"stream={self.llm_stream}"
            )
        raw = conversation.send(stream=self.llm_stream, log=self.llm_log)
        revised = self._validate_with_repair(
            raw_output=raw,
            output_class=Stage1Output,
            conversation=conversation,
            cross_validator=lambda obj: obj.assert_valid(),
        )

        self._stage1_output = revised
        should_save = self.auto_save if save is None else save
        target_dir = output_dir or (
            self._stage1_output_path.parent if self._stage1_output_path else None
        )
        if should_save and target_dir is not None:
            self._stage1_output_path = self.save_stage1_output(revised, target_dir)
        return revised

    def stage1_revise_from_json(
        self,
        stage1_json: str | Path | dict[str, Any] | Stage1Output,
        *,
        output_dir: str | Path | None = None,
        save: bool | None = None,
    ) -> Stage1Output:
        """Load a user-edited Stage1Output JSON/JSONC document and validate it."""

        stage1 = self._load_stage1_json_like(stage1_json)
        stage1.assert_valid()
        self._stage1_output = stage1

        should_save = self.auto_save if save is None else save
        target_dir = output_dir or (
            self._stage1_output_path.parent if self._stage1_output_path else None
        )
        if should_save and target_dir is not None:
            self._stage1_output_path = self.save_stage1_output(stage1, target_dir)
        return stage1

    def export_stage1_review_jsonc(
        self,
        stage1: Stage1Output | None = None,
        output_path: str | Path | None = None,
    ) -> str | Path:
        """Export Stage1Output as annotated JSONC for human review/editing."""

        stage1 = stage1 or self._stage1_output
        if stage1 is None:
            raise ValueError("export_stage1_review_jsonc requires Stage1Output")

        text = _render_stage1_review_jsonc(stage1)
        if output_path is None:
            return text

        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def diff_stage1_outputs(
        self,
        old: Stage1Output,
        new: Stage1Output,
        *,
        max_changes: int | None = None,
    ) -> list[dict[str, Any]]:
        """Return a structural path diff between two Stage1Output objects."""

        return diff_stage1_outputs(old, new, max_changes=max_changes)

    def format_stage1_diff_markdown(
        self,
        old: Stage1Output,
        new: Stage1Output,
        *,
        max_changes: int | None = None,
    ) -> str:
        """Return a readable markdown diff between two Stage1Output objects."""

        return format_stage1_diff_markdown(
            self.diff_stage1_outputs(old, new, max_changes=max_changes)
        )

    def confirm_stage1(
        self,
        stage1: Stage1Output | None = None,
        *,
        output_dir: str | Path | None = None,
    ) -> Path:
        """Mark the current Stage 1 result as final and save stage1_final.json."""

        stage1 = stage1 or self._stage1_output
        if stage1 is None:
            raise ValueError("confirm_stage1 requires Stage1Output")
        stage1.assert_valid()

        if output_dir is None:
            if self._stage1_output_path is not None:
                output_dir = self._stage1_output_path.parent
            else:
                output_dir = self.output_root / "stage1"

        self._stage1_output = stage1
        self._stage1_output_path = self.save_stage1_output(
            stage1,
            output_dir,
            final=True,
        )
        return self._stage1_output_path

    def parse_stage2(
        self,
        stage1: Stage1Output | GameBasics | str | Path | None = None,
        *,
        paper_path: str | Path | None = None,
        paper_content: str | None = None,
        output_dir: str | Path | None = None,
        save: bool | None = None,
    ) -> Stage2Output:
        """Generate a structured solving procedure from confirmed GameBasics."""

        basics = self._resolve_game_basics(stage1)
        paper_text = self._resolve_stage2_paper_text(
            basics=basics,
            paper_path=paper_path,
            paper_content=paper_content,
        )
        schema_text = render_compact_stage2_schema_for_prompt()
        solving_template = _solving_template_for_game_type(basics.game_type)
        user_prompt = STAGE2_USER_TEMPLATE.format(
            schema=schema_text,
            game_basics=basics.model_dump_json(indent=2),
            solving_template=solving_template,
            paper_content=paper_text,
        )

        conversation = self.llm.new_conversation(system=STAGE2_SYSTEM)
        conversation.add_user(user_prompt)
        if self.llm_log:
            emit_log(
                "[Stage2] prompt_ready "
                f"paper_chars={len(paper_text)} prompt_chars={len(user_prompt)} "
                f"stream={self.llm_stream}"
            )
        raw = conversation.send(stream=self.llm_stream, log=self.llm_log)

        stage2 = self._validate_with_repair(
            raw_output=raw,
            output_class=Stage2Output,
            conversation=conversation,
            cross_validator=lambda obj: obj.assert_valid(basics),
            schema_text=schema_text,
            repair_template=STAGE2_REPAIR_USER_TEMPLATE,
            log_prefix="[Stage2]",
        )

        self._stage2_output = stage2
        should_save = self.auto_save if save is None else save
        target_dir = output_dir or (
            self._stage1_output_path.parent if self._stage1_output_path else None
        )
        if should_save and target_dir is not None:
            self._stage2_output_path = self.save_stage2_output(stage2, target_dir)
        return stage2

    def stage2_revise_from_feedback(
        self,
        previous: Stage2Output | None = None,
        stage1: Stage1Output | GameBasics | str | Path | None = None,
        *,
        answers: dict[str, str] | None = None,
        free_feedback: str = "",
        paper_path: str | Path | None = None,
        paper_content: str | None = None,
        output_dir: str | Path | None = None,
        save: bool | None = None,
    ) -> Stage2Output:
        """Revise a Stage 2 result using user answers and free-form feedback."""

        previous = previous or self._stage2_output
        if previous is None:
            raise ValueError("stage2_revise_from_feedback requires previous output")

        basics = self._resolve_game_basics(stage1)
        paper_text = self._resolve_stage2_paper_text(
            basics=basics,
            paper_path=paper_path,
            paper_content=paper_content,
        )
        schema_text = render_compact_stage2_schema_for_prompt()
        solving_template = _solving_template_for_game_type(basics.game_type)
        user_prompt = STAGE2_REVISION_USER_TEMPLATE.format(
            schema=schema_text,
            game_basics=basics.model_dump_json(indent=2),
            previous_output=previous.model_dump_json(indent=2),
            answers=json.dumps(answers or {}, indent=2, ensure_ascii=False),
            free_feedback=free_feedback or "(No free-form feedback.)",
            solving_template=solving_template,
            paper_content=paper_text,
        )

        conversation = self.llm.new_conversation(system=STAGE2_SYSTEM)
        conversation.add_user(user_prompt)
        if self.llm_log:
            emit_log(
                "[Stage2.5] revision_prompt_ready "
                f"paper_chars={len(paper_text)} prompt_chars={len(user_prompt)} "
                f"stream={self.llm_stream}"
            )
        raw = conversation.send(stream=self.llm_stream, log=self.llm_log)
        revised = self._validate_with_repair(
            raw_output=raw,
            output_class=Stage2Output,
            conversation=conversation,
            cross_validator=lambda obj: obj.assert_valid(basics),
            schema_text=schema_text,
            repair_template=STAGE2_REPAIR_USER_TEMPLATE,
            log_prefix="[Stage2.5]",
        )

        self._stage2_output = revised
        should_save = self.auto_save if save is None else save
        target_dir = output_dir or (
            self._stage2_output_path.parent
            if self._stage2_output_path is not None
            else (
                self._stage1_output_path.parent
                if self._stage1_output_path is not None
                else None
            )
        )
        if should_save and target_dir is not None:
            self._stage2_output_path = self.save_stage2_output(revised, target_dir)
        return revised

    def stage2_revise_from_json(
        self,
        stage2_json: str | Path | dict[str, Any] | Stage2Output,
        stage1: Stage1Output | GameBasics | str | Path | None = None,
        *,
        output_dir: str | Path | None = None,
        save: bool | None = None,
    ) -> Stage2Output:
        """Load a user-edited Stage2Output JSON/JSONC document and validate it."""

        stage2 = self._load_stage2_json_like(stage2_json)
        basics = self._resolve_game_basics(stage1)
        stage2.assert_valid(basics)
        self._stage2_output = stage2

        should_save = self.auto_save if save is None else save
        target_dir = output_dir or (
            self._stage2_output_path.parent
            if self._stage2_output_path is not None
            else (
                self._stage1_output_path.parent
                if self._stage1_output_path is not None
                else None
            )
        )
        if should_save and target_dir is not None:
            self._stage2_output_path = self.save_stage2_output(stage2, target_dir)
        return stage2

    def export_stage2_review_jsonc(
        self,
        stage2: Stage2Output | None = None,
        output_path: str | Path | None = None,
    ) -> str | Path:
        """Export Stage2Output as annotated JSONC for human review/editing."""

        stage2 = stage2 or self._stage2_output
        if stage2 is None:
            raise ValueError("export_stage2_review_jsonc requires Stage2Output")

        text = _render_stage2_review_jsonc(stage2)
        if output_path is None:
            return text

        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def diff_stage2_outputs(
        self,
        old: Stage2Output,
        new: Stage2Output,
        *,
        max_changes: int | None = None,
    ) -> list[dict[str, Any]]:
        """Return a structural path diff between two Stage2Output objects."""

        return diff_stage2_outputs(old, new, max_changes=max_changes)

    def format_stage2_diff_markdown(
        self,
        old: Stage2Output,
        new: Stage2Output,
        *,
        max_changes: int | None = None,
    ) -> str:
        """Return a readable markdown diff between two Stage2Output objects."""

        return format_stage2_diff_markdown(
            self.diff_stage2_outputs(old, new, max_changes=max_changes)
        )

    def save_stage2_output(
        self,
        stage2: Stage2Output,
        output_dir: str | Path,
        *,
        final: bool = False,
    ) -> Path:
        """Save Stage 2 output as versioned JSON."""

        directory = Path(output_dir)
        directory.mkdir(parents=True, exist_ok=True)
        if final:
            path = directory / "stage2_final.json"
        else:
            path = self._next_version_path(directory, "stage2_output", ".json")
        path.write_text(stage2.model_dump_json(indent=2), encoding="utf-8")
        return path

    def confirm_stage2(
        self,
        stage2: Stage2Output | None = None,
        *,
        basics: GameBasics | None = None,
        output_dir: str | Path | None = None,
    ) -> Path:
        """Mark the current Stage 2 result as final and save stage2_final.json."""

        stage2 = stage2 or self._stage2_output
        if stage2 is None:
            raise ValueError("confirm_stage2 requires Stage2Output")
        resolved_basics = basics or self._resolve_game_basics(None)
        stage2.assert_valid(resolved_basics)

        if output_dir is None:
            if self._stage2_output_path is not None:
                output_dir = self._stage2_output_path.parent
            elif self._stage1_output_path is not None:
                output_dir = self._stage1_output_path.parent
            else:
                output_dir = self.output_root / "stage2"

        self._stage2_output = stage2
        self._stage2_output_path = self.save_stage2_output(
            stage2,
            output_dir,
            final=True,
        )
        return self._stage2_output_path

    def finalize(
        self,
        stage1: Stage1Output | str | Path | None = None,
        stage2: Stage2Output | str | Path | None = None,
        *,
        output_dir: str | Path | None = None,
        save: bool = True,
        save_json: bool = True,
        allow_optional_basics_revision_suggestions: bool = True,
    ) -> ModelSpec:
        """Build and optionally save the final Phase 0 ModelSpec artifact."""

        stage1_output = self._resolve_stage1_output(stage1)
        stage2_output = self._resolve_stage2_output(stage2)
        spec = self.build_modelspec(
            stage1_output,
            stage2_output,
            allow_optional_basics_revision_suggestions=(
                allow_optional_basics_revision_suggestions
            ),
        )

        self._modelspec = spec
        if save:
            target_dir = output_dir
            if target_dir is None:
                if self._stage2_output_path is not None:
                    target_dir = self._stage2_output_path.parent
                elif self._stage1_output_path is not None:
                    target_dir = self._stage1_output_path.parent
                else:
                    target_dir = self.output_root / "modelspec"
            self._modelspec_paths = self.save_modelspec(
                spec,
                target_dir,
                save_json=save_json,
            )
        return spec

    def build_modelspec(
        self,
        stage1: Stage1Output,
        stage2: Stage2Output,
        *,
        allow_optional_basics_revision_suggestions: bool = True,
    ) -> ModelSpec:
        """Merge confirmed Stage 1 and Stage 2 outputs into ModelSpec."""

        blocking_suggestions = [
            suggestion
            for suggestion in stage2.basics_revision_suggestions
            if suggestion.severity in {"material", "blocking"}
        ]
        optional_suggestions = [
            suggestion
            for suggestion in stage2.basics_revision_suggestions
            if suggestion.severity == "optional"
        ]

        if blocking_suggestions:
            formatted = "\n  - ".join(
                f"{item.field_path}: {item.issue}" for item in blocking_suggestions
            )
            raise ValueError(
                "Cannot finalize ModelSpec while material/blocking Stage 1 "
                f"revision suggestions remain:\n  - {formatted}"
            )

        if optional_suggestions and not allow_optional_basics_revision_suggestions:
            formatted = "\n  - ".join(
                f"{item.field_path}: {item.issue}" for item in optional_suggestions
            )
            raise ValueError(
                "Cannot finalize ModelSpec while Stage 1 revision suggestions "
                f"remain:\n  - {formatted}"
            )

        implicit_assumptions = list(stage1.implicit_assumptions)
        for suggestion in optional_suggestions:
            implicit_assumptions.append(
                "Optional Stage 1 revision suggestion left unresolved: "
                f"{suggestion.field_path} - {suggestion.issue} "
                f"(suggested_change: {suggestion.suggested_change})"
            )

        spec = ModelSpec(
            basics=stage1.basics,
            procedure=stage2.procedure,
            research_questions=stage2.research_questions,
            meta=ModelMeta(
                implicit_assumptions=implicit_assumptions,
                field_confidence=[
                    *stage1.field_confidence,
                    *stage2.field_confidence,
                ],
                version="modelspec-v1",
            ),
        )
        spec.assert_valid()
        return spec

    def save_modelspec(
        self,
        spec: ModelSpec,
        output_dir: str | Path,
        *,
        save_json: bool = True,
    ) -> dict[str, Path]:
        """Save final ModelSpec as YAML and optionally JSON."""

        spec.assert_valid()
        directory = Path(output_dir)
        directory.mkdir(parents=True, exist_ok=True)

        paths: dict[str, Path] = {}
        yaml_path = directory / "modelspec_final.yaml"
        yaml_text = yaml.safe_dump(
            spec.model_dump(mode="json"),
            sort_keys=False,
            allow_unicode=True,
        )
        yaml_path.write_text(yaml_text, encoding="utf-8")
        paths["yaml"] = yaml_path

        if save_json:
            json_path = directory / "modelspec_final.json"
            json_path.write_text(spec.model_dump_json(indent=2), encoding="utf-8")
            paths["json"] = json_path

        return paths

    def save_stage1_output(
        self,
        stage1: Stage1Output,
        output_dir: str | Path,
        *,
        final: bool = False,
    ) -> Path:
        """Save Stage 1 output as versioned JSON."""

        directory = Path(output_dir)
        directory.mkdir(parents=True, exist_ok=True)
        if final:
            path = directory / "stage1_final.json"
        else:
            path = self._next_version_path(directory, "stage1_output", ".json")
        path.write_text(stage1.model_dump_json(indent=2), encoding="utf-8")
        return path

    @staticmethod
    def _next_version_path(directory: Path, stem: str, suffix: str) -> Path:
        for version in range(1, 10_000):
            candidate = directory / f"{stem}_v{version}{suffix}"
            if not candidate.exists():
                return candidate
        raise RuntimeError(f"could not allocate versioned path in {directory}")

    def _validate_with_repair(
        self,
        raw_output: str,
        output_class: type,
        conversation: Conversation,
        cross_validator: Callable[[object], None] | None = None,
        schema_text: str | None = None,
        repair_template: str = REPAIR_USER_TEMPLATE,
        log_prefix: str = "[Stage1]",
    ):
        cleaned = self._strip_json_fences(raw_output)
        last_raw = cleaned
        last_error: Exception | None = None
        schema_text = schema_text or render_compact_stage1_schema_for_prompt()

        for attempt in range(self.max_repair_retries + 1):
            try:
                if self.llm_log:
                    emit_log(
                        f"{log_prefix} validation_attempt={attempt + 1} "
                        f"raw_chars={len(last_raw)}"
                    )
                start = time.perf_counter()
                parsed = output_class.model_validate_json(last_raw)
                if cross_validator:
                    cross_validator(parsed)
                if self.llm_log:
                    emit_log(
                        f"{log_prefix} validation_ok "
                        f"elapsed={time.perf_counter() - start:.2f}s",
                    )
                return parsed
            except (ValidationError, json.JSONDecodeError, ValueError) as error:
                last_error = error
                if attempt >= self.max_repair_retries:
                    break

                if self.llm_log:
                    emit_log(
                        f"{log_prefix} validation_failed "
                        f"{type(error).__name__}: {self._format_validation_error(error)[:1000]}",
                    )
                repair_prompt = repair_template.format(
                    previous_output=last_raw[:12000],
                    validation_errors=self._format_validation_error(error),
                    schema=schema_text,
                )
                conversation.add_user(repair_prompt)
                last_raw = self._strip_json_fences(
                    conversation.send(stream=self.llm_stream, log=self.llm_log)
                )

        raise ParseError(
            f"Stage 1 output failed validation after "
            f"{self.max_repair_retries + 1} attempts.\n"
            f"Last error: {last_error}\n"
            f"Last output prefix: {last_raw[:1000]}"
        )

    @staticmethod
    def _strip_json_fences(text: str) -> str:
        text = text.strip()
        match = re.match(r"^```(?:json)?\s*\n?(.*?)\n?```$", text, re.DOTALL)
        if match:
            return match.group(1).strip()
        return text

    @staticmethod
    def _format_validation_error(error: Exception) -> str:
        if isinstance(error, ValidationError):
            lines = []
            for item in error.errors():
                loc = ".".join(str(part) for part in item["loc"])
                lines.append(f"- {loc}: [{item.get('type', '')}] {item['msg']}")
            return "\n".join(lines)
        if isinstance(error, json.JSONDecodeError):
            return (
                f"JSON parse failed: {error.msg} "
                f"(line {error.lineno}, column {error.colno})"
            )
        return str(error)

    @staticmethod
    def _content_blocks_to_text(blocks: list[dict]) -> str:
        texts = []
        for block in blocks:
            if block.get("type") == "text":
                texts.append(block.get("text", ""))
            else:
                raise NotImplementedError(
                    "Stage 1 currently requires text or markdown input. "
                    "Preprocess PDF/image files into markdown before parsing."
                )
        return "\n\n".join(texts)

    def _load_source_text(self, previous: Stage1Output) -> str | None:
        source = previous.basics.source
        if not source:
            return None
        path = Path(source)
        if not path.exists():
            return None
        load_result = load_document(path, self.llm.provider_config)
        return self._content_blocks_to_text(load_result.content_blocks)

    @staticmethod
    def _load_stage1_json_like(
        stage1_json: str | Path | dict[str, Any] | Stage1Output,
    ) -> Stage1Output:
        if isinstance(stage1_json, Stage1Output):
            return stage1_json
        if isinstance(stage1_json, dict):
            return Stage1Output.model_validate(stage1_json)

        if isinstance(stage1_json, Path):
            text = stage1_json.read_text(encoding="utf-8")
        else:
            looks_like_json = stage1_json.lstrip().startswith(("{", "["))
            possible_path = Path(stage1_json) if not looks_like_json else None
            if (
                possible_path is not None
                and "\n" not in stage1_json
                and possible_path.exists()
            ):
                text = possible_path.read_text(encoding="utf-8")
            else:
                text = stage1_json

        return Stage1Output.model_validate_json(strip_jsonc_comments(text))

    @staticmethod
    def _load_stage2_json_like(
        stage2_json: str | Path | dict[str, Any] | Stage2Output,
    ) -> Stage2Output:
        if isinstance(stage2_json, Stage2Output):
            return stage2_json
        if isinstance(stage2_json, dict):
            return Stage2Output.model_validate(stage2_json)

        if isinstance(stage2_json, Path):
            text = stage2_json.read_text(encoding="utf-8")
        else:
            looks_like_json = stage2_json.lstrip().startswith(("{", "["))
            possible_path = Path(stage2_json) if not looks_like_json else None
            if (
                possible_path is not None
                and "\n" not in stage2_json
                and possible_path.exists()
            ):
                text = possible_path.read_text(encoding="utf-8")
            else:
                text = stage2_json

        return Stage2Output.model_validate_json(strip_jsonc_comments(text))

    def _resolve_stage1_output(
        self,
        stage1: Stage1Output | str | Path | None,
    ) -> Stage1Output:
        if isinstance(stage1, Stage1Output):
            stage1.assert_valid()
            self._stage1_output = stage1
            return stage1
        if isinstance(stage1, (str, Path)):
            stage1_output = self._load_stage1_json_like(stage1)
            stage1_output.assert_valid()
            self._stage1_output = stage1_output
            return stage1_output
        if self._stage1_output is not None:
            self._stage1_output.assert_valid()
            return self._stage1_output
        raise ValueError("finalize requires confirmed Stage1Output")

    def _resolve_stage2_output(
        self,
        stage2: Stage2Output | str | Path | None,
    ) -> Stage2Output:
        if isinstance(stage2, Stage2Output):
            self._stage2_output = stage2
            return stage2
        if isinstance(stage2, (str, Path)):
            stage2_output = self._load_stage2_json_like(stage2)
            self._stage2_output = stage2_output
            return stage2_output
        if self._stage2_output is not None:
            return self._stage2_output
        raise ValueError("finalize requires confirmed Stage2Output")

    def _resolve_game_basics(
        self,
        stage1: Stage1Output | GameBasics | str | Path | None,
    ) -> GameBasics:
        if isinstance(stage1, GameBasics):
            basics = stage1
        elif isinstance(stage1, Stage1Output):
            basics = stage1.basics
            self._stage1_output = stage1
        elif isinstance(stage1, (str, Path)):
            stage1_output = self._load_stage1_json_like(stage1)
            self._stage1_output = stage1_output
            basics = stage1_output.basics
        elif self._stage1_output is not None:
            basics = self._stage1_output.basics
        else:
            raise ValueError(
                "parse_stage2 requires confirmed Stage1Output or GameBasics"
            )

        basics.assert_valid()
        return basics

    def _resolve_stage2_paper_text(
        self,
        *,
        basics: GameBasics,
        paper_path: str | Path | None,
        paper_content: str | None,
    ) -> str:
        if paper_content is not None:
            return paper_content
        if paper_path is not None:
            load_result = load_document(Path(paper_path), self.llm.provider_config)
            return self._content_blocks_to_text(load_result.content_blocks)
        if self._paper_content is not None:
            return self._paper_content
        if basics.source:
            path = Path(basics.source)
            if path.exists():
                load_result = load_document(path, self.llm.provider_config)
                return self._content_blocks_to_text(load_result.content_blocks)
        return (
            "Original paper text is unavailable. Generate Stage 2 using only "
            "confirmed GameBasics; mark inferred details with field_confidence."
        )


def parse_stage1(
    file_path: str | Path,
    *,
    llm_client: LLMClient | None = None,
    output_dir: str | Path | None = None,
    save: bool | None = None,
) -> Stage1Output:
    parser = Parser(llm_client=llm_client)
    return parser.parse_stage1(file_path, output_dir=output_dir, save=save)


def parse_stage1_text(
    text: str,
    *,
    llm_client: LLMClient | None = None,
) -> Stage1Output:
    parser = Parser(llm_client=llm_client, auto_save=False)
    return parser.parse_stage1_text(text)


def parse_stage2(
    stage1: Stage1Output | GameBasics | str | Path,
    *,
    llm_client: LLMClient | None = None,
    paper_path: str | Path | None = None,
    paper_content: str | None = None,
    output_dir: str | Path | None = None,
    save: bool | None = None,
) -> Stage2Output:
    parser = Parser(llm_client=llm_client)
    return parser.parse_stage2(
        stage1,
        paper_path=paper_path,
        paper_content=paper_content,
        output_dir=output_dir,
        save=save,
    )


def finalize(
    stage1: Stage1Output | str | Path,
    stage2: Stage2Output | str | Path,
    *,
    output_dir: str | Path | None = None,
    save: bool = True,
    save_json: bool = True,
    allow_optional_basics_revision_suggestions: bool = True,
) -> ModelSpec:
    parser = Parser(auto_save=False)
    return parser.finalize(
        stage1,
        stage2,
        output_dir=output_dir,
        save=save,
        save_json=save_json,
        allow_optional_basics_revision_suggestions=(
            allow_optional_basics_revision_suggestions
        ),
    )


def diff_stage1_outputs(
    old: Stage1Output,
    new: Stage1Output,
    *,
    max_changes: int | None = None,
) -> list[dict[str, Any]]:
    """Return structural differences between two Stage1Output objects."""

    changes: list[dict[str, Any]] = []
    old_data = old.model_dump(mode="json")
    new_data = new.model_dump(mode="json")
    _diff_json_values("$", old_data, new_data, changes, max_changes)
    return changes


def format_stage1_diff_markdown(changes: list[dict[str, Any]]) -> str:
    """Render structural Stage 1 changes as markdown."""

    return _format_diff_markdown(changes, title="Stage 1 Changes")


def diff_stage2_outputs(
    old: Stage2Output,
    new: Stage2Output,
    *,
    max_changes: int | None = None,
) -> list[dict[str, Any]]:
    """Return structural differences between two Stage2Output objects."""

    changes: list[dict[str, Any]] = []
    old_data = old.model_dump(mode="json")
    new_data = new.model_dump(mode="json")
    _diff_json_values("$", old_data, new_data, changes, max_changes)
    return changes


def format_stage2_diff_markdown(changes: list[dict[str, Any]]) -> str:
    """Render structural Stage 2 changes as markdown."""

    return _format_diff_markdown(changes, title="Stage 2 Changes")


def _format_diff_markdown(changes: list[dict[str, Any]], *, title: str) -> str:
    if not changes:
        return f"No {title.lower()}."

    lines = [f"# {title}", ""]
    for change in changes:
        lines.append(f"- `{change['path']}`: {change['type']}")
        if change["type"] == "changed":
            lines.append(f"  - old: `{_short_json(change['old'])}`")
            lines.append(f"  - new: `{_short_json(change['new'])}`")
        elif change["type"] == "added":
            lines.append(f"  - new: `{_short_json(change['new'])}`")
        elif change["type"] == "removed":
            lines.append(f"  - old: `{_short_json(change['old'])}`")
    return "\n".join(lines)


def strip_jsonc_comments(text: str) -> str:
    """Remove // and /* */ comments from JSONC while preserving strings."""

    result: list[str] = []
    i = 0
    in_string = False
    escaped = False
    while i < len(text):
        char = text[i]
        next_char = text[i + 1] if i + 1 < len(text) else ""

        if in_string:
            result.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            i += 1
            continue

        if char == '"':
            in_string = True
            result.append(char)
            i += 1
            continue

        if char == "/" and next_char == "/":
            i += 2
            while i < len(text) and text[i] not in "\r\n":
                i += 1
            continue

        if char == "/" and next_char == "*":
            i += 2
            while i + 1 < len(text) and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i += 2
            continue

        result.append(char)
        i += 1

    return "".join(result)


def _env_flag(name: str) -> bool:
    value = os.environ.get(name, "")
    return value.lower() in {"1", "true", "yes", "on"}


def _render_stage1_review_jsonc(stage1: Stage1Output) -> str:
    json_text = stage1.model_dump_json(indent=2)
    lines = [
        "// Stage1Output review JSONC.",
        "// Edit values carefully, then load it with stage1_revise_from_json().",
        "// Machine artifacts are saved as strict JSON; comments are for review only.",
        "// Reference ids matter: player ids, decision variable names, random",
        "// variable names, demand names, and scenario axis values must stay",
        "// consistent across the whole document.",
    ]
    for line in json_text.splitlines():
        stripped = line.strip()
        comments = _jsonc_comments_for_line(stripped)
        indent = line[: len(line) - len(line.lstrip())]
        lines.extend(f"{indent}// {comment}" for comment in comments)
        lines.append(line)
    return "\n".join(lines) + "\n"


def _render_stage2_review_jsonc(stage2: Stage2Output) -> str:
    json_text = stage2.model_dump_json(indent=2)
    lines = [
        "// Stage2Output review JSONC.",
        "// Edit values carefully, then load it with stage2_revise_from_json().",
        "// Machine artifacts are saved as strict JSON; comments are for review only.",
        "// Stage 2 may revise solving procedure, scenario details, research",
        "// questions, confidence notes, and Stage 2 clarification questions.",
        "// Do not change Stage 1 ids here. If GameBasics is wrong, add or keep a",
        "// basics_revision_suggestions item and go back to Stage 1.",
    ]
    for line in json_text.splitlines():
        stripped = line.strip()
        comments = _stage2_jsonc_comments_for_line(stripped)
        indent = line[: len(line) - len(line.lstrip())]
        lines.extend(f"{indent}// {comment}" for comment in comments)
        lines.append(line)
    return "\n".join(lines) + "\n"


def _jsonc_comments_for_line(stripped: str) -> list[str]:
    if stripped.startswith('"basics":'):
        return ["basics contains Stage 1 game facts only."]
    if stripped.startswith('"game_type":'):
        return ["game_type controls later solver routing."]
    if stripped.startswith('"players":'):
        return ["players[].id is referenced by owners, deciders, payers, payees."]
    if stripped.startswith('"decision_variables":'):
        return ["decision variable names are used by timing and formulas."]
    if stripped.startswith('"parameters":'):
        return ["do not duplicate random variable names here."]
    if stripped.startswith('"information_structure":'):
        return ["random variable knowledge belongs here; action observation is separate."]
    if stripped.startswith('"decision_timing":'):
        return [
            "each decision must list chosen variables, within-stage order, observed prior variables, and decision role."
        ]
    if stripped.startswith('"demands":'):
        return ["payoff formulas must reference these demand/equation names exactly."]
    if stripped.startswith('"payoff_components":'):
        return ["atomic payoff terms used later to assemble full objectives."]
    if stripped.startswith('"contract_terms":'):
        return ["fixed or contract-level terms only; sales-dependent terms are payoff components."]
    if stripped.startswith('"scenario_axes":'):
        return ["generic dimensions of scenario comparison."]
    if stripped.startswith('"scenario_overview":'):
        return ["scenario ids and axis values only; detailed overrides come in Stage 2."]
    if stripped.startswith('"clarification_questions":'):
        return ["unresolved user review questions; keep at most 8."]
    if stripped.startswith('"field_confidence":'):
        return ["mark inferred or uncertain fields so users know what to inspect."]
    if stripped.startswith('"implicit_assumptions":'):
        return ["assumptions not directly encoded elsewhere."]
    return []


def _stage2_jsonc_comments_for_line(stripped: str) -> list[str]:
    if stripped.startswith('"procedure":'):
        return ["procedure contains the Stage 2 solving program only."]
    if stripped.startswith('"method":'):
        return ["solver routing method; must match confirmed GameBasics.game_type."]
    if stripped.startswith('"solving_stages":'):
        return ["ordered solving steps, usually backward-induction order."]
    if stripped.startswith('"stage_id":'):
        return ["stable id used by scenario_details.informed_overrides."]
    if stripped.startswith('"solve_type":'):
        return ["FOC, optimization, enumeration, or discrete payoff-matrix logic."]
    if stripped.startswith('"deciders":'):
        return ["players and decision variables solved in this stage."]
    if stripped.startswith('"profit_function_assignments":'):
        return ["payoff component ids from confirmed GameBasics, grouped by player."]
    if stripped.startswith('"uses_demands":'):
        return ["demand/equation names from confirmed GameBasics."]
    if stripped.startswith('"uses_contract_terms":'):
        return ["contract terms used here; pricing FOC should normally omit them."]
    if stripped.startswith('"expectation_handling":'):
        return [
            "use mixed_by_scenario when player information differs across scenarios."
        ]
    if stripped.startswith('"uses_previous_stage_results":'):
        return ["stage ids or result labels this step substitutes or compares."]
    if stripped.startswith('"scenario_details":'):
        return ["must cover every scenario id from confirmed GameBasics."]
    if stripped.startswith('"informed_overrides":'):
        return ["stage_id -> player_id -> random variables known in that scenario."]
    if stripped.startswith('"active_demands":'):
        return ["demands active in this scenario."]
    if stripped.startswith('"active_payoff_components":'):
        return ["payoff components active in this scenario."]
    if stripped.startswith('"active_contract_terms":'):
        return ["contract terms active in this scenario."]
    if stripped.startswith('"research_questions":'):
        return ["paper-level questions this solving program should answer."]
    if stripped.startswith('"basics_revision_suggestions":'):
        return ["possible Stage 1 corrections; not normal Stage 2 feedback."]
    if stripped.startswith('"clarification_questions":'):
        return ["unresolved Stage 2 review questions; keep at most 8."]
    if stripped.startswith('"field_confidence":'):
        return ["mark inferred or uncertain Stage 2 fields for review."]
    return []


def _diff_json_values(
    path: str,
    old: Any,
    new: Any,
    changes: list[dict[str, Any]],
    max_changes: int | None,
) -> None:
    if max_changes is not None and len(changes) >= max_changes:
        return

    if isinstance(old, dict) and isinstance(new, dict):
        keys = sorted(set(old) | set(new))
        for key in keys:
            child_path = f"{path}.{key}" if path != "$" else key
            if key not in old:
                changes.append({"path": child_path, "type": "added", "new": new[key]})
            elif key not in new:
                changes.append(
                    {"path": child_path, "type": "removed", "old": old[key]}
                )
            else:
                _diff_json_values(
                    child_path,
                    old[key],
                    new[key],
                    changes,
                    max_changes,
                )
            if max_changes is not None and len(changes) >= max_changes:
                return
        return

    if isinstance(old, list) and isinstance(new, list):
        shared = min(len(old), len(new))
        for index in range(shared):
            _diff_json_values(
                f"{path}[{index}]",
                old[index],
                new[index],
                changes,
                max_changes,
            )
            if max_changes is not None and len(changes) >= max_changes:
                return
        for index in range(shared, len(old)):
            changes.append({"path": f"{path}[{index}]", "type": "removed", "old": old[index]})
            if max_changes is not None and len(changes) >= max_changes:
                return
        for index in range(shared, len(new)):
            changes.append({"path": f"{path}[{index}]", "type": "added", "new": new[index]})
            if max_changes is not None and len(changes) >= max_changes:
                return
        return

    if old != new:
        changes.append({"path": path, "type": "changed", "old": old, "new": new})


def _short_json(value: Any, max_chars: int = 220) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    if len(text) > max_chars:
        return text[: max_chars - 3] + "..."
    return text


def _solving_template_for_game_type(game_type: GameType) -> str:
    if game_type == GameType.BAYESIAN_BACKWARD_INDUCTION:
        return BAYESIAN_BACKWARD_INDUCTION_TEMPLATE
    return (
        "No specialized template is implemented for this game_type yet. "
        "If unsupported, set method to unsupported and ask clarification "
        "questions about the required solving approach."
    )
