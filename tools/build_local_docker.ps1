# OpenSMS Local Android APK Build Script using Docker
# Run this script on Windows PowerShell whenever Docker Desktop is running.

$ErrorActionPreference = "Stop"

Write-Host "==> Checking Docker Desktop status..." -ForegroundColor Cyan
try {
    docker version | Out-Null
} catch {
    Write-Host "Error: Docker Desktop is not running. Please start Docker Desktop and try again." -ForegroundColor Red
    exit 1
}

$repoRoot = (Get-Item $PSScriptRoot).Parent.FullName
$appDir = Join-Path $repoRoot "app"

Write-Host "==> Repository root: $repoRoot" -ForegroundColor Cyan
Write-Host "==> Building Android APK via Kivy/Buildozer container..." -ForegroundColor Cyan

docker run --rm `
    -v "${repoRoot}:/home/user/hostcwd" `
    -w /home/user/hostcwd/app `
    kivy/buildozer `
    android debug

if ($LASTEXITCODE -eq 0) {
    Write-Host "==> Local build successful! APK is located in app/bin/" -ForegroundColor Green
    Get-ChildItem (Join-Path $appDir "bin/*.apk") | ForEach-Object {
        Write-Host "    $($_.FullName) ($([math]::Round($_.Length / 1MB, 2)) MB)" -ForegroundColor Yellow
    }
} else {
    Write-Host "==> Local build failed with exit code $LASTEXITCODE" -ForegroundColor Red
    exit $LASTEXITCODE
}

