# =============================================================================
# rebuild-apk.ps1  —  N7SIX HamClock  —  full rebuild: native server + APK
# =============================================================================
# Rebuilds the native HamClock server (arm64-v8a) with the NDK, then builds
# and signs the release APK via packaging/build-apk.ps1. Run from any cwd:
#   powershell -ExecutionPolicy Bypass -File packaging\rebuild-apk.ps1
# =============================================================================
[CmdletBinding()]
param(
    [string[]]$Abis = @('arm64-v8a', 'armeabi-v7a', 'x86_64', 'x86'),
    [string]$Repo = 'C:\Users\sebue\Documents\N7SIX\Software\HamClock'
)
$ErrorActionPreference = 'Stop'

$env:ANDROID_NDK_HOME = 'C:\Users\sebue\hc-buildtools\android-sdk\ndk\26.3.11579264'
if (-not (Test-Path (Join-Path $env:ANDROID_NDK_HOME 'toolchains'))) {
    throw "NDK not found at $env:ANDROID_NDK_HOME"
}

Write-Output '==> Step 1/2: cross-compile native server (all ABIs)'
foreach ($a in $Abis) {
    & (Join-Path $Repo 'packaging\build-apk-native.ps1') -Abi $a -Repo $Repo
    if ($LASTEXITCODE -ne 0) { throw "Native build failed for $a" }
}

Write-Output '==> Step 2/2: build APK (natives already staged)'
& (Join-Path $Repo 'packaging\build-apk.ps1') -Abis $Abis -SkipNative
if ($LASTEXITCODE -ne 0) { throw 'APK build failed' }

Write-Output '==> Rebuild complete'
