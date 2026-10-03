"""Editable Python strategies, evaluated in a bounded child process."""
from __future__ import annotations

import ast
import hashlib
import inspect
import json
import os
from pathlib import Path
import subprocess
import sys
import sysconfig
import tempfile

import numpy as np
import pandas as pd

ALLOWED_IMPORTS = {"numpy", "pandas", "math", "dataclasses"}
FORBIDDEN_NAMES = {"open", "exec", "eval", "compile", "getattr", "setattr", "delattr", "globals", "locals", "vars", "breakpoint", "input", "help", "exit", "quit"}
FORBIDDEN_ATTRIBUTES = {"load", "save", "savez", "savez_compressed", "loadtxt", "savetxt", "fromfile", "tofile", "memmap", "frombuffer", "ctypes", "ctypeslib", "ffi", "to_csv", "to_json", "to_pickle", "to_excel", "to_sql", "to_parquet", "to_feather", "to_hdf", "to_html", "to_clipboard", "to_xml", "to_markdown", "query", "eval", "plot", "show", "style"}
REQUIRED = ("regime", "regime_switch", "state", "symbol", "weight", "reason", "xsd_close", "xsd_annual", "xsd_ma20", "qqq_close", "qqq_annual", "anchored_peak", "peak_drawdown", "volume_multiple", "top_trigger", "top_locked")
TIMEOUT = 30
BASE_SYMBOLS = ("XSD", "SMH", "SOXX", "QQQ")
PORTFOLIO_COLUMNS = ("weight_QQQ", "weight_TQQQ", "rebalance_band")


def template(profile, baseline, base_symbol="XSD"):
    if profile.get("kind") == "python":
        return profile["code"]
    config = inspect.getsource(baseline.Config)
    function = inspect.getsource(baseline.generate_signals)
    # Keep the actual rule implementation visible; omit the research narrative.
    first = function.index('    """')
    end = function.index('"""', first + 7) + 3
    function = function[:first] + '    """按已确认收盘日生成目标，下一交易日开盘执行。"""' + function[end:]
    function = function.replace('cfg=Config()', 'cfg=Config(**PARAMETERS)', 1)
    if base_symbol not in BASE_SYMBOLS:
        raise ValueError("信号标的仅支持XSD、SMH、SOXX。")
    function = function.replace('frames["XSD"]', 'frames[BASE_SYMBOL]').replace('"XSD", defense', 'BASE_SYMBOL, defense').replace('"XSD", cfg.bear_defense', 'BASE_SYMBOL, cfg.bear_defense')
    parameters = "{\n" + "\n".join(f"    {key!r}: {value!r}," for key, value in profile["parameters"].items()) + "\n}"
    return ("# 修改 PARAMETERS 或下方 generate_signals 的判断逻辑，再点击应用代码。\n"
            f"# frames: QQQ / {base_symbol} / SOXL 的日线 DataFrame；只能使用当日及之前的数据。\n"
            "# 返回以日期为索引的信号表；保留模板的输出字段。仓位为 0～1。\n"
            "# xsd_close/xsd_annual/xsd_ma20 是兼容字段，保存当前信号标的的指标。\n"
            "from dataclasses import dataclass, asdict\nimport numpy as np\nimport pandas as pd\n\n\n" + config +
            f"\n# 信号与防御标的；QQQ用于环境判断，SOXL用于进攻。\nBASE_SYMBOL = {base_symbol!r}\n" +
            "\n# 参数也用于看板上的周期与价格口径标注。\nPARAMETERS = " + parameters +
            "\n\n# 可选：自定义状态名称和解释；解释须与修改后的代码一致。\nSTATE_LABELS = {}\nSTATE_NOTES = {}\n\n\n" + function)


