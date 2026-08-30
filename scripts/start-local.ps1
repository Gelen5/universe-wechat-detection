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
& "C:\Python314\python.exe" -m uvicorn server.main:app --host 127.0.0.1 --port 8000
