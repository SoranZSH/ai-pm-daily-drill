# 把提醒程序装进「开机启动」，并立刻启动一次。
# 用法：右键 → 使用 PowerShell 运行；或在本目录执行  powershell -ExecutionPolicy Bypass -File .\安装自启动.ps1

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$app  = Join-Path $root "app.pyw"

if (-not (Test-Path $app)) { Write-Host "找不到 app.pyw" -ForegroundColor Red; exit 1 }

# 找 pythonw.exe（无控制台窗口的解释器）
$pythonw = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source
if (-not $pythonw) {
    $py = (Get-Command python.exe -ErrorAction SilentlyContinue).Source
    if ($py) { $pythonw = Join-Path (Split-Path $py) "pythonw.exe" }
}
if (-not $pythonw -or -not (Test-Path $pythonw)) {
    Write-Host "找不到 pythonw.exe，请确认 Python 已加入 PATH" -ForegroundColor Red; exit 1
}

$startup = [Environment]::GetFolderPath("Startup")
$lnk     = Join-Path $startup "面试英语每日提醒.lnk"

$ws = New-Object -ComObject WScript.Shell
$s  = $ws.CreateShortcut($lnk)
$s.TargetPath       = $pythonw
$s.Arguments        = "`"$app`""
$s.WorkingDirectory = $root
$s.Description      = "面试英语题库 · 每日练习提醒"
$s.IconLocation     = "$pythonw,0"
$s.Save()

# 守护定时任务：每 30 分钟拉起一次。程序在运行时新实例会立刻退出；程序崩溃或被关掉后最多 30 分钟自动恢复。
# 以当前用户运行，不需要管理员。不限运行时长（默认 72 小时上限会把常驻的提醒程序杀掉）。
$taskName = "面试英语每日提醒-守护"
$action   = New-ScheduledTaskAction -Execute $pythonw -Argument "`"$app`"" -WorkingDirectory $root
$trigger  = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
                -RepetitionInterval (New-TimeSpan -Minutes 30) -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
                -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Seconds 0)
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings `
    -Principal $principal -Description "面试英语题库：提醒程序意外退出后自动恢复" -Force | Out-Null

Write-Host ""
Write-Host "  已安装开机自启动" -ForegroundColor Green
Write-Host "  已安装守护定时任务（每 30 分钟检查一次，程序意外退出后自动恢复）: $taskName" -ForegroundColor Green
Write-Host "  快捷方式: $lnk" -ForegroundColor DarkGray
Write-Host "  解释器:   $pythonw" -ForegroundColor DarkGray
Write-Host ""

# 结束可能已在运行的旧实例，再启动新的
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" |
    Where-Object { $_.CommandLine -like "*app.pyw*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

Start-Process -FilePath $pythonw -ArgumentList "`"$app`"" -WorkingDirectory $root
Write-Host "  提醒程序已在后台运行，约 90 秒后会第一次敲门。" -ForegroundColor Green
Write-Host "  想马上看效果:  python app.pyw --test" -ForegroundColor DarkGray
Write-Host ""
