param([Parameter(Mandatory=$true)][string]$PayloadPath)
$ErrorActionPreference = 'Stop'
try {
    $payload = Get-Content -LiteralPath $PayloadPath -Raw -Encoding UTF8 | ConvertFrom-Json
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing
    $icon = New-Object System.Windows.Forms.NotifyIcon
    $icon.Icon = [System.Drawing.SystemIcons]::Information
    $icon.Text = 'XSD / SOXL'
    $icon.Visible = $true
    $icon.ShowBalloonTip(10000, $payload.title, $payload.message, [System.Windows.Forms.ToolTipIcon]::Info)
    Write-Output ((Get-Date -Format o) + ' Windows notification API invoked successfully.')
    Start-Sleep -Seconds 12
    $icon.Dispose()
} finally {
    $safeRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot 'runtime')) + [System.IO.Path]::DirectorySeparatorChar
    $safeFile = [System.IO.Path]::GetFullPath($PayloadPath)
    if ($safeFile.StartsWith($safeRoot, [System.StringComparison]::OrdinalIgnoreCase) -and [System.IO.Path]::GetFileName($safeFile).StartsWith('notice-')) {
        Remove-Item -LiteralPath $safeFile -ErrorAction SilentlyContinue
    }
}