def check_source(code):
    if not isinstance(code, str) or not code.strip() or len(code.encode("utf-8")) > 200_000:
        raise ValueError("策略代码不能为空，且须小于200KB。")
    try:
        tree = ast.parse(code, filename="strategy.py")
    except SyntaxError as exc:
        raise ValueError(f"代码第{exc.lineno}行语法错误：{exc.msg}") from exc
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            modules = [alias.name for alias in node.names] if isinstance(node, ast.Import) else [node.module or ""]
            if any(m not in ALLOWED_IMPORTS for m in modules) or getattr(node, "level", 0):
                raise ValueError(f"代码第{node.lineno}行：只支持 numpy、pandas、math、dataclasses。")
            if isinstance(node, ast.ImportFrom) and any(a.name.startswith("_") or a.name.startswith("read_") or a.name in FORBIDDEN_ATTRIBUTES or a.name == "*" for a in node.names):
                raise ValueError(f"代码第{node.lineno}行：此导入不属于行情计算接口。")
        if isinstance(node, ast.Name) and (node.id in FORBIDDEN_NAMES or node.id.startswith("__")):
            raise ValueError(f"代码第{node.lineno}行：不支持 {node.id}，请只编写行情计算逻辑。")
        if isinstance(node, ast.Attribute) and (node.attr.startswith("_") or node.attr.startswith("read_") or node.attr in FORBIDDEN_ATTRIBUTES):
            raise ValueError(f"代码第{node.lineno}行：不支持 {node.attr}，策略不能自行读写文件或连接外部服务。")
    if not any(isinstance(n, ast.FunctionDef) and n.name == "generate_signals" for n in tree.body):
        raise ValueError("请定义 generate_signals(frames, start='2017-01-02') 函数。")
    metadata = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in ("PARAMETERS", "STATE_LABELS", "STATE_NOTES", "BASE_SYMBOL"):
                    try:
                        metadata[target.id] = ast.literal_eval(node.value)
                    except (ValueError, TypeError, SyntaxError) as exc:
                        raise ValueError(f"{target.id}须直接填写常量，不能动态计算。") from exc
    if metadata.get("BASE_SYMBOL", "XSD") not in BASE_SYMBOLS:
        raise ValueError("BASE_SYMBOL仅支持XSD、SMH、SOXX、QQQ。")
    for field, limit in (("STATE_LABELS", 80), ("STATE_NOTES", 2000)):
        values = metadata.get(field, {})
        if not isinstance(values, dict) or len(values) > 40 or any(not isinstance(k, str) or not 1 <= len(k) <= 80 or not isinstance(v, str) or not 1 <= len(v) <= limit for k, v in values.items()):
            raise ValueError(f"{field}须为状态代码到文字的字典。")
    return metadata


def encode_frames(frames):
    return {symbol: {"dates": frame.index.strftime("%Y-%m-%d").tolist(),
                     "columns": list(frame.columns), "data": frame.to_numpy().tolist()}
            for symbol, frame in frames.items()}


def decode_frames(data):
    return {symbol: pd.DataFrame(item["data"], columns=item["columns"], index=pd.to_datetime(item["dates"])) for symbol, item in data.items()}


