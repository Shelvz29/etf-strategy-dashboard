"""Per-strategy state documentation and lossless edits of literal metadata."""
import ast

import code_strategy as cs
import core


def legacy_notes(profile):
    from state_ui import state_details
    return {code: "\n".join((item["condition"], item["meaning"], item["detail"]))
            for code, item in state_details(profile).items()}


def literal_states(source):
    """Draft-only fallback; declared metadata and replayed outputs take priority."""
    tree = ast.parse(source)
    codes = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "state":
                value = node.value
            elif isinstance(target, (ast.Tuple, ast.List)) and isinstance(node.value, (ast.Tuple, ast.List)):
                pairs = zip(target.elts, node.value.elts)
                value = next((v for t, v in pairs if isinstance(t, ast.Name) and t.id == "state"), None)
            else:
                continue
            if isinstance(value, ast.Constant) and isinstance(value.value, str) and value.value:
                codes.append(value.value)
    return list(dict.fromkeys(codes))


def definitions(profile, observed=()):
    if profile.get("kind") != "python":
        labels, notes = core.STATE_NAMES, legacy_notes(profile)
        codes = list(labels)
    else:
        labels, notes = profile.get("state_labels", {}), profile.get("state_notes", {})
        codes = list(dict.fromkeys([*labels, *notes, *observed]))
        if not codes:
            codes = literal_states(profile["code"])
    return [{"code": code, "name": labels.get(code, core.STATE_NAMES.get(code, code)),
             "note": notes.get(code, "")} for code in codes]


def source_definitions(source):
    metadata = cs.check_source(source)
    profile = {"kind": "python", "code": source,
               "state_labels": metadata.get("STATE_LABELS", {}), "state_notes": metadata.get("STATE_NOTES", {})}
    return definitions(profile)


def replace_metadata(source, labels, notes):
    """Replace only top-level literal assignments; preserve all trading logic."""
    cs.check_source(source)
    values = {"STATE_LABELS": labels, "STATE_NOTES": notes}
    tree = ast.parse(source)
    lines = source.splitlines(keepends=True)
    edits, present = [], set()
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        names = [target.id for target in node.targets if isinstance(target, ast.Name) and target.id in values]
        if not names:
            continue
        if len(node.targets) != 1:
            raise ValueError("STATE_LABELS和STATE_NOTES请分别独立赋值，不能与其他变量共用赋值。")
        name = names[0]
        present.add(name)
        # AST columns are UTF-8 byte offsets. Replace the RHS only, so inline
        # comments, preceding semicolon statements and Chinese text survive.
        begin = sum(len(line.encode("utf-8")) for line in lines[:node.value.lineno - 1]) + node.value.col_offset
        end = sum(len(line.encode("utf-8")) for line in lines[:node.value.end_lineno - 1]) + node.value.end_col_offset
        edits.append((begin, end, repr(values[name]).encode("utf-8")))
    raw = source.encode("utf-8")
    for begin, end, replacement in sorted(edits, reverse=True):
        raw = raw[:begin] + replacement + raw[end:]
    result = raw.decode("utf-8")
    missing = [name for name in values if name not in present]
    if missing:
        result += "\n" + "\n".join(f"{name} = {values[name]!r}" for name in missing) + "\n"
    cs.check_source(result)
    return result


def merge_editor_states(source, defaults, edited, profile):
    metadata = cs.check_source(source)
    labels, notes = dict(metadata.get("STATE_LABELS", {})), dict(metadata.get("STATE_NOTES", {}))
    # Carry the known parameter-strategy descriptions into its first code copy
    # only if the rule body is unchanged. Parameter-only edits regenerate the
    # descriptions with the submitted parameters, avoiding stale thresholds.
    if profile.get("kind") != "python" and not labels and not notes:
        function = lambda text: next(node for node in ast.parse(text).body
                                     if isinstance(node, ast.FunctionDef) and node.name == "generate_signals")
        if ast.dump(function(source)) == ast.dump(function(core.strategy_code(profile))):
            described = {**profile, "parameters": core.validate_parameters(metadata.get("PARAMETERS", profile["parameters"]))}
            labels, notes = dict(core.STATE_NAMES), legacy_notes(described)
    baseline = {row["code"]: row for row in defaults}
    for row in edited:
        code = row["code"]
        old = baseline.get(code, {"name": code, "note": ""})
        if row.get("remove"):
            labels.pop(code, None)
            notes.pop(code, None)
            continue
        if row["name"] != old["name"] or code not in baseline or old.get("new"):
            if not row["name"].strip():
                raise ValueError(f"{code}的状态名称不能为空。")
            labels[code] = row["name"].strip()
        if row["note"] != old["note"] or code not in baseline or old.get("new"):
            if row["note"].strip():
                notes[code] = row["note"].strip()
            else:
                notes.pop(code, None)
    return replace_metadata(source, labels, notes)
