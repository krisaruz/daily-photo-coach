# Daily Photo Coach - 本地每日运行脚本
# 功能：抓取照片 + LLM 分析 + 推送到 GitHub（自动部署到 Pages）
# 密钥从 config.yaml 读取（已 gitignore）

$ErrorActionPreference = "Stop"
$projectDir = "E:\daily-photo-coach"
$logFile = "$projectDir\daily-run.log"

function Log($msg) {
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "$ts $msg" | Tee-Object -FilePath $logFile -Append
}

try {
    Log "=== Daily Photo Coach 开始 ==="
    Set-Location $projectDir

    # 运行主程序（抓图 + LLM 分析）
    Log "运行 main.py ..."
    $env:PYTHONPATH = "src"
    python src/main.py 2>&1 | Tee-Object -FilePath $logFile -Append
    if ($LASTEXITCODE -ne 0) {
        Log "main.py 执行失败，退出码: $LASTEXITCODE"
        exit $LASTEXITCODE
    }

    # 提交并推送
    Log "提交 output 到 git ..."
    git add output/ -f
    $changed = git diff --cached --quiet; $hasChanges = $LASTEXITCODE -ne 0
    if ($hasChanges) {
        $today = Get-Date -Format "yyyy-MM-dd"
        git commit -m "daily: auto fetch + analyze for $today"
        Log "推送到 GitHub ..."
        git push origin master
        Log "推送完成，GitHub Pages 将自动部署"
    } else {
        Log "没有新变更需要提交"
    }

    Log "=== Daily Photo Coach 完成 ==="
} catch {
    Log "异常: $_"
    exit 1
}
