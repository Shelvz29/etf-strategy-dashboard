"""Build a relocatable Windows source/data package without disrupting the live monitor."""
from datetime import datetime, timezone
from contextlib import closing
from pathlib import Path
import hashlib
import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import zipfile
import re
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parent.parent
EXPORTS = ROOT / "exports"
NAME = "ETF策略编辑与回测看板"
RESEARCH = Path("backtests/2026-10-02-xsd-soxl")
STAMP = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")
EXCLUDED_PARTS = {".git", ".venv", "__pycache__", "node_modules", ".pytest_cache"}


def copy_sources(source, destination, skip_runtime=False):
    count = 0
    for path in sorted(source.rglob("*")):
        relative = path.relative_to(source)
        if not path.is_file() or any(part in EXCLUDED_PARTS for part in relative.parts):
            continue
        if skip_runtime and relative.parts[0] == "runtime":
            continue
        if path.suffix.lower() in {".zip", ".7z", ".rar", ".pyc", ".pyo", ".pid", ".lock", ".log"}:
            continue
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        count += 1
    return count


def write_text(path, text, encoding="utf-8"):
    path.write_text(text, encoding=encoding)


README = """ETF策略编辑与回测看板 · Windows项目包

一、首次运行
1. 把整个压缩包解压到一个固定目录，不要直接在压缩包内启动。
2. 安装Windows版Python 3.12（64位）。下载入口：https://www.python.org/downloads/
   安装时启用Python启动器，或勾选Add Python to PATH。
3. 双击“首次安装.cmd”。脚本会在本目录建立.venv，并联网安装固定版本依赖。
4. 安装成功后，双击本目录“启动看板.vbs”。浏览器地址：http://127.0.0.1:8501/
5. 双击“停止看板.vbs”可同时停止网页与后台。关闭浏览器只关闭网页，不停止监测。
   不需要WSL，也不需要币安API密钥。

二、包含的功能与资料
monitor：本地看板、后台收盘监测、Windows提醒、手动执行记录和操作说明。
看板包括今日看板、信号与提醒、手动执行、设置与说明、历史回测、状态解释、策略编辑。
策略编辑提供Python代码文本框，支持修改参数和判断逻辑、命名、预览、保存、应用和恢复旧版本。
策略选择使用可点击矩形卡片，预览2017年至最新确认收盘、近1/2/3/5年的年化收益与最大回撤。
卡片采用历史连续持仓、单边成本0.1%；点击选中只加载代码，保存后按新版本更新预览。
状态解释按所选策略展示自己的状态集合，突出最新收盘触发状态；未启用策略可独立试算。
策略编辑提供矩形状态框，可编辑名称和解释、添加或移除说明、从代码读取，并随代码版本保存和恢复。
启用后名称、目标、图例和状态说明同步变化；内置组合策略始终保留。
monitor/strategies包含SMH和SOXL、SOXX和SOXL及MACD＋4%急跌避险的完整Python代码，可直接粘贴到策略编辑器。
这些策略已经保存，可在策略编辑和历史回测中选择；当前盯盘策略保持用户原来的选择。
MACD＋4%急跌避险使用SMH MACD柱线<0且昨收至最低跌幅≥4%，现金等待5交易日，再按MACD/EMA20恢复条件解除。
它包含基础八种状态和三种现金避险状态，不包含部分止盈或分批买回。
历史回测可独立选择所有已保存策略及版本，输入本金，查看近1/2/3/5年、全部历史、自定义日期的收益与回撤；
可对比TQQQ、QQQ、XSD、SMH、VGT、SOXX、SOXL。
“对比ETF与策略（可多选）”还支持同时勾选已保存策略的各版本，统一本金、日期和成本，展示并导出收益、资金与回撤。
backtests/2026-10-02-xsd-soxl：原始策略、执行引擎、冻结行情、回测报告和优化研究。
优化研究资料包含在包内；运行看板继续使用现有组合策略的参数。
monitor/runtime/monitor.db：打包时通过SQLite在线备份得到的一致性快照，
保留产品对应关系、页面设置、确认行情、ETF对比缓存、提醒与手动记录。
包中清除了旧进程状态；在新电脑启动后，后台会重新检查最新收盘行情。
SOXL默认名称：Direxion Daily Semiconductor Bull 3X ETF。
XSD默认名称：State Street SPDR S&P Semiconductor ETF。两者状态均按你的信息设为已确认可买卖。

三、启动与自动运行
在新电脑上，自动启动尚未配置。需要登录Windows后自动运行时，打开PowerShell执行：
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\\monitor\\install-startup.ps1
取消自动启动：
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\\monitor\\remove-startup.ps1
任务名称为XSD-SOXL-LocalMonitor；若本机已有同名任务，配置会将其启动路径更新到此副本。
同一台电脑同时启动多个副本会发生8501端口冲突；先停止旧副本，再启动新副本。
保持电脑开机、联网且不休眠，后台才可持续监测。

四、校验与复现
“包内容清单.json”列出包内文件的SHA-256及数据库备份信息。
压缩包旁的.sha256文件用于验证整个压缩包。
如果需要验证源码，首次安装后在monitor目录执行：
..\\.venv\\Scripts\\python.exe -m unittest test_monitor test_performance test_strategies test_macd_risk -v
原始研究的运行方式见backtests/2026-10-02-xsd-soxl/README.md。

五、运行约定
这是源码和数据包，Python及虚拟环境需按上述步骤安装；首次安装需要联网。
历史行情与HTML研究报告可以离线查看，最新行情更新需要联网。
新电脑不会继承原电脑的Windows通知权限；可在“设置与说明”测试本机提醒。
策略信号不代表你已经持有股票；实际持仓以账户为准，工具不自动下单。
“monitor/操作说明.txt”包含完整使用说明；其中原电脑已完成的部署验证属于历史记录。
"""

