"""
The SIV Generator: deterministic compilation from validated SIV JSON
extraction to Neo-Davidsonian-compliant FOL.

Input:  SentenceExtraction (already validated by the Neo-Davidsonian validator)
Output: GenerationResult containing either a generated FOL string or a
        refusal record with a specific reason.

The Generator is JSON-only: it receives the structured extraction, not
the source natural language. This is architecturally load-bearing. See
Master Document §5.2.
"""
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from siv.schema import SentenceExtraction, ProblemExtraction
from siv.compiler import validate_neo_davidsonian
from siv.invariants import check_all_invariants

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


@dataclass
class GenerationResult:
    sentence_nl: str        # stored for reporting only; NEVER fed back into the prompt
    fol: Optional[str]
    refused: bool
    refusal_reason: Optional[str]
    refusal_stage: Optional[str]   # "pre_call" | "post_call" | None
    invariant_failures: List[str] = field(default_factory=list)


@dataclass
class BatchGenerationReport:
    problem_id: str
    results: List[GenerationResult]
    num_generated: int
    num_refused_pre_call: int
    num_refused_post_call: int


def _load_generation_prompt() -> str:
    path = _PROMPTS_DIR / "generation_system.txt"
    return path.read_text()


def _load_generation_examples() -> List[dict]:
    path = _PROMPTS_DIR / "generation_examples.json"
    return json.loads(path.read_text())


_SYSTEM_PROMPT: str = _load_generation_prompt()
_EXAMPLES: List[dict] = _load_generation_examples()


def _extraction_to_json_input(sentence: SentenceExtraction) -> dict:
    """
    Convert a SentenceExtraction to the JSON input shape the generation
    prompt expects. This is the ONLY channel through which the Generator
    sees the extraction — the NL sentence is NOT included.
    """
    return {
        "constants": [{"id": c.id, "surface": c.surface} for c in sentence.constants],
        "entities": [
            {"id": e.id, "surface": e.surface, "entity_type": e.entity_type.value}
            for e in sentence.entities
        ],
        "facts": [
            {"pred": f.pred, "args": list(f.args), "negated": f.negated}
            for f in sentence.facts
        ],
        "macro_template": sentence.macro_template.value,
    }


def _build_few_shot_messages() -> List[dict]:
    messages = []
    for ex in _EXAMPLES:
        messages.append({"role": "user", "content": json.dumps(ex["input"])})
        messages.append({"role": "assistant", "content": json.dumps(ex["output"])})
    return messages


def generate_fol(
    sentence: SentenceExtraction,
    frozen_client,
) -> GenerationResult:
    """
    Generate a Neo-Davidsonian FOL string from a sentence extraction.

    Pre-call refusal path: if the extraction has Neo-Davidsonian violations,
    refuse without making an API call.

    Post-call refusal path: if the generated output fails any of the five
    invariants, refuse after the API call with the invariant failure list.
    """
    # Pre-call validation
    wrapped = ProblemExtraction(problem_id="generator_precheck", sentences=[sentence])
    violations = validate_neo_davidsonian(wrapped)
    if violations:
        return GenerationResult(
            sentence_nl=sentence.nl,
            fol=None,
            refused=True,
            refusal_reason=f"Extraction has {len(violations)} Neo-Davidsonian violation(s): "
                           f"{[v.violation_type for v in violations]}",
            refusal_stage="pre_call",
        )

    # Call the frozen client with JSON-only input
    user_content = json.dumps(_extraction_to_json_input(sentence))
    data, _meta = frozen_client.generate(
        system_prompt=_SYSTEM_PROMPT,
        few_shot_messages=_build_few_shot_messages(),
        user_content=user_content,
    )

    fol = data.get("fol")
    if fol is None:
        return GenerationResult(
            sentence_nl=sentence.nl,
            fol=None,
            refused=True,
            refusal_reason=data.get("refusal_reason") or "generator_refused",
            refusal_stage="post_call",
        )

    # Post-call invariant checks
    failures = check_all_invariants(fol, sentence)
    if failures:
        return GenerationResult(
            sentence_nl=sentence.nl,
            fol=None,
            refused=True,
            refusal_reason="invariant_failure",
            refusal_stage="post_call",
            invariant_failures=failures,
        )

    return GenerationResult(
        sentence_nl=sentence.nl,
        fol=fol,
        refused=False,
        refusal_reason=None,
        refusal_stage=None,
    )


def generate_problem(
    extraction: ProblemExtraction,
    frozen_client,
) -> BatchGenerationReport:
    """Generate FOL for every sentence in a problem."""
    results = [generate_fol(s, frozen_client) for s in extraction.sentences]
    return BatchGenerationReport(
        problem_id=extraction.problem_id,
        results=results,
        num_generated=sum(1 for r in results if not r.refused),
        num_refused_pre_call=sum(1 for r in results if r.refusal_stage == "pre_call"),
        num_refused_post_call=sum(1 for r in results if r.refusal_stage == "post_call"),
    )
