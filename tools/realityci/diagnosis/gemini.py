"""Gemini causal diagnostician over Vertex-genai with structured output.

The model proposes hypotheses and requests experiments ONLY from the
supported intervention registry.  Responses are schema-validated; malformed
or unsupported outputs fail closed and pass through a bounded repair retry.
Root cause remains PROPOSED here regardless of model confidence — only the
deterministic causal gate can establish it.

Set SERVO_GEMINI_MODEL to override the pinned default after verifying
current availability in your project; the default is documented in
docs/REALITYCI_BACKEND.md.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Optional

from ..schemas.diagnosis import HypothesisKind, InterventionName
from ..schemas.run import FailureClass, FailureRecord, RunEvidence
from .base import DiagnosisContext, DiagnosisProposal, Diagnostician, ExperimentRequest


GEMINI_DIAGNOSTICIAN_NAME = "gemini-diagnostician/v1"
PROMPT_TEMPLATE_VERSION = "realityci-diagnosis-prompt/v1"

# Mirrors src/ui/chat/AiChatController.cpp so desktop chat and RealityCI use
# identical model ids and the identical x-goog-api-key credential path.
# Policy: restricted catalog - Gemini 3.6/3.7 flash only. "Batch" is not a
# separate model id: the same ids run through the Batch API (roughly half
# cost, up-to-24h turnaround), which suits offline bulk analysis but NEVER
# the live fail->diagnose loop where hypotheses must return immediately.
MODEL_CATALOG: tuple[str, ...] = (
    "gemini-3.7-flash",
    "gemini-3.6-flash",
)
DEFAULT_MODEL_ID = "gemini-3.7-flash"
ROLE_MODELS: dict[str, str] = {
    "diagnostician": "gemini-3.7-flash",
    "telemetry_compression": "gemini-3.6-flash",
    "second_opinion": "gemini-3.6-flash",
}

MAX_REPAIR_RETRIES = 1
MAX_ATTACHMENT_FRAMES = 4

# Optional reasoning effort control (Gemini 3 thinking levels).
# Unset -> model default behaviour. Set SERVO_GEMINI_THINKING_LEVEL=low|high
# to pin it explicitly; invalid values fail closed rather than being ignored.
THINKING_LEVELS: tuple[str, ...] = ("low", "high")


def configured_thinking_level() -> Optional[str]:
    import os

    level = os.environ.get("SERVO_GEMINI_THINKING_LEVEL", "").strip().lower()
    if not level:
        return None
    if level not in THINKING_LEVELS:
        raise GeminiDiagnosticianError(
            f"SERVO_GEMINI_THINKING_LEVEL must be one of {THINKING_LEVELS}, got {level!r}"
        )
    return level


def model_for_role(role: str) -> str:
    if role not in ROLE_MODELS:
        raise KeyError(f"unknown model role: {role!r} (known: {sorted(ROLE_MODELS)})")
    return ROLE_MODELS[role]


class GeminiDiagnosticianError(RuntimeError):
    pass


class UnsupportedInterventionError(ValueError):
    pass


_SYSTEM_INSTRUCTIONS = (
    "You are the causal diagnostician inside Servo, an autonomous CI/CD "
    "system for physical-AI policies. You receive synchronized run evidence "
    "for one failed scenario execution. Produce ranked competing hypotheses "
    "(perception missed, detected too late, planner failed, controller "
    "failed, occlusion delayed perception) and request counterfactual "
    "experiments selected ONLY from the provided intervention list with "
    "typed parameters. State uncertainty explicitly. Never invent "
    "interventions or parameters outside the allowed ranges."
)

_USER_PROMPT_TEMPLATE = """Failure record:
{failure_json}

Synchronized evidence summary:
{evidence_json}

Supported interventions and parameter bounds:
- remove_occluder {{}}
- reveal_pedestrian_earlier {{delta_seconds: 0.0..5.0}}
- oracle_perception {{}}
- oracle_planner {{}}
- oracle_controller {{}}
- vary_ego_speed {{speed_mps: 1.0..route speed limit}}
- vary_pedestrian_speed {{speed_mps: 0.2..8.0}}

