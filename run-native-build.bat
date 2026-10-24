@echo off
set "ANDROID_NDK_HOME=C:\Users\sebue\hc-buildtools\android-sdk\ndk\26.3.11579264"
powershell -ExecutionPolicy Bypass -File packaging\build-apk-native.ps1 -Abi arm64-v8a -Res 1600x960 > native-build-arm64.log 2> native-build-arm64.err