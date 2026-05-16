@echo off
:: Daily Photo Coach - 每日定时运行
:: 由 Windows 任务计划程序调用
:: 密钥从 config.yaml 读取（已 gitignore）

cd /d E:\daily-photo-coach
powershell -ExecutionPolicy Bypass -File daily-run.ps1