INSTALL = r"""$ErrorActionPreference = 'Stop'
$packageRoot = $PSScriptRoot
$environmentPath = Join-Path $packageRoot '.venv'
$environmentPython = Join-Path $environmentPath 'Scripts\python.exe'
if (-not (Test-Path -LiteralPath $environmentPython)) {
    $basePython = $null
    if (Get-Command py -ErrorAction SilentlyContinue) {
        try { $probe = & py -3.12 -c 'import sys; print(sys.executable)' 2>$null } catch { $probe = $null }
        if ($LASTEXITCODE -eq 0 -and $probe) { $basePython = ([string]$probe).Trim() }
    }
    if (-not $basePython -and (Get-Command python -ErrorAction SilentlyContinue)) {
        try { $probe = & python -c 'import sys; print(sys.executable)' 2>$null } catch { $probe = $null }
        if ($LASTEXITCODE -eq 0 -and $probe) { $basePython = ([string]$probe).Trim() }
    }
    if (-not $basePython -or -not (Test-Path -LiteralPath $basePython)) {
        throw '未找到Python。请先安装Windows版Python 3.12（64位），并启用启动器或添加到PATH。'
    }
    & $basePython -c 'import sys; sys.exit(0 if sys.version_info[:2]==(3,12) and sys.maxsize>2**32 else 1)'
    if ($LASTEXITCODE -ne 0) { throw '此项目包使用Python 3.12（64位），请安装该版本后重试。' }
    & $basePython -m venv $environmentPath
    if ($LASTEXITCODE -ne 0) { throw '建立本地Python环境失败。' }
}
& $environmentPython -c 'import sys; sys.exit(0 if sys.version_info[:2]==(3,12) and sys.maxsize>2**32 else 1)'
if ($LASTEXITCODE -ne 0) { throw '已有.venv不是Python 3.12（64位）。请换一个全新的解压目录后安装。' }
& $environmentPython -m pip install --disable-pip-version-check -r (Join-Path $packageRoot 'monitor\requirements.txt') -r (Join-Path $packageRoot 'backtests\2026-10-02-xsd-soxl\requirements.txt')
if ($LASTEXITCODE -ne 0) { throw '依赖安装失败，请检查网络连接，再运行“首次安装.cmd”。' }
Write-Host '安装完成。请双击本目录的“启动看板.vbs”。' -ForegroundColor Green
"""


