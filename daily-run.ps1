# Daily Photo Coach - 本地每日运行脚本
# 功能：抓取照片 + LLM 分析 + 推送到 GitHub（自动部署到 Pages）
# 密钥从 config.yaml 读取（已 gitignore）

$projectDir = "E:\daily-photo-coach"
$logFile = "$projectDir\daily-run.log"
$pythonExe = "C:\Users\admin\AppData\Local\Programs\Python\Python311\python.exe"

function Log($msg) {
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "$ts $msg" | Tee-Object -FilePath $logFile -Append
}

try {
    Log "=== Daily Photo Coach 开始 ==="
    Set-Location $projectDir

    # 先拉取最新代码（GitHub Actions 可能已抓了图）
    Log "拉取最新代码 ..."
    git pull origin master --quiet 2>&1 | Out-File -FilePath $logFile -Append -Encoding utf8

    # 循环模式：不再抓新图、不调 LLM，从历史归档中挑选已有分析的图片
    # Python logging 写 stderr，所以用 cmd 重定向把 stderr 合并到 stdout，避免 PowerShell ErrorActionPreference 触发异常
    Log "运行 recycle_daily.py (Python 3.11) ..."
    $env:PYTHONPATH = "src"
    $env:PYTHONIOENCODING = "utf-8"
    cmd /c "`"$pythonExe`" src\recycle_daily.py 2>&1" | Tee-Object -FilePath $logFile -Append
    if ($LASTEXITCODE -ne 0) {
        Log "recycle_daily.py 执行失败，退出码: $LASTEXITCODE"
        exit $LASTEXITCODE
    }

    # 小红书 daily pick（纯归档轮换，不访问小红书、不调 LLM）
    Log "运行 xhs_daily.py ..."
    cmd /c "`"$pythonExe`" src\xhs_daily.py --style-key xhs-portrait --mode note --count 1 --from-archive-only --skip-analysis 2>&1" | Tee-Object -FilePath $logFile -Append
    if ($LASTEXITCODE -ne 0) {
        Log "xhs_daily.py 执行失败，退出码: $LASTEXITCODE"
    }

    # 提交并推送
    Log "提交 output 到 git ..."
    git add output/ -f
    git diff --cached --quiet
    $hasChanges = ($LASTEXITCODE -ne 0)
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

