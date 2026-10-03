param([switch]$OpenBrowser)
$ErrorActionPreference = 'Stop'
$monitorRoot = $PSScriptRoot
$pythonExe = Join-Path (Split-Path $monitorRoot -Parent) '.venv\Scripts\python.exe'
$runtimeRoot = Join-Path $monitorRoot 'runtime'
New-Item -ItemType Directory -Path $runtimeRoot -Force | Out-Null
if (-not (Test-Path -LiteralPath $pythonExe)) { throw '本地运行环境不存在，请检查 .venv。' }
function Start-MonitorProcess([string]$Name, [string[]]$TaskArgs) {
    $pidFile = Join-Path $runtimeRoot ($Name + '.pid')
    if (Test-Path -LiteralPath $pidFile) {
        $savedId = [int](Get-Content -LiteralPath $pidFile -Raw)
        $existing = Get-CimInstance Win32_Process -Filter "ProcessId = $savedId" -ErrorAction SilentlyContinue
        if ($existing -and $existing.CommandLine -like ('*' + $monitorRoot + '*') -and $existing.ExecutablePath -eq $pythonExe) { return }
    }
    $proc = Start-Process -FilePath $pythonExe -ArgumentList $TaskArgs -WorkingDirectory $monitorRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runtimeRoot ($Name + '.stdout.log')) -RedirectStandardError (Join-Path $runtimeRoot ($Name + '.stderr.log'))
    Set-Content -LiteralPath $pidFile -Value $proc.Id -Encoding ASCII
}
Start-MonitorProcess 'service' @(('"' + (Join-Path $monitorRoot 'service.py') + '"'))
$port = Get-NetTCPConnection -LocalPort 8501 -State Listen -ErrorAction SilentlyContinue
if (-not $port) {
    Start-MonitorProcess 'dashboard' @('-m', 'streamlit', 'run', ('"' + (Join-Path $monitorRoot 'app.py') + '"'), '--server.address', '127.0.0.1', '--server.port', '8501', '--server.headless', 'true', '--browser.gatherUsageStats', 'false')
} else {
    $owner = Get-CimInstance Win32_Process -Filter "ProcessId = $($port[0].OwningProcess)" -ErrorAction SilentlyContinue
    if (-not $owner -or $owner.CommandLine -notlike ('*' + (Join-Path $monitorRoot 'app.py') + '*')) { throw '8501端口被其他程序占用。后台仍可监测，但看板未启动。' }
}
if ($OpenBrowser) { Start-Process 'http://127.0.0.1:8501' }
