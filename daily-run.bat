@echo off
:: Daily Photo Coach - 每日定时运行
:: 由 Windows 任务计划程序调用

:: === 在这里填入你的密钥 ===
set UNSPLASH_ACCESS_KEY=你的Unsplash密钥
set LLM_BEARER_TOKEN=你的LLM密钥
:: =========================

cd /d E:\daily-photo-coach
powershell -ExecutionPolicy Bypass -File daily-run.ps1
