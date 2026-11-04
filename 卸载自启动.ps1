# 移除开机自启动，并结束正在运行的提醒程序。

$lnk = Join-Path ([Environment]::GetFolderPath("Startup")) "面试英语每日提醒.lnk"
if (Test-Path $lnk) { Remove-Item $lnk -Force; Write-Host "  已移除开机自启动" -ForegroundColor Green }
else { Write-Host "  本来就没有安装自启动" -ForegroundColor DarkGray }

$taskName = "面试英语每日提醒-守护"
if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    Write-Host "  已移除守护定时任务" -ForegroundColor Green
}

$n = 0
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" |
    Where-Object { $_.CommandLine -like "*app.pyw*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; $n++ }
Write-Host "  已结束 $n 个后台进程" -ForegroundColor DarkGray
Write-Host "  题库和练习记录都还在，随时可以重新安装。" -ForegroundColor DarkGray
