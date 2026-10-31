param(
    # 关掉热重载（需要复现「干净启动」时用）
    [switch]$NoReload,
    # 端口，默认 8000
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$variableNames = @(
    "WECHAT_TEXT_API_KEY",
    "WECHAT_IMAGE_API_KEY",
    "WECHAT_API_BASE_URL",
    "WECHAT_TEXT_MODEL",
    "WECHAT_IMAGE_MODEL",
    "WECHAT_API_ACTOR_AUTH",
    "WECHAT_API_VERIFY_SSL"
)

foreach ($variableName in $variableNames) {
    $variableValue = [Environment]::GetEnvironmentVariable($variableName, "User")
    if ($variableValue) {
        Set-Item -Path "Env:$variableName" -Value $variableValue
    }
}

$env:PYTHONPATH = $projectRoot
if (-not $env:CREATOR_OWNER_EMAIL) {
    $env:CREATOR_OWNER_EMAIL = "gelen5@163.com"
}
Set-Location $projectRoot

# 热重载只监听 Python 源码目录：
#  - server/ 是唯一的应用代码来源
#  - 故意不监听 static/、vendor/、output/、tests/：static 每次请求都从磁盘读，
#    改样式刷新浏览器即可；把这几万文件纳入监听会拖慢启动并触发无意义的重启
#  - vendor/ 下的 Skill 文本是调用时才读，改完下次调用自然生效
$uvicornArgs = @(
    "-m", "uvicorn", "server.main:app",
    "--host", "127.0.0.1",
    "--port", "$Port"
)

if ($NoReload) {
    Write-Host "[start-local] 热重载已关闭" -ForegroundColor Yellow
} else {
    $uvicornArgs += @(
        "--reload",
        "--reload-dir", "server",
        "--reload-delay", "0.5"
    )
    Write-Host "[start-local] 热重载已开启：改 server/*.py 会自动重启，改 static/* 刷新浏览器即可" -ForegroundColor Green
}

Write-Host "[start-local] http://127.0.0.1:$Port/" -ForegroundColor Cyan
& "C:\Python314\python.exe" @uvicornArgs
