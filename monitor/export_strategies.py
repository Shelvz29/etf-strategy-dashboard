"""Generate complete, editable semiconductor ETF combination strategies."""
from pathlib import Path
import json

import core
import code_strategy
import state_ui


def replacement_code(symbol):
    profile = core.default_strategy()
    source = code_strategy.template(profile, core.baseline, symbol)
    details = state_ui.state_details(profile)
    notes = {code: (item["condition"] + " " + item["detail"]).replace("XSD", symbol) for code, item in details.items()}
    source = source.replace("STATE_LABELS = {}", "STATE_LABELS = " + repr(core.STATE_NAMES))
    source = source.replace("STATE_NOTES = {}", "STATE_NOTES = " + repr(notes))
    source = f"# {symbol}和SOXL组合策略\n# 将XSD的信号与防御角色完整替换为{symbol}，原有参数保持不变。\n" + source
    code_strategy.check_source(source)
    return source


def main():
    directory = core.ROOT / "strategies"
    directory.mkdir(exist_ok=True)
    for symbol in ("SMH", "SOXX"):
        name = f"{symbol}和SOXL组合策略"
        source = replacement_code(symbol)
        path = directory / f"{name}.py"
        path.write_text(source, encoding="utf-8")
        # Saving performs a full replay and a sampled causality check, while
        # preserving the currently active strategy and confirmed state.
        existing = next((p for p in core.list_strategies() if p["name"] == name), None)
        if existing is None:
            saved = core.save_strategy(name, description=f"以{symbol}替换XSD的信号与防御标的；QQQ环境、SOXL进攻及原始参数保持不变。", code=source)
        elif existing.get("code") == source:
            saved = existing
        else:
            raise ValueError(f"{name}已被编辑，导出文件已生成，未覆盖你的策略版本。")
        print(json.dumps({"file": str(path), "name": name, "revision": saved["revision"], "id": saved["id"]}, ensure_ascii=True), flush=True)


if __name__ == "__main__":
    core.init_db()
    main()
