#!/usr/bin/env bash
# =============================================================================
# Copyright 2026 Sean, N7SIX
# =============================================================================
# build-apk-native.sh  —  N7SIX HamClock  —  cross-compile the native server
# =============================================================================
# Compiles the SAME web-only HamClock executable that the desktop/Termux builds
# produce, but for Android using the NDK toolchain, for one ABI at a time.
#
# The output is a standalone executable (a normal ELF, NOT a shared library). It is
# bundled into the APK under app/src/main/jniLibs/<abi>/libhamclock.so and exec()'d
# at runtime by MainActivity. Shipping it as a native lib lets the package manager
# extract it to the executable nativeLibraryDir -- Android 10+ forbids exec() of files
# in the app's private data dir. Because it's a real process it can bind its own ports.
#
# Usage:
#   ANDROID_NDK_HOME=/path/to/ndk ./build-apk-native.sh <abi> [outdir]
#
# Example:
#   ANDROID_NDK_HOME=~/android-ndk-r26b ./build-apk-native.sh arm64-v8a
#
# ABIs: arm64-v8a | armeabi-v7a | x86_64 | x86
# =============================================================================
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"

ABI="${1:-arm64-v8a}"
# NDK r26 floors at API 21 for 64-bit / 19 for 32-bit; the Gradle minSdk stays
# 17 so one APK installs on 4.2.2 (old 32-bit tablets run armeabi-v7a).
# Per-ABI floor keeps the compiler pointed at an existing sysroot.
case "$ABI" in
  arm64-v8a|armeabi-v7a|x86_64|x86)   MIN_API=21 ;;
  *) echo "Unknown ABI: $ABI"; exit 1 ;;
esac
API="$MIN_API"                        # effective NDK target for this ABI
RES="1600x960"                            # clock resolution

: "${ANDROID_NDK_HOME:?Set ANDROID_NDK_HOME to your Android NDK root}"
NDK="$ANDROID_NDK_HOME"
TOOLCHAIN="$NDK/toolchains/llvm/prebuilt/linux-x86_64"
# Windows hosts use windows-x86_64:
[ -d "$TOOLCHAIN" ] || TOOLCHAIN="$NDK/toolchains/llvm/prebuilt/windows-x86_64"
[ -d "$TOOLCHAIN" ] || TOOLCHAIN="$NDK/toolchains/llvm/prebuilt/darwin-x86_64"
BIN="$TOOLCHAIN/bin"
[ -d "$BIN" ] || { echo "NDK toolchain bin not found under $NDK"; exit 1; }

# Map ABI -> NDK target triple + arch for the compiler wrapper
case "$ABI" in
  arm64-v8a)   TRIPLE="aarch64-linux-android" ;;
  armeabi-v7a) TRIPLE="armv7a-linux-androideabi" ;;
  x86_64)      TRIPLE="x86_64-linux-android" ;;
  x86)         TRIPLE="i686-linux-android" ;;
  *) echo "Unknown ABI: $ABI"; exit 1 ;;
esac

CLANG="$BIN/${TRIPLE}${API}-clang++"
CLANG_C="$BIN/${TRIPLE}${API}-clang"
AR="$BIN/llvm-ar"
RANLIB="$BIN/llvm-ranlib"
STRIP="$BIN/llvm-strip"
[ -x "$CLANG" ] || { echo "Compiler not found: $CLANG"; exit 1; }

BUILD="$(mktemp -d)"
trap 'rm -rf "$BUILD"' EXIT

# Flags reproducing the Makefile web target + Termux Android fixes.
#  -D_WEB_ONLY           headless web server (no X11/framebuffer)
#  -D_CLOCK_1600x960     resolution (via RES)
INC="-I$REPO/include -I$REPO/src -I$REPO/ArduinoLib -I$REPO/wsServer/include -I$REPO/zlib-hc -I$REPO"
CXXFLAGS="-std=c++17 -O2 -g -fPIC -pthread -D_WEB_ONLY -D__ANDROID__ -D_CLOCK_${RES} $INC -Wno-unused-function"

echo ">> Building native server for ABI=$ABI  target=$TRIPLE  API=$API"
echo "   NDK=$NDK"

# --- compile helper ---------------------------------------------------------
OBJS=()
compile() { # $1 = source file, $2 = compiler
  local src="$1" cc="$2"
  local obj="$BUILD/$(echo "${src#$REPO/}" | tr '/' '_').o"
  "$cc" $CXXFLAGS -c "$src" -o "$obj"
  OBJS+=("$obj")
}

# --- sub-libraries ----------------------------------------------------------
# (compiled straight into the executable; we still build .a to mirror Makefiles)
echo ">> ArduinoLib"; for f in "$REPO"/ArduinoLib/*.cpp; do compile "$f" "$CLANG"; done
echo ">> wsServer";   for f in "$REPO"/wsServer/src/*.cpp; do compile "$f" "$CLANG"; done
echo ">> zlib-hc";    for f in "$REPO"/zlib-hc/*.cpp;    do compile "$f" "$CLANG"; done
echo ">> src ($RES)"; for f in "$REPO"/src/*.cpp;        do compile "$f" "$CLANG"; done
echo ">> termux/android-stubs"; compile "$REPO/termux/android-stubs.cpp" "$CLANG"

# --- Android fdsan abort workaround (from termux/) --------------------------
FDSAN="$BUILD/disable-fdsan.o"
"$CLANG_C" -fPIC -c "$REPO/termux/disable-fdsan.c" -o "$FDSAN"
OBJS+=("$FDSAN")

# --- link the executable ----------------------------------------------------
OUT="$BUILD/hamclock"
echo ">> Linking $OUT"
"$CLANG" $CXXFLAGS -o "$OUT" "${OBJS[@]}" \
    -static-libstdc++ -ldl -llog -lz -lm
"$STRIP" "$OUT"

# --- stage into APK jniLibs --------------------------------------------------
# N.B. must be named lib*.so for Gradle to package it as a native library; the
# package manager then extracts it to the executable nativeLibraryDir at install.
OUTDIR="${2:-$REPO/android/app/src/main/jniLibs/$ABI}"
mkdir -p "$OUTDIR"
cp "$OUT" "$OUTDIR/libhamclock.so"
echo ">> Staged: $OUTDIR/libhamclock.so ($(du -h "$OUTDIR/libhamclock.so" | cut -f1))"

# sanity: it must be an Android ELF for the right arch
file "$OUTDIR/libhamclock.so" || true
echo ">> DONE ($ABI)"