Return hypotheses H1..HN with kind values from: not_detected,
detected_too_late, planner_failed, controller_failed,
occlusion_caused_perception_failure.
"""


def _pydantic_response_schema() -> type:
    from pydantic import BaseModel, ConfigDict, Field

    class GHypothesis(BaseModel):
        model_config = ConfigDict(extra="forbid")

        hypothesis_id: str
        kind: str
        claim: str

    class GExperiment(BaseModel):
        model_config = ConfigDict(extra="forbid")

        intervention: str
        parameters: dict[str, float] = Field(default_factory=dict)
        hypothesis_ids: tuple[str, ...] = ()
        estimated_cost_seconds: float = 6.0

    class GProposal(BaseModel):
        model_config = ConfigDict(extra="forbid")

        summary: str
        hypotheses: tuple[GHypothesis, ...]
        requested_experiments: tuple[GExperiment, ...]

    return GProposal


def _gemini_transport_response_schema() -> type:
    """Gemini-compatible schema without arbitrary-object properties.

    The Gen AI structured-output dialect rejects JSON Schema
    ``additionalProperties``. The canonical diagnostic contract deliberately
    keeps intervention parameters as a dictionary, so the transport carries
    that one field as JSON text and validates it through the canonical model
    before any intervention can execute.
    """

    from pydantic import BaseModel, Field

    class GHypothesisTransport(BaseModel):
        hypothesis_id: str
        kind: str
        claim: str

    class GExperimentTransport(BaseModel):
        intervention: str
        parameters_json: str = "{}"
        hypothesis_ids: tuple[str, ...] = ()
        estimated_cost_seconds: float = 6.0

    class GProposalTransport(BaseModel):
        summary: str
        hypotheses: tuple[GHypothesisTransport, ...]
        requested_experiments: tuple[GExperimentTransport, ...] = Field(
            default_factory=tuple
        )

    return GProposalTransport


def _validate_and_convert(parsed: Any, context: DiagnosisContext) -> DiagnosisProposal:
    allowed = set(context.available_interventions)
    schema = _pydantic_response_schema()

    hypotheses = []
    for h in parsed.hypotheses:
        try:
            kind = HypothesisKind(h.kind)
        except ValueError as exc:
            raise GeminiDiagnosticianError(f"unknown hypothesis kind: {h.kind!r}") from exc
        hypotheses.append(
            CausalHypothesisShim(
                hypothesis_id=h.hypothesis_id, kind=kind, claim=h.claim
            )
        )

    experiments: list[ExperimentRequest] = []
    for e in parsed.requested_experiments:
        try:
            name = InterventionName(e.intervention)
        except ValueError as exc:
            raise UnsupportedInterventionError(f"unsupported intervention: {e.intervention!r}") from exc
        if name not in allowed:
            raise UnsupportedInterventionError(f"intervention not enabled in context: {name.value}")
        experiments.append(
            ExperimentRequest(
                intervention=name,
                parameters=dict(e.parameters),
                hypothesis_ids=tuple(e.hypothesis_ids),
                estimated_cost_seconds=float(e.estimated_cost_seconds),
            )
        )

    return DiagnosisProposal(
        hypotheses=tuple(item.as_record() for item in hypotheses),
        requested_experiments=tuple(experiments),
        summary=parsed.summary,
        diagnostician=GEMINI_DIAGNOSTICIAN_NAME,
    )


class CausalHypothesisShim:
    def __init__(self, hypothesis_id: str, kind: HypothesisKind, claim: str) -> None:
        self.hypothesis_id = hypothesis_id
        self.kind = kind
        self.claim = claim

    def as_record(self):
        from ..schemas.diagnosis import CausalHypothesis

        return CausalHypothesis(
            hypothesis_id=self.hypothesis_id,
            kind=self.kind,
            claim=self.claim,
        )


class GeminiDiagnostician(Diagnostician):
    def __init__(
        self,
        model_id: str = DEFAULT_MODEL_ID,
        client: Any = None,
        temperature: float = 0.2,
    ) -> None:
        self.model_id = model_id
        self.temperature = temperature
        if client is None:
            client = self._build_default_client()
        self._client = client

    @staticmethod
    def _build_default_client() -> Any:
        import os

        try:
            from google import genai
        except ImportError as exc:
            raise GeminiDiagnosticianError(
                "google-genai is required for the Gemini diagnostician"
            ) from exc
        api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        google_api = os.environ.get("SERVO_GOOGLE_API", "").strip().lower()
        use_vertex = (
            google_api in {"vertex", "vertex-ai", "aiplatform"}
            or os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "").strip().lower()
            in {"1", "true", "yes", "on"}
        )
        if api_key:
            # Match Ask Servo's planner transport. Vertex AI Express accepts a
            # Google Cloud API key, while an API key restricted to
            # aiplatform.googleapis.com is correctly rejected by the separate
            # generativelanguage.googleapis.com Developer API endpoint.
            return (
                genai.Client(vertexai=True, api_key=api_key)
                if use_vertex
                else genai.Client(api_key=api_key)
            )
        if os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") or os.environ.get("GOOGLE_CLOUD_PROJECT"):
            if use_vertex:
                return genai.Client(
                    vertexai=True,
                    project=os.environ.get("GOOGLE_CLOUD_PROJECT"),
                    location=os.environ.get("GOOGLE_CLOUD_LOCATION", "global"),
                )
            return genai.Client()
        raise GeminiDiagnosticianError(
            "no Gemini credentials: set GEMINI_API_KEY / GOOGLE_API_KEY or "
            "GOOGLE_APPLICATION_CREDENTIALS for Vertex AI"
        )

    @property
    def name(self) -> str:
        return GEMINI_DIAGNOSTICIAN_NAME

    def propose(
        self,
        evidence: RunEvidence,
        failure: FailureRecord,
        context: DiagnosisContext,
        frame_png_paths: Optional[list[Path]] = None,
    ) -> DiagnosisProposal:
        prompt = _USER_PROMPT_TEMPLATE.format(
            failure_json=failure.model_dump_json(indent=2),
            evidence_json=evidence.body.model_dump_json(indent=2),
        )
        contents: list[Any] = [prompt]
        attachments = []
        for path in (frame_png_paths or [])[:MAX_ATTACHMENT_FRAMES]:
            data = Path(path).read_bytes()
            attachments.append(("image/png", data))
            contents.append({"mime_type": "image/png", "data": data})

        last_error: Exception | None = None
        for attempt in range(1 + MAX_REPAIR_RETRIES):
            raw = self._call_model(contents, attachments)
            response_sha = (
                "sha256:" + hashlib.sha256(json.dumps(raw, sort_keys=True).encode()).hexdigest()
            )
            try:
                proposal = self._parse_and_validate(raw, context)
            except (GeminiDiagnosticianError, UnsupportedInterventionError) as exc:
                last_error = exc
                contents.append(
                    f"Your previous response was rejected: {exc}. "
                    "Return strictly schema-valid JSON using only supported interventions."
                )
                continue
            return DiagnosisProposal(
                hypotheses=proposal.hypotheses,
                requested_experiments=proposal.requested_experiments,
                summary=proposal.summary,
                diagnostician=GEMINI_DIAGNOSTICIAN_NAME,
                model_id=self.model_id,
                prompt_template_version=PROMPT_TEMPLATE_VERSION,
                response_sha256=response_sha,
            )
        raise GeminiDiagnosticianError(f"model output failed validation after retries: {last_error}")

    def _call_model(self, contents: list[Any], attachments: list[tuple[str, bytes]]) -> dict[str, Any]:
        config_kwargs: dict[str, Any] = {
            "temperature": self.temperature,
            "system_instruction": _SYSTEM_INSTRUCTIONS,
            "response_mime_type": "application/json",
            "response_schema": _gemini_transport_response_schema(),
        }
        thinking_level = configured_thinking_level()
        if thinking_level is not None:
            from google.genai import types as genai_types

            config_kwargs["thinking_config"] = genai_types.ThinkingConfig(
                thinking_level=thinking_level
            )
        from google.genai import types

        generation_config = types.GenerateContentConfig(**config_kwargs)
        payload: list[Any] = []
        for item in contents:
            if isinstance(item, dict):
                payload.append(types.Part.from_bytes(data=item["data"], mime_type=item["mime_type"]))
            else:
                payload.append(item)
        response = self._client.models.generate_content(
            model=self.model_id,
            contents=payload,
            config=generation_config,
        )
        text = response.text
        return {"text": text}

    def _parse_and_validate(self, raw: dict[str, Any], context: DiagnosisContext) -> DiagnosisProposal:
        import re

        text = raw.get("text", "")
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            raise GeminiDiagnosticianError("model returned no JSON object")
        schema = _pydantic_response_schema()
        try:
            parsed = schema.model_validate_json(match.group(0))
        except Exception as canonical_exc:
            try:
                transport = _gemini_transport_response_schema().model_validate_json(
                    match.group(0)
                )
                normalized_experiments = []
                for experiment in transport.requested_experiments:
                    parameters = json.loads(experiment.parameters_json or "{}")
                    if not isinstance(parameters, dict):
                        raise ValueError("parameters_json must decode to an object")
                    normalized_experiments.append(
                        {
                            "intervention": experiment.intervention,
                            "parameters": parameters,
                            "hypothesis_ids": experiment.hypothesis_ids,
                            "estimated_cost_seconds": experiment.estimated_cost_seconds,
                        }
                    )
                parsed = schema.model_validate(
                    {
                        "summary": transport.summary,
                        "hypotheses": [
                            hypothesis.model_dump()
                            for hypothesis in transport.hypotheses
                        ],
                        "requested_experiments": normalized_experiments,
                    }
                )
            except Exception as transport_exc:
                raise GeminiDiagnosticianError(
                    "schema validation failed: "
                    f"canonical={canonical_exc}; transport={transport_exc}"
                ) from transport_exc
        return _validate_and_convert(parsed, context)


def build_diagnostician(kind: str, **kwargs: Any) -> Diagnostician:
    if kind == "auto":
        has_credentials = bool(
            os.environ.get("GEMINI_API_KEY")
            or os.environ.get("GOOGLE_API_KEY")
            or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        )
        kind = "gemini" if has_credentials else "deterministic"
    if kind == "deterministic":
        from .deterministic import DeterministicDiagnostician

        return DeterministicDiagnostician()
    if kind == "gemini":
        model_id = kwargs.get("model_id", model_for_role("diagnostician"))
        client = kwargs.get("client")
        return GeminiDiagnostician(model_id=model_id, client=client)
    raise ValueError(f"unknown diagnostician kind: {kind}")
