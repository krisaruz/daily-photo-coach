# Daily Photo Coach - 卸载定时任务

$taskName = "DailyPhotoCoach"

$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    Write-Host "已删除定时任务: $taskName" -ForegroundColor Yellow
} else {
    Write-Host "未找到定时任务: $taskName" -ForegroundColor Gray
}
