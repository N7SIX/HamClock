/*
 * android-stubs.cpp
 * ---------------------------------------------------------------------------
 * N7SIX HamClock — standalone Android platform callbacks.
 *
 * When built for Android (__ANDROID__ -> _IS_ANDROID), the C++ code calls a
 * handful of `android_*` functions that the *official* APK supplies through a
 * JNI Activity (see include/ArduinoLib.h). Those symbols are declared and used
 * but never defined in this repo, so a plain standalone executable (like the
 * Termux build, or the WebView-launcher APK produced by packaging/) would fail
 * to link with "undefined symbol: android_get_clipboard".
 *
 * This file provides minimal, self-contained implementations so the same binary
 * runs as an ordinary child process with no JNI/Activity host:
 *
 *   - android_request_exit()    -> terminate the process cleanly.
 *   - android_request_restart() -> re-exec ourselves (optionally dropping -K).
 *   - android_open_url()        -> no-op (the WebView launcher opens links).
 *   - android_get_clipboard()   -> return false (WebView handles paste in JS).
 * ---------------------------------------------------------------------------
 */
#include <unistd.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>

extern "C" {

/* Save argv[0] path at startup so restart can re-exec the same binary. */
static char g_progpath[1024] = {0};

__attribute__((constructor))
static void android_stubs_init(void)
{
    ssize_t n = readlink("/proc/self/exe", g_progpath, sizeof(g_progpath) - 1);
    if (n > 0) g_progpath[n] = '\0';
}

/* Terminate the whole process. doExit() would otherwise spin in for(;;). */
void android_request_exit(void)
{
    _exit(0);
}

/* Re-launch ourselves so HamClock restarts with fresh state.
 * minus_K mirrors the upstream "keep showing splash/keep settings" flag; when
 * set we simply relaunch without any special flag. */
void android_request_restart(bool minus_K)
{
    (void)minus_K;
    if (g_progpath[0]) {
        /* Replace this process image with a fresh copy of the same binary. */
        char *const argv[] = { g_progpath, nullptr };
        execv(g_progpath, argv);
    }
    /* If execv failed, fall back to a clean exit. */
    _exit(0);
}

/* No standalone browser intent available; the WebView launcher intercepts
 * external links, so this is intentionally a no-op. */
void android_open_url(const char *url)
{
    (void)url;
}

/* Clipboard is managed by the Android WebView (navigator.clipboard in
 * live.html), not by the native process. Report "no clipboard text" so the
 * caller falls back to the web paste path. */
bool android_get_clipboard(char *buf, size_t buf_len)
{
    if (buf && buf_len) buf[0] = '\0';
    return false;
}

} /* extern "C" */
