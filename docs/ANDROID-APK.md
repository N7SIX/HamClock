# Building the Android APK (N7SIX HamClock)

This repo now produces **two** installers:

| Platform | Artifact | How |
|---|---|---|
| Windows | `mingw-web-<res>.exe` | `packaging/build-*.sh`, or `make mingw-web-*` |
| Android | `n7six.HamClock.v7.6.1.apk` | `android/` Gradle project + `packaging/build-apk.ps1` |

The Android app is a small Kotlin **WebView launcher** around the **same
native C++ web-server** the desktop/Termux builds use. It bundles a per-ABI
`hamclock` executable (built with the Android **NDK**) as a native library
(`libhamclock.so`), which the package manager extracts to the app's executable
`nativeLibraryDir`. `MainActivity` runs it as a child process on its default
ports (`8080` RESTful, `8081` interactive UI, `8082` read-only) and displays
`http://127.0.0.1:8081/live.html` in a full-screen WebView. No external web
server, no X11, no framebuffer — the clock runs entirely on-device.

---

## 1. One-time toolchain setup

You need: **JDK 17**, the **Android SDK** (platform 34 + build-tools), and the
**Android NDK**.

If you have the SDK/NDK installed already, just point the environment at them:

```powershell
$env:ANDROID_HOME      = "C:\Users\sebue\Android\Sdk"
$env:ANDROID_NDK_HOME  = "C:\Users\sebue\Android\Sdk\ndk\26.1.10909125"
```

A convenience script installs the cmdline-tools, SDK packages, and NDK into
`C:\Users\sebue\hc-buildtools` (used by the automated build):

```powershell
powershell -ExecutionPolicy Bypass -File packaging\setup-android-sdk.ps1
```

---

## 2. Build everything (native + APK)

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build-apk.ps1
```

This will:
1. Cross-compile `hamclock` for `arm64-v8a`, `armeabi-v7a`, `x86_64`, `x86`
   via `packaging\build-apk-native.sh` (NDK clang++).
2. Stage each binary to `android\app\src\main\jniLibs\<abi>\libhamclock.so`.
3. Run `gradlew assembleRelease`.
4. Emit **`n7six.HamClock.v7.6.1.apk`** in `<repo>\dist\` (e.g. `C:\Users\sebue\Documents\N7SIX\Software\HamClock\dist\`).

The APK is **debug-signed** so it installs directly. Re-sign with your own
keystore before publishing to an app store.

Install to a connected device:

```powershell
adb install -r C:\Users\sebue\Documents\N7SIX\Software\HamClock\dist\n7six.HamClock.v7.6.1.apk
```

---

## 3. Building a single ABI / resolution

Edit `packaging\build-apk-native.sh` (the `RES="1600x960"` line) to change the
built-in resolution, or build one ABI manually:

```bash
export ANDROID_NDK_HOME=/c/Users/sebue/hc-buildtools/android-ndk-r26d
./packaging/build-apk-native.sh arm64-v8a
```

Then assemble:

```powershell
cd android
.\gradlew.bat assembleRelease
```

---

## 4. What gets bundled (jniLibs, so it is executable)

```
android/app/src/main/
  jniLibs/arm64-v8a/libhamclock.so    <- native server (ELF, packaged as a .so)
  jniLibs/armeabi-v7a/libhamclock.so
  jniLibs/x86_64/libhamclock.so
  jniLibs/x86/libhamclock.so
  kotlin/.../MainActivity.kt           <- exec()s it from nativeLibraryDir
```

The binary ships as a **native library**, not an asset. Android 10+ forbids
`exec()` of files in the app's data home dir (`getFilesDir()`), so extracting it
there fails with `error=13, Permission denied`. Packaging it under `jniLibs`
instead makes the package manager extract it to the app's `nativeLibraryDir` at
install time — that directory **is** executable. Gradle sets
`jniLibs.useLegacyPackaging true` so the `.so` lands on disk as a real file.

At runtime `MainActivity`:
- resolves `applicationInfo.nativeLibraryDir/libhamclock.so` (no copy, no
  `chmod`, no ABI selection — the OS already extracted the correct ABI),
- launches it on its **default ports** (RESTful 8080, R/W live 8081, R/O live
  8082), setting `HOME`/`USERPROFILE` to `filesDir` — the C++
  `defaultAppDir()` reads `getenv("HOME")` and throws if it is unset (it is on
  Android), which would crash the child at startup,
- waits for `http://127.0.0.1:8081/live.html` to answer,
- shows it in the WebView, proxying `http://127.0.0.1:8081/` requests through
  `shouldInterceptRequest`. The clock's WebSocket (`ws://127.0.0.1:8081/live-ws`)
  connects directly over loopback; `usesCleartextTraffic` is enabled for that.

---

## 5. Notes & limits

- **minSdk 17** (Android 4.2). The `termux/disable-fdsan.c` shim is linked in to
  stop Android's *file-descriptor sanitizer* from aborting the process.
- The app requests only `INTERNET` / `ACCESS_NETWORK_STATE` / `WAKE_LOCK`.
- The server binds all interfaces (`0.0.0.0`) on ports 8080–8082 — the WebView
  only talks to it over `127.0.0.1`, but on an untrusted network those ports are
  reachable from the LAN. Bind to loopback in the server config if that matters
  for your deployment.
- All C++ is compiled with `-static-libstdc++`, so the executable is
  self-contained and needs no extra `.so` next to it.

---

## 6. Troubleshooting

| Symptom | Fix |
|---|---|
| `ANDROID_NDK_HOME is not set` | Install the NDK / set the env var (see §1). |
| `Missing staged binary: …\bin\arm64-v8a\hamclock` | Native build step failed — run `build-apk-native.sh` alone and read its output. |
| `SDK location not found` | Set `$env:ANDROID_HOME` or create `android/local.properties` with `sdk.dir=…`. |
| WebView shows "failed to start" | Check `adb logcat -s HamClock`; the native server prints its startup/usage there. |
