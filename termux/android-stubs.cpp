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
 *   - android_open_url()        -> launch the browser via "am start" ACTION_VIEW (see below).
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
void android_request_restart(bool minus_K, bool minus_0)
{
    (void)minus_K;
    if (g_progpath[0]) {
        /* Replace this process image with a fresh copy of the same binary.
         * Pass "-0" when minus_0 is set so the restarted process deletes its
         * EEPROM storage (factory reset) before reinitializing via defaultState(). */
        char *const argv[] = {
            g_progpath,
            minus_0 ? (char *)"-0" : nullptr,
            nullptr,
        };
        execv(g_progpath, argv);
    }
    /* If execv failed, fall back to a clean exit. */
    _exit(0);
}

/* Open url with the device's browser or other handler app. We run as a plain
 * child process with no JNI/Activity host, so go through the am command-line
 * tool, which issues ACTION_VIEW under our own app identity -- launching a
 * browser for a VIEW intent is a normal, caller-permission-free activity start.
 * This is the fallback for touches not classified as Live Web (keyboard,
 * future native UI); Live Web sessions go through openLiveWebURL() instead and
 * the WebView shows the page itself.
 */
void android_open_url(const char *url)
{
    if (!url || !*url)
        return;

    /* single-quote the url for sh; escape any embedded single quote by ending
     * the quoted span, emitting an escaped quote, and reopening it */
    char quoted[1100];
    size_t q = 0;
    for (const char *p = url; *p && q < sizeof(quoted) - 4; p++) {
        if (*p == '\'') {
            quoted[q++] = '\''; quoted[q++] = '\\';
            quoted[q++] = '\''; quoted[q++] = '\'';
        } else {
            quoted[q++] = *p;
        }
    }
    quoted[q] = '\0';

    char cmd[sizeof(quoted) + 100];
    snprintf (cmd, sizeof(cmd),
              "/system/bin/am start -a android.intent.action.VIEW -d '%s' >/dev/null 2>&1",
              quoted);
    int rc = system (cmd);
    printf ("android_open_url: rc=%d url=%s\n", rc, url);
}

/* Clipboard is managed by the Android WebView (navigator.clipboard in
 * live.html), not by the native process. Report "no clipboard text" so the
 * caller falls back to the web paste path. */
bool android_get_clipboard(char *buf, size_t buf_len)
{
    if (buf && buf_len) buf[0] = '\0';
    return false;
}

/* Provide random() and srandom() for older Android Bionic libc (API 17) */
long random(void)
{
    return rand();
}

void srandom(unsigned int seed)
{
    srand(seed);
}

} /* extern "C" */
