[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'

$android = 'c:/Users/sebue/Documents/N7SIX/Software/HamClock/android'
$repo = 'c:/Users/sebue/Documents/N7SIX/Software/HamClock'
$logFile = Join-Path $repo 'packaging/gradle-build-final.log'

# Build debug APK
Write-Output "Building debug APK..."
Push-Location $android
try {
    & "$android/gradlew.bat" assembleDebug --no-daemon --warning-mode summary 2>&1 | Out-File -FilePath $logFile -Encoding UTF8
    $exit = $LASTEXITCODE
} finally {
    Pop-Location
}

Write-Output "Gradle exit code: $exit"

if ($exit -ne 0) {
    Write-Output "=== GRADLE BUILD FAILED ==="
    Get-Content $logFile | Select-Object -First 100
    exit $exit
}

# Find the APK
$apk = Get-ChildItem (Join-Path $android 'app/build/outputs/apk/debug/*.apk') -ErrorAction SilentlyContinue |
    Sort-Object Length -Descending | Select-Object -First 1

if (-not $apk) {
    Write-Output "No APK found!"
    Get-Content $logFile | Select-Object -First 50
    exit 1
}

# Copy to dist folder
$distDir = Join-Path $repo 'dist'
if (-not (Test-Path $distDir)) {
    New-Item -ItemType Directory -Path $distDir -Force | Out-Null
}

$final = Join-Path $distDir "n7six.HamClock.v7.6.1.apk"
Copy-Item $apk.FullName $final -Force

Write-Output "========================================"
Write-Output " APK BUILD SUCCESSFUL"
Write-Output " APK: $final"
Write-Output " Size: $([math]::Round((Get-Item $final).Length/1MB, 1)) MB"
Write-Output "========================================"
