$ErrorActionPreference = 'Stop'
$pythonExe = Join-Path (Split-Path $PSScriptRoot -Parent) '.venv\Scripts\python.exe'
foreach ($name in @('dashboard', 'service')) {
    $pidFile = Join-Path $PSScriptRoot ('runtime\' + $name + '.pid')
    if (Test-Path -LiteralPath $pidFile) {
        $savedId = [int](Get-Content -LiteralPath $pidFile -Raw)
        $existing = Get-CimInstance Win32_Process -Filter "ProcessId = $savedId" -ErrorAction SilentlyContinue
        if ($existing -and $existing.ExecutablePath -eq $pythonExe -and $existing.CommandLine -like ('*' + $PSScriptRoot + '*')) {
            # Windows venv's launcher creates a child interpreter. Stop only this
            # launcher's children carrying the same absolute application path.
            $children = Get-CimInstance Win32_Process -Filter "ParentProcessId = $savedId"
            foreach ($child in $children) {
                $expectedScript = if ($name -eq 'service') { Join-Path $PSScriptRoot 'service.py' } else { Join-Path $PSScriptRoot 'app.py' }
                if ($child.Name -eq 'python.exe' -and $child.CommandLine -like ('*' + $expectedScript + '*')) {
                    Stop-Process -Id $child.ProcessId -ErrorAction SilentlyContinue
                }
            }
            Stop-Process -Id $savedId -ErrorAction SilentlyContinue
        }
        Remove-Item -LiteralPath $pidFile
    }
}
