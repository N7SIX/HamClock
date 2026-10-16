[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'

$android = 'c:/Users/sebue/Documents/N7SIX/Software/HamClock/android'
$repo = 'c:/Users/sebue/Documents/N7SIX/Software/HamClock'

# Clean previous build
Write-Output "Cleaning previous build..."
Remove-Item -Recurse -Force (Join-Path $android 'app/build') -ErrorAction SilentlyContinue

# Build debug APK
Write-Output "Building debug APK..."
Push-Location $android
try {
    & "$android/gradlew.bat" assembleDebug --no-daemon --warning-mode summary
    $exit = $LASTEXITCODE
} finally {
    Pop-Location
}

Write-Output "Gradle exit code: $exit"
if ($exit -ne 0) {
    Write-Output "Gradle build FAILED"
    exit $exit
}

# Copy APK to dist folder
$apk = Get-ChildItem (Join-Path $android 'app/build/outputs/apk/debug/*.apk') -ErrorAction SilentlyContinue |
    Sort-Object Length -Descending | Select-Object -First 1

if (-not $apk) {
    Write-Output "No APK found!"
    exit 1
}

$distDir = Join-Path $repo 'dist'
if (-not (Test-Path $distDir)) {
    New-Item -ItemType Directory -Path $distDir -Force | Out-Null
}

$final = Join-Path $distDir "n7six.HamClock.v7.6.1.apk"
Copy-Item $apk.FullName $final -Force

Write-Output "APK READY: $final"
Write-Output "Size: $([math]::Round((Get-Item $final).Length/1MB, 1)) MB"
