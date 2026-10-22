# R8 / minification rules for N7SIX HamClock.
# The native HamClock server is a bundled executable (assets/bin/<abi>/hamclock),
# launched as a child process — there are no JNI symbols to keep. Nothing special
# is required here; this file is intentionally minimal.

# Keep the MainActivity and its related classes
-keep class my.hamradio.n7six.hamclock.MainActivity { *; }
-keep class my.hamradio.n7six.hamclock.R { *; }

# Keep location-related classes (for runtime permission handling)
-keep class * extends java.lang.Exception { *; }

# Keep WebView-related classes
-keepclassmembers class android.webkit.WebViewClient { *; }
-keepclassmembers class android.webkit.WebView { *; }

# Keep location and permission constants
-keep enum android.Manifest$permission { *; }

