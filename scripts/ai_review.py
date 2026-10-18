"""Turn open-code-review's result into review.json and validate it against the review schema.

Usage: python3 scripts/ai_review.py <ocr-result.json> <review.schema.json> <review.json>

Each entry of ``comments`` in the result is one finding (one inline PR comment). The reviewer is
told to begin each comment with ``[SEVERITY confidence=C]``; that prefix becomes ``severity`` and
``confidence``, the rest becomes ``issue``. A finding without the prefix gets ``null`` for both,
which the schema rejects, so the run fails visibly instead of inventing a value. The checker
covers the keywords the schema uses (type, enum, required, properties, additionalProperties,
items, minimum, maximum, minLength) with the standard library only. Exit 1 if review.json is
invalid.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

_PREFIX = re.compile(r"^\s*\[(INFO|LOW|MEDIUM|HIGH)\s+confidence=([0-9]*\.?[0-9]+)\]\s*", re.I)
_TYPES: dict[str, tuple[type, ...]] = {
    "object": (dict,),
    "array": (list,),
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
}


def violations(value: Any, schema: dict[str, Any], where: str = "$") -> list[str]:
    expected = schema.get("type")
    if expected is not None:
        ok = isinstance(value, _TYPES[expected])
        if expected in ("integer", "number") and isinstance(value, bool):
            ok = False
        if not ok:
            return [f"{where}: expected {expected}, got {json.dumps(value)}"]
    if "enum" in schema and value not in schema["enum"]:
        return [f"{where}: {json.dumps(value)} is not one of {schema['enum']}"]
    found: list[str] = []
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        found += [f"{where}: missing {k!r}" for k in schema.get("required", []) if k not in value]
        if schema.get("additionalProperties") is False:
            found += [f"{where}: unexpected {k!r}" for k in value if k not in properties]
        for key, sub in properties.items():
            if key in value:
                found += violations(value[key], sub, f"{where}.{key}")
    if isinstance(value, list) and "items" in schema:
        for n, item in enumerate(value):
            found += violations(item, schema["items"], f"{where}[{n}]")
    if isinstance(value, int | float) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            found.append(f"{where}: {value} is below {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            found.append(f"{where}: {value} is above {schema['maximum']}")
    if isinstance(value, str) and len(value) < schema.get("minLength", 0):
        found.append(f"{where}: shorter than {schema['minLength']} characters")
    return found


def to_finding(comment: dict[str, Any]) -> dict[str, Any]:
    content = str(comment.get("content", ""))
    match = _PREFIX.match(content)
    return {
        "file": comment.get("path", ""),
        "start_line": comment.get("start_line", 0),
        "end_line": comment.get("end_line", 0),
        "issue": content[match.end() :] if match else content,
        "severity": match.group(1).upper() if match else None,
        "confidence": float(match.group(2)) if match else None,
        "suggestion": comment.get("suggestion_code") or "",
    }


def main(result_path: str, schema_path: str, review_path: str) -> int:
    result = json.loads(Path(result_path).read_text(encoding="utf-8"))
    schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
    findings = [to_finding(c) for c in result.get("comments", [])]
    review = {
        "summary": result.get("message") or f"{len(findings)} finding(s)",
        "findings": findings,
    }
    out = Path(review_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(review, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    problems = violations(review, schema)
    for problem in problems:
        sys.stderr.write(f"::error title=ai-review schema::{problem}\n")
    sys.stdout.write(f"{len(findings)} finding(s), {len(problems)} schema violation(s): {out}\n")
    return 1 if problems else 0


if __name__ == "__main__":
    if len(sys.argv) != 4:
        raise SystemExit(__doc__)
    raise SystemExit(main(*sys.argv[1:]))
