# Daily Photo Coach - Windows 任务计划程序安装脚本
# 以管理员权限运行此脚本，创建每日定时任务

$ErrorActionPreference = "Stop"

$projectDir = "E:\daily-photo-coach"
$taskName = "DailyPhotoCoach"
$batPath = "$projectDir\daily-run.bat"

# 检查 daily-run.bat 是否存在
if (-not (Test-Path $batPath)) {
    Write-Error "找不到 $batPath"
    exit 1
}

# 删除已有任务（如果存在）
$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "删除已有的定时任务: $taskName"
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
}

# 创建任务操作：运行 daily-run.bat
$action = New-ScheduledTaskAction `
    -Execute "cmd.exe" `
    -Argument "/c `"$batPath`"" `
    -WorkingDirectory $projectDir

# 每天早上 9:00 触发
$triggerDaily = New-ScheduledTaskTrigger -Daily -At "09:00"

# 开机时触发（延迟 60 秒等待网络就绪）
$triggerBoot = New-ScheduledTaskTrigger -AtStartup
$triggerBoot.Delay = "PT60S"

# 任务设置
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2)

# 注册任务（以当前用户身份运行）
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERNAME" -LogonType S4U -RunLevel Highest

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger @($triggerDaily, $triggerBoot) `
    -Settings $settings `
    -Principal $principal `
    -Description "Daily Photo Coach - 每日抓取照片 + LLM 分析 + 推送到 GitHub Pages" `
    -Force

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host " 定时任务已创建！" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "任务名称: $taskName"
Write-Host "触发条件:"
Write-Host "  - 每天 09:00 自动执行"
Write-Host "  - 开机后 60 秒自动执行"
Write-Host ""
Write-Host "查看任务: Get-ScheduledTask -TaskName '$taskName'"
Write-Host "手动运行: Start-ScheduledTask -TaskName '$taskName'"
Write-Host "删除任务: Unregister-ScheduledTask -TaskName '$taskName'"
