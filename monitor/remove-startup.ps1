$ErrorActionPreference = 'Stop'
Unregister-ScheduledTask -TaskName 'XSD-SOXL-LocalMonitor' -Confirm:$false -ErrorAction SilentlyContinue
Write-Output '已取消登录后自动启动；当前运行程序可通过停止看板关闭。'
