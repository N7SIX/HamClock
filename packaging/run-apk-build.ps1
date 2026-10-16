# =============================================================================
# run-apk-build.ps1  —  N7SIX HamClock  —  wrapper: set NDK env, build APK
# =============================================================================
# Natives are assumed already staged (use packaging/rebuild-apk.ps1 or
# packaging/build-apk-native.ps1 first). Sets ANDROID_NDK_HOME then runs
# packaging/build-apk.ps1 -SkipNative.
# =============================================================================
$ErrorActionPreference = 'Stop'
$Repo  = 'C:\Users\sebue\Documents\N7SIX\Software\HamClock'
$env:ANDROID_NDK_HOME = 'C:\Users\sebue\hc-buildtools\android-sdk\ndk\26.3.11579264'
$env:ANDROID_HOME     = 'C:\Users\sebue\hc-buildtools\android-sdk'
& (Join-Path $Repo 'packaging\build-apk.ps1') -SkipNative -Repo $Repo
