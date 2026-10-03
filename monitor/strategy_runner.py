"""Child process for local user code; limits are safeguards, not an OS sandbox."""
import builtins
import contextlib
import json
import os
from pathlib import Path
import sys
import traceback
import types

import pandas as pd

import code_strategy as cs


def calculate(code, frames):
    metadata = cs.check_source(code)
    module = types.ModuleType("editable_strategy")
    sys.modules[module.__name__] = module
    safe = {name: value for name, value in vars(builtins).items() if name not in cs.FORBIDDEN_NAMES and not name.startswith("__")}
    def safe_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name not in cs.ALLOWED_IMPORTS or level:
            raise ValueError("策略不支持此模块：" + name)
        return builtins.__import__(name, globals, locals, fromlist, level)
    safe.update({"__import__": safe_import, "__build_class__": builtins.__build_class__})
    module.__dict__["__builtins__"] = safe
    # Discard prints so user code cannot fill the worker's log.
    with open(os.devnull, "w", encoding="utf-8") as discard:
        with contextlib.redirect_stdout(discard), contextlib.redirect_stderr(discard):
            exec(compile(code, "strategy.py", "exec"), module.__dict__)
            signals = module.generate_signals({s: f.copy(deep=True) for s, f in frames.items()}, start="2017-01-02")
    return cs.validate_signals(signals, frames, "2017-01-02", metadata.get("BASE_SYMBOL", "XSD"))


def main():
    output = Path(sys.argv[2])
    try:
        payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
        frames = cs.decode_frames(payload["frames"])
        signals = calculate(payload["code"], frames)
        if payload["audit"]:
            # Compare every earlier row at several truncated endpoints. This catches
            # common future-data mistakes; it is deliberately not a proof of causality.
            count = len(signals)
            cuts = sorted(set([max(2, int(count * fraction)) for fraction in (.1, .25, .5, .75, .9)] + [count - 1]))
            for stop in cuts:
                endpoint = signals.index[stop - 1]
                earlier = calculate(payload["code"], {s: f.loc[:endpoint] for s, f in frames.items()})
                try:
                    pd.testing.assert_frame_equal(signals.loc[:endpoint], earlier, check_exact=False, rtol=1e-10, atol=1e-10)
                except AssertionError as exc:
                    raise ValueError(f"截断至{endpoint.date()}后，历史信号发生变化；代码可能引用未来数据或产生不确定结果，请检查。") from exc
        response = {"signals": {"dates": signals.index.strftime("%Y-%m-%d").tolist(), "columns": list(signals.columns), "data": signals.to_numpy().tolist()}}
    except BaseException as exc:
        lines = [item.lineno for item in traceback.extract_tb(exc.__traceback__) if item.filename == "strategy.py"]
        where = f"代码第{lines[-1]}行：" if lines else ""
        response = {"error": where + type(exc).__name__ + "：" + str(exc)[:1500]}
    output.write_text(json.dumps(response, ensure_ascii=False, allow_nan=False), encoding="utf-8")


if __name__ == "__main__":
    main()
