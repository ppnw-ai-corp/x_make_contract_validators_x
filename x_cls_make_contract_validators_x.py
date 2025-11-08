"""JSON contract validation CLI and helpers."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal, Protocol, TypeAlias, TypedDict, cast

from x_make_common_x.json_contracts import validate_schema as _common_validate_schema

SCHEMA_VERSION: Final[str] = "x_make_contract_validators_x.run/1.0"


class RunSuccess(TypedDict):
    status: Literal["success"]
    schema_version: str
    issues: list[dict[str, object]]
    message: str


class RunFailure(TypedDict):
    status: Literal["failure"]
    schema_version: str
    error_type: str
    issues: list[dict[str, object]]
    message: str


RunResult: TypeAlias = RunSuccess | RunFailure


class _DraftValidatorProtocol(Protocol):
    @classmethod
    def check_schema(cls, schema: Mapping[str, object]) -> None: ...

    def __init__(self, schema: Mapping[str, object]) -> None: ...

    def iter_errors(self, instance: object) -> Iterable[object]: ...


def _load_validator() -> type[_DraftValidatorProtocol]:
    try:
        from jsonschema.validators import Draft202012Validator
    except ImportError as exc:  # pragma: no cover - dependency missing
        message = "jsonschema Draft202012Validator is unavailable"
        raise RuntimeError(message) from exc
    return cast("type[_DraftValidatorProtocol]", Draft202012Validator)


_DRAFT_VALIDATOR: Final[type[_DraftValidatorProtocol]] = _load_validator()


@dataclass(slots=True)
class _CliArgs:
    schema_path: str
    payload_path: str
    emit_json: bool


@dataclass(slots=True)
class ValidationIssue:
    message: str
    path: tuple[object, ...]
    schema_path: tuple[object, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "message": self.message,
            "path": list(self.path),
            "schema_path": list(self.schema_path),
        }


@dataclass(slots=True)
class ValidationResult:
    success: bool
    issues: tuple[ValidationIssue, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "success": self.success,
            "issues": [issue.to_dict() for issue in self.issues],
        }


class SchemaValidationError(RuntimeError):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class ContractValidationError(RuntimeError):
    def __init__(self, issues: Sequence[ValidationIssue]) -> None:
        message = issues[0].message if issues else "Payload failed validation"
        super().__init__(message)
        self.issues = tuple(issues)


def validate_schema(schema: Mapping[str, object]) -> None:
    try:
        _common_validate_schema(schema)
    except Exception as exc:
        raise SchemaValidationError(str(exc)) from exc


def validate_payload(payload: object, schema: Mapping[str, object]) -> ValidationResult:
    validator = _DRAFT_VALIDATOR(dict(schema))
    issues = tuple(_build_issue(err) for err in validator.iter_errors(payload))
    if issues:
        raise ContractValidationError(issues)
    return ValidationResult(success=True, issues=())


def _normalize_sequence(value: object) -> tuple[object, ...]:
    if isinstance(value, Iterable) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(value)
    return ()


def _build_issue(error: object) -> ValidationIssue:
    message_obj = cast("object", getattr(error, "message", "Validation failed"))
    message = str(message_obj)
    path_attr = cast("object", getattr(error, "path", ()))
    schema_attr = cast("object", getattr(error, "schema_path", ()))
    path = _normalize_sequence(path_attr)
    schema_path = _normalize_sequence(schema_attr)
    return ValidationIssue(message=message, path=path, schema_path=schema_path)


def run(payload: Mapping[str, object]) -> RunResult:
    parameters_obj = payload.get("parameters")
    if not isinstance(parameters_obj, Mapping):
        message = "Payload parameters must be a mapping"
        raise TypeError(message)
    parameters = cast("Mapping[str, object]", parameters_obj)
    schema = _resolve_schema(parameters)
    try:
        validate_schema(schema)
    except SchemaValidationError as exc:
        return _failure_result("schema", str(exc), ())
    candidate = _resolve_payload(parameters)
    try:
        result = validate_payload(candidate, schema)
    except ContractValidationError as exc:
        return _failure_result("payload", str(exc), exc.issues)
    success: RunSuccess = {
        "status": "success",
        "schema_version": SCHEMA_VERSION,
        "issues": [issue.to_dict() for issue in result.issues],
        "message": "Payload matches schema",
    }
    return success


def _failure_result(
    error_type: str,
    message: str,
    issues: Sequence[ValidationIssue],
) -> RunFailure:
    return {
        "status": "failure",
        "schema_version": SCHEMA_VERSION,
        "error_type": error_type,
        "message": message,
        "issues": [issue.to_dict() for issue in issues],
    }


def _resolve_schema(parameters: Mapping[str, object]) -> dict[str, object]:
    if "schema" in parameters:
        schema_obj = parameters["schema"]
        if not isinstance(schema_obj, Mapping):
            message = "Inline schema must be a mapping"
            raise TypeError(message)
        return {str(key): value for key, value in schema_obj.items()}
    schema_path_obj = parameters.get("schema_path")
    if schema_path_obj is None:
        message = "Schema data must be provided via 'schema' or 'schema_path'"
        raise ValueError(message)
    schema_data = _load_json(Path(str(schema_path_obj)), expect_mapping=True)
    return cast("dict[str, object]", schema_data)


def _resolve_payload(parameters: Mapping[str, object]) -> object:
    if "payload" in parameters:
        return parameters["payload"]
    payload_path_obj = parameters.get("payload_path")
    if payload_path_obj is None:
        message = "Payload data must be provided via 'payload' or 'payload_path'"
        raise ValueError(message)
    return _load_json(Path(str(payload_path_obj)), expect_mapping=False)


def _load_json(path: Path, *, expect_mapping: bool) -> object:
    with path.open("r", encoding="utf-8") as handle:
        data = cast("object", json.load(handle))
    if expect_mapping and not isinstance(data, Mapping):
        message = "JSON file must contain an object at the root"
        raise TypeError(message)
    return data


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate JSON payloads against a schema"
    )
    parser.add_argument("--schema", required=True, help="Path to JSON schema file")
    parser.add_argument("--payload", required=True, help="Path to JSON payload file")
    parser.add_argument("--json", action="store_true", help="Emit JSON summary")
    namespace = parser.parse_args(list(argv) if argv is not None else None)
    namespace_dict = cast("dict[str, object]", vars(namespace))
    args = _CliArgs(
        schema_path=str(namespace_dict["schema"]),
        payload_path=str(namespace_dict["payload"]),
        emit_json=bool(namespace_dict.get("json", False)),
    )

    parameters: dict[str, object] = {
        "schema_path": args.schema_path,
        "payload_path": args.payload_path,
    }
    payload: dict[str, object] = {
        "command": "x_make_contract_validators_x",
        "parameters": parameters,
    }
    result = run(payload)
    if args.emit_json:
        json.dump(result, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        print(result["message"])
        for issue in result["issues"]:
            issue_message = str(issue.get("message", ""))
            issue_path = issue.get("path", "?")
            print(f" - {issue_message} @ path {issue_path}")
    return 0 if result["status"] == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
