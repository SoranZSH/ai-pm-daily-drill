# 卸载「Github学习-采集」定时任务（方案 M6）。
# 本文件须以 UTF-8 带 BOM 保存（Windows PowerShell 5.1 需要）。
$taskName = "Github学习-采集"

schtasks /Delete /TN $taskName /F
if ($LASTEXITCODE -eq 0) {
    Write-Host "已删除定时任务「$taskName」"
} else {
    Write-Host "未找到定时任务「$taskName」（可能已经删除）"
}
