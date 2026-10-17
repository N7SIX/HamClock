<#
  Build HamClock debug APK with extended timeout.
  Run until complete - doesn't use the 30s command timeout.
#>
$repo = 'c:/Users/sebue/Documents/N7SIX/Software/HamClock'
$android = Join-Path $repo 'android'
$logFile = Join-Path $repo 'packaging/gradle-build-ext.log'
$apkFile = Join-Path $android 'app/build/outputs/apk/debug/n7six.HamClock.v7.6.1-debug.apk'
$distFile = Join-Path $repo 'dist/n7six.HamClock.v7.6.1.apk'

# Clean any stale build
Remove-Item -Recurse -Force (Join-Path $android 'app/build/intermediates') -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force (Join-Path $android 'app/build/kotlin') -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force (Join-Path $android 'app/build/tmp') -ErrorAction SilentlyContinue

Write-Output "=== Starting Gradle build (background) ==="
Push-Location $android
try {
    & 'c:/Users/sebue/Documents/N7SIX/Software/HamClock/android/gradlew.bat' assembleDebug --no-daemon --warning-mode summary 2>&1 | Out-File -FilePath $logFile -Encoding UTF8
    $exit = $LASTEXITCODE
} finally {
    Pop-Location
}

Write-Output "=== Build finished with exit code: $exit ==="

# Find APK
$apk = Get-ChildItem (Join-Path $android 'app/build/outputs/apk/debug/*.apk') -ErrorAction SilentlyContinue |
    Sort-Object Length -Descending | Select-Object -First 1

if ($apk) {
    Write-Output "APK found: $($apk.FullName)"
    # Copy to dist
    if (Test-Path $distFile) { Remove-Item $distFile -Force }
    Copy-Item $apk.FullName $distFile -Force
    Write-Output "Copied to: $distFile"
    Write-Output "Size: $([math]::Round((Get-Item $distFile).Length/1MB, 1)) MB"
} else {
    Write-Output "No APK found!"
    Get-Content $logFile | Select-Object -First 80
}