def main():
    EXPORTS.mkdir(exist_ok=True)
    archive = EXPORTS / f"{STAMP}-{NAME}.zip"
    if archive.exists():
        archive = EXPORTS / f"{STAMP}-{NAME}-{datetime.now():%H%M%S}.zip"
    with tempfile.TemporaryDirectory(prefix=".package-", dir=EXPORTS) as working:
        working_path = Path(working).resolve()
        # Cleanup is limited to this newly created directory under the exports workspace.
        working_path.relative_to(EXPORTS.resolve())
        package = working_path / NAME
        package.mkdir()
        copy_sources(ROOT / "monitor", package / "monitor", skip_runtime=True)
        copy_sources(ROOT / RESEARCH, package / RESEARCH)
        # Minimal frozen evidence needed by the added standalone-strategy test
        # and generator; avoid requiring the large exploratory curve sets.
        risk_proof = Path("backtests/2026-10-03-smh-soxl-risk")
        combo_proof = Path("backtests/2026-10-03-smh-soxl-combinations")
        proof_files = [risk_proof / "source_profile.json",
                       *(risk_proof / "data" / f"{s}.csv" for s in ("QQQ", "SMH", "SOXL")),
                       combo_proof / "signals_macd_drop4.csv", combo_proof / "curve_macd_drop4.csv"]
        for relative in proof_files:
            target = package / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / relative, target)
        runtime = package / "monitor" / "runtime"
        runtime.mkdir()
        db_path = runtime / "monitor.db"
        with closing(sqlite3.connect(ROOT / "monitor" / "runtime" / "monitor.db", timeout=30)) as source:
            with closing(sqlite3.connect(db_path)) as target:
                source.backup(target)
                target.execute("DELETE FROM kv WHERE key IN ('heartbeat','preview','refresh_request','refresh_handled','validated_session','last_attempt')")
                target.commit()
                target.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                target.execute("PRAGMA journal_mode=DELETE")
                assert target.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
                db_info = {"snapshot_method": "SQLite online backup", "manual_trade_count": target.execute("SELECT COUNT(*) FROM trades").fetchone()[0],
                           "comparison_price_count": target.execute("SELECT COUNT(*) FROM comparison_prices").fetchone()[0],
                           "strategy_profile_count": target.execute("SELECT COUNT(*) FROM strategy_profiles").fetchone()[0]}
                for key in ("products", "performance_settings", "snapshot", "active_strategy"):
                    row = target.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
                    value = json.loads(row[0]) if row else None
                    db_info[key] = ({"source": value["source"], "confirmed_session": value["last"]["date"]} if key == "snapshot" and value else value)
        for preview_name in (f"{NAME}.png", "策略编辑看板.png", "策略编辑-回测预览.png", "历史回测-策略选择.png", "替换策略选项.png", "多策略与ETF对比.png", "策略选择卡片.png", "状态解释.png", "状态编辑框.png"):
            preview = ROOT / "monitor" / "runtime" / preview_name
            if preview.exists():
                shutil.copy2(preview, runtime / preview.name)
        manifest_path = package / "monitor" / "strategy_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["source"] = (RESEARCH / "strategy.py").as_posix()
        write_text(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        write_text(package / "先读我.txt", README, "utf-8-sig")
        write_text(package / "install.ps1", INSTALL, "utf-8-sig")
        write_text(package / "首次安装.cmd", '@echo off\npowershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"\npause\n', "ascii")
        for label, script, args in (("启动看板", "start.ps1", " -OpenBrowser"), ("停止看板", "stop.ps1", "")):
            launcher = ('Dim shell, folder\nSet shell = CreateObject("WScript.Shell")\n'
                        'folder = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)\n'
                        'shell.Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & folder & '
                        f'"\\monitor\\{script}""{args}", 0, False\n')
            write_text(package / f"{label}.vbs", launcher, "ascii")
        sources = sorted(p for p in package.rglob("*") if p.is_file())
        content = {str(p.relative_to(package)).replace("\\", "/"): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
        package_manifest = {"project_name": NAME, "created_utc": datetime.now(timezone.utc).isoformat(),
                            "python_version": "3.12 (64-bit)", "file_count_without_manifest": len(sources),
                            "database": db_info, "files_sha256": content}
        write_text(package / "包内容清单.json", json.dumps(package_manifest, ensure_ascii=False, indent=2) + "\n")
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
            for path in sorted(p for p in package.rglob("*") if p.is_file()):
                bundle.write(path, path.relative_to(working_path).as_posix())
        with zipfile.ZipFile(archive) as bundle:
            assert bundle.testzip() is None
            assert len(bundle.namelist()) == len(content) + 1
            assert all(not name.endswith((".zip", ".pid", ".lock", ".log")) for name in bundle.namelist())
            for name, digest in content.items():
                assert hashlib.sha256(bundle.read(f"{NAME}/{name}")).hexdigest() == digest, name
            extracted = working_path / "relocation-check"
            bundle.extractall(extracted)
        relocated = extracted / NAME
        relocated_manifest = json.loads((relocated / "monitor" / "strategy_manifest.json").read_text(encoding="utf-8"))
        assert hashlib.sha256((relocated / RESEARCH / "strategy.py").read_bytes()).hexdigest() == relocated_manifest["sha256"]
        # Verify the installer syntax without executing installs or changing the live service.
        check_file = working_path / "check-installer.ps1"
        write_text(check_file, "param([string]$Source)\n$parseTokens=$null; $parseErrors=$null; [System.Management.Automation.Language.Parser]::ParseFile($Source,[ref]$parseTokens,[ref]$parseErrors) | Out-Null; if ($parseErrors.Count) { $parseErrors | ForEach-Object { $_.Message }; exit 1 }\n")
        script_check = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(check_file), "-Source", str(relocated / "install.ps1")], capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
        if script_check.returncode:
            raise RuntimeError(script_check.stdout + script_check.stderr)
        checks = subprocess.run([str(ROOT / ".venv" / "Scripts" / "python.exe"), "-m", "unittest", "test_monitor", "test_performance", "test_strategies", "test_macd_risk", "-q"],
                                cwd=relocated / "monitor", capture_output=True, text=True, encoding="utf-8", errors="replace")
        if checks.returncode:
            raise RuntimeError(checks.stdout + checks.stderr)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    write_text(archive.with_suffix(".zip.sha256"), f"{digest}  {archive.name}\n")
    verification = {"archive": str(archive), "size_bytes": archive.stat().st_size, "file_count": len(content) + 1,
                    "sha256": digest, "zip_crc_check": "passed", "file_hash_checks": "passed", "database_integrity": "ok",
                    "relocated_tests_passed": int(re.search(r"Ran (\d+) tests", checks.stderr).group(1)), "installer_parse_check": "passed", "database": db_info,
                    "verified_at_utc": datetime.now(timezone.utc).isoformat()}
    write_text(archive.with_suffix(".zip.verify.json"), json.dumps(verification, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(verification, ensure_ascii=True), flush=True)


if __name__ == "__main__":
    main()
