package my.hamradio.n7six.hamclock

import android.Manifest
import android.annotation.SuppressLint
import android.content.Context
import android.content.pm.PackageManager
import android.location.Location
import android.location.LocationListener
import android.location.LocationManager
import android.os.Build
import android.os.Bundle
import android.os.Looper
import android.util.Log
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import kotlin.concurrent.thread

/**
 * Bundles the native `hamclock` web-server executable (built per-ABI by
 * packaging/build-apk-native.ps1 into app/src/main/jniLibs/<abi>/libhamclock.so),
 * runs it as a child process bound to 127.0.0.1, and shows the clock UI in a
 * WebView.
 *
 * The binary ships as a native library so the package manager extracts it to the
 * executable nativeLibraryDir at install time (Android 10+ forbids execve() of
 * files in the app's data home dir).
 */
class MainActivity : AppCompatActivity() {

    companion object {
        private const val TAG = "HamClock"
        // HamClock ports (see include/ArduinoLib.h):
        //   8080 = RESTful API + screenshots (NOT the UI)
        //   8081 = interactive read/write live web UI  <-- the clock (live.html)
        //   8082 = read-only live web UI
        // We start the native server on its DEFAULT ports and load the R/W UI.
        private const val RW_PORT = 8081
        private const val REST_PORT = 8080
        private const val URL_TO_LOAD = "http://127.0.0.1:$RW_PORT/live.html"
        private const val REQ_LOC = 1001
        // Match native gpsd/nmea follow thresholds:
        // FOLLOW_MIND = 3 miles (~4828m), FOLLOW_DT = 5 min
        private const val MIN_DIST_M = 4828f
        private const val MIN_TIME_MS = 5 * 60 * 1000L
    }

    private var serverProc: Process? = null
    private var locationManager: LocationManager? = null
    private var gpsListener: LocationListener? = null
    @Volatile private var serverReady = false
    @Volatile private var lastPushedLat: Double? = null
    @Volatile private var lastPushedLng: Double? = null
    @Volatile private var lastPushMs: Long = 0L
    @Volatile private var pendingLat: Double? = null
    @Volatile private var pendingLng: Double? = null

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        requestLocationPermissionIfNeeded()
        loadLastKnownPush()
        val web = WebView(this)
        setContentView(web)

        web.settings.javaScriptEnabled = true
        web.settings.domStorageEnabled = true
        web.webViewClient = object : WebViewClient() {
            override fun shouldInterceptRequest(
                view: WebView, request: WebResourceRequest
            ): WebResourceResponse? {
                val u = request.url.toString()
                return if (u.startsWith("http://127.0.0.1:$RW_PORT/")) {
                    try {
                        val conn = (URL(u).openConnection() as HttpURLConnection).apply {
                            requestMethod = "GET"
                            connectTimeout = 3000
                            readTimeout = 5000
                        }
                        val ct = conn.contentType ?: "text/html"
                        WebResourceResponse(
                            ct.substringBefore(';'), "UTF-8", conn.inputStream
                        )
                    } catch (e: Exception) {
                        Log.w(TAG, "proxy $u failed: ${e.message}")
                        null
                    }
                } else null
            }
        }

        thread(name = "hamclock-native") {
            try {
                val bin = nativeServerFile()
                // Launch with DEFAULT ports so RESTful(8080), R/W live(8081) and
                // R/O live(8082) all come up. Passing -w 8080 would collide with
                // the RESTful port and the app validates/aborts on that.
                //
                // HOME must be set: the C++ code does `std::string home =
                // getenv("HOME")` during startup (ArduinoLib/Arduino.cpp), which
                // throws std::logic_error and crashes the process if HOME is
                // unset (as it is on Android). Point it at the app's private dir.
                // First-run auto-location: on the very first launch the config
                // dir (~/.hamclock/) does not exist yet. In that case add "-g -k"
                // so the server geolocates the device's Latitude/Longitude from its
                // public IP and skips the manual setup screen -- beginners never
                // have to enter raw coordinates. geolocateIP() also fills in the
                // Maidenhead grid and timezone. Later launches omit the flags so a
                // location the user sets by hand is never overwritten by a fresh
                // IP lookup. (N.B. -k is required by -g; see ArduinoLib/Arduino.cpp)
                val firstRun = !File(filesDir, ".hamclock").exists()
                val cmd = mutableListOf(bin.absolutePath)
                if (firstRun) {
                    cmd += "-g"   // auto-locate DE lat/long/grid/tz from public IP
                    cmd += "-k"   // required by -g; skip the manual setup screen
                    Log.i(TAG, "first run: launching with -g -k (IP auto-geolocation)")
                }
                val pb = ProcessBuilder(*cmd.toTypedArray())
                    .directory(filesDir)
                    .redirectErrorStream(true)
                pb.environment()["HOME"] = filesDir.absolutePath
                pb.environment()["USERPROFILE"] = filesDir.absolutePath
                serverProc = pb.start()
                Log.i(TAG, "native server started bin=${bin.absolutePath} home=${filesDir.absolutePath}")
                // Drain stdout so the child never blocks on a full pipe.
                serverProc!!.inputStream.bufferedReader().forEachLine { Log.i(TAG, it) }
            } catch (e: Exception) {
                Log.e(TAG, "native server failed", e)
            }
        }

        // Poll until the server answers, then load the UI and start GPS follow.
        thread {
            if (waitForServer()) {
                serverReady = true
                flushPendingGps()
                runOnUiThread { web.loadUrl(URL_TO_LOAD) }
            } else {
                runOnUiThread {
                    web.loadData(
                        "<h2>HamClock failed to start</h2>" +
                            "<p>The native server did not open port $RW_PORT. " +
                            "See logcat (tag HamClock) for details.</p>",
                        "text/html", "UTF-8"
                    )
                }
            }
        }
    }

    /**
     * Returns the native server executable from the app's nativeLibraryDir.
     *
     * The binary is packaged as a native library (libhamclock.so), so the package
     * manager extracts it to nativeLibraryDir at install time. That directory is
     * executable (unlike filesDir on Android 10+), so we can exec it directly.
     * No per-ABI selection is needed here — the OS already placed the right ABI.
     */
    private fun nativeServerFile(): File {
        val f = File(applicationInfo.nativeLibraryDir, "libhamclock.so")
        if (!f.exists()) {
            throw IllegalStateException(
                "native server binary missing: ${f.absolutePath} " +
                    "(nativeLibraryDir=${applicationInfo.nativeLibraryDir})"
            )
        }
        return f
    }

    private fun waitForServer(timeoutMs: Long = 20_000): Boolean {
        val deadline = System.currentTimeMillis() + timeoutMs
        while (System.currentTimeMillis() < deadline) {
            try {
                val conn = (URL(URL_TO_LOAD).openConnection() as HttpURLConnection).apply {
                    requestMethod = "GET"; connectTimeout = 800; readTimeout = 800
                }
                if (conn.responseCode in 200..499) { conn.inputStream.close(); return true }
                conn.disconnect()
            } catch (e: Exception) { /* not up yet */ }
            Thread.sleep(300)
        }
        return false
    }

    override fun onDestroy() {
        super.onDestroy()
        try { serverProc?.destroy() } catch (e: Exception) { }
    }
}
