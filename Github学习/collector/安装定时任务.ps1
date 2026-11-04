# 安装「Github学习-采集」定时任务（方案 M6）。以当前用户运行，不需要管理员。
# 本文件须以 UTF-8 带 BOM 保存（Windows PowerShell 5.1 需要）。
# 触发器：① 每天 09:00；② 用户登录时延迟 5 分钟；③ 每天 09:00 起每 1 小时一次，持续 14 小时；
# ④ 电脑从睡眠唤醒后延迟 1 分钟（System 日志，Microsoft-Windows-Power-Troubleshooter 事件 1）。
# 不设置「唤醒计算机运行此任务」；不做负载检测。
# 防重复由 collect.py 负责（20 小时规则与窗口规则），重复触发几乎没有成本。
$ErrorActionPreference = "Stop"
$taskName = "Github学习-采集"
$collectorDir = $PSScriptRoot
# 解析 pythonw.exe 的完整路径，避免计划任务在用户 PATH 之外找不到 Python
$pythonw = (Get-Command pythonw.exe -ErrorAction Stop).Source
$startDate = (Get-Date).ToString("yyyy-MM-dd")
$user = "$env:USERDOMAIN\$env:USERNAME"

function Escape-Xml([string]$s) {
    return [System.Security.SecurityElement]::Escape($s)
}

$xmlTemplate = @'
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>采集 GitHub 高 Star 项目（方案 M6）。防重复由 collect.py 负责。</Description>
  </RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>{{START}}T09:00:00</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByDay>
        <DaysInterval>1</DaysInterval>
      </ScheduleByDay>
    </CalendarTrigger>
    <LogonTrigger>
      <Enabled>true</Enabled>
      <Delay>PT5M</Delay>
      <UserId>{{USER}}</UserId>
    </LogonTrigger>
    <CalendarTrigger>
      <Repetition>
        <Interval>PT1H</Interval>
        <Duration>PT14H</Duration>
        <StopAtDurationEnd>false</StopAtDurationEnd>
      </Repetition>
      <StartBoundary>{{START}}T09:00:00</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByDay>
        <DaysInterval>1</DaysInterval>
      </ScheduleByDay>
    </CalendarTrigger>
    <EventTrigger>
      <Enabled>true</Enabled>
      <Subscription>&lt;QueryList&gt;&lt;Query Id="0" Path="System"&gt;&lt;Select Path="System"&gt;*[System[Provider[@Name='Microsoft-Windows-Power-Troubleshooter'] and (EventID=1)]]&lt;/Select&gt;&lt;/Query&gt;&lt;/QueryList&gt;</Subscription>
      <Delay>PT1M</Delay>
    </EventTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>{{USER}}</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT1H</ExecutionTimeLimit>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{{PYTHONW}}</Command>
      <Arguments>collect.py</Arguments>
      <WorkingDirectory>{{DIR}}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
'@

$xml = $xmlTemplate.Replace("{{START}}", $startDate)
$xml = $xml.Replace("{{USER}}", (Escape-Xml $user))
$xml = $xml.Replace("{{PYTHONW}}", (Escape-Xml $pythonw))
$xml = $xml.Replace("{{DIR}}", (Escape-Xml $collectorDir))

# schtasks /XML 要求 UTF-16（带 BOM）的文件，与 XML 声明一致
$xmlPath = Join-Path $env:TEMP "github-collect-task.xml"
[System.IO.File]::WriteAllText($xmlPath, $xml, [System.Text.Encoding]::Unicode)
try {
    schtasks /Create /TN $taskName /XML $xmlPath /F
    if ($LASTEXITCODE -ne 0) { throw "schtasks /Create 失败（退出码 $LASTEXITCODE）" }
    Write-Host "已安装定时任务「$taskName」。"
    Write-Host "验证：schtasks /Query /TN `"$taskName`" /V /FO LIST"
} finally {
    Remove-Item $xmlPath -ErrorAction SilentlyContinue
}