def validate_signals(signals, frames, start, base_symbol="XSD"):
    if not isinstance(signals, pd.DataFrame) or any(col not in signals for col in REQUIRED):
        raise ValueError("generate_signals须返回DataFrame，并保留模板的全部信号字段。")
    if not isinstance(signals.index, pd.DatetimeIndex) or signals.index.tz is not None or signals.index.has_duplicates or not signals.index.is_monotonic_increasing:
        raise ValueError("信号索引须为无时区、递增且不重复的交易日期。")
    x = frames[base_symbol]
    attack_symbol = "TQQQ" if base_symbol == "QQQ" else "SOXL"
    first = frames[attack_symbol].index.intersection(x.index)
    first = first[first >= pd.Timestamp(start)][0]
    expected = x.index[x.index.get_loc(first) - 1:]
    if not signals.index.equals(expected):
        raise ValueError("信号日期须从首个交易日前一收盘日起连续覆盖至最新日线，不能删减交易日。")
    portfolio = base_symbol == "QQQ"
    if portfolio and any(col not in signals for col in PORTFOLIO_COLUMNS):
        raise ValueError("QQQ策略须返回weight_QQQ、weight_TQQQ和rebalance_band。")
    signals = signals.loc[:, [*REQUIRED, *(PORTFOLIO_COLUMNS if portfolio else ())]].copy()
    numbers = ("weight", "xsd_close", "xsd_annual", "xsd_ma20", "qqq_close", "qqq_annual", "anchored_peak", "peak_drawdown", "volume_multiple")
    for col in numbers:
        if not pd.api.types.is_numeric_dtype(signals[col]) or pd.api.types.is_bool_dtype(signals[col]) or not np.isfinite(signals[col].to_numpy(dtype=float)).all():
            raise ValueError(f"{col}须为有限数值，不能含空值或无穷大。")
    if not signals.weight.between(0, 1).all():
        raise ValueError("目标仓位 weight 须在0至1之间。")
    allowed = ["QQQ", "TQQQ", "MIX", "CASH"] if portfolio else [base_symbol, "SOXL", "CASH"]
    if not signals.symbol.isin(allowed).all():
        raise ValueError("目标 symbol 仅支持 " + "、".join(allowed) + "。")
    if portfolio:
        weights = signals[list(PORTFOLIO_COLUMNS)]
        if any(not pd.api.types.is_numeric_dtype(weights[c]) or pd.api.types.is_bool_dtype(weights[c]) for c in weights) or not np.isfinite(weights.to_numpy(dtype=float)).all():
            raise ValueError("双资产仓位及再平衡阈值须为有限数值。")
        if not weights.ge(0).all().all() or not weights.le(1).all().all():
            raise ValueError("双资产仓位及再平衡阈值须在0至1之间。")
        if not np.allclose(signals.weight, signals.weight_QQQ + signals.weight_TQQQ, atol=1e-12, rtol=0):
            raise ValueError("总仓位必须等于QQQ和TQQQ仓位之和。")
        expected_symbols = np.where(signals.weight_QQQ > 0, np.where(signals.weight_TQQQ > 0, "MIX", "QQQ"), np.where(signals.weight_TQQQ > 0, "TQQQ", "CASH"))
        if not np.array_equal(signals.symbol, expected_symbols):
            raise ValueError("symbol须与双资产仓位一致。")
    if (signals.loc[signals.symbol == "CASH", "weight"] != 0).any():
        raise ValueError("CASH目标的weight须为0。")
    if not signals.regime.isin(["BULL", "BEAR"]).all():
        raise ValueError("regime须为BULL或BEAR。")
    for col in ("regime_switch", "top_trigger", "top_locked"):
        if not pd.api.types.is_bool_dtype(signals[col]):
            raise ValueError(f"{col}须为布尔值。")
    for col in ("state", "reason"):
        if not signals[col].map(lambda v: isinstance(v, str) and len(v) <= 2000 and (bool(v.strip()) if col == "state" else True)).all():
            raise ValueError(f"{col}须为文字，状态名称不能为空。")
    if (signals[list(numbers)[1:7]] <= 0).any().any() or not signals.peak_drawdown.between(0, 1).all() or (signals.volume_multiple < 0).any():
        raise ValueError("价格和均线须大于0，回撤须在0至1之间，成交量倍数须非负。")
    return signals


def evaluate(code, frames, audit=False, timeout=None):
    base_symbol = check_source(code).get("BASE_SYMBOL", "XSD")
    with tempfile.TemporaryDirectory(prefix="xsd-code-") as work:
        source = Path(work) / "input.json"
        output = Path(work) / "output.json"
        source.write_text(json.dumps({"code": code, "frames": encode_frames(frames), "audit": audit}, ensure_ascii=False, allow_nan=False), encoding="utf-8")
        # On Windows the venv launcher creates another process; launching the
        # real interpreter means timeout termination stops the actual runner.
        interpreter = getattr(sys, "_base_executable", sys.executable) if os.name == "nt" else sys.executable
        command = [interpreter, str(Path(__file__).with_name("strategy_runner.py")), str(source), str(output)]
        try:
            # No inherited keys/credentials or user site-packages are needed.
            env = {k: v for k, v in os.environ.items() if k.upper() in {"SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP", "LANG", "LC_ALL"}}
            env["PYTHONIOENCODING"] = "utf-8"
            if os.name == "nt":
                env["PYTHONPATH"] = sysconfig.get_path("purelib")
            result = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout or TIMEOUT,
                                    env=env, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        except subprocess.TimeoutExpired as exc:
            raise ValueError("策略计算超过时间限制，可能存在死循环或计算量过大；当前策略未切换。") from exc
        if result.returncode or not output.exists() or output.stat().st_size > 15_000_000:
            raise ValueError("策略计算进程未正常完成，请检查代码。")
        response = json.loads(output.read_text(encoding="utf-8"))
        if "error" in response:
            raise ValueError(response["error"])
        item = response["signals"]
        signals = pd.DataFrame(item["data"], columns=item["columns"], index=pd.to_datetime(item["dates"]))
        signals.index = signals.index.astype(frames[base_symbol].index.dtype)
        signals.index.name = "date"
        return validate_signals(signals, frames, "2017-01-02", base_symbol)


def code_hash(code):
    return hashlib.sha256(code.encode("utf-8")).hexdigest()
