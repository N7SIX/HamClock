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
import android.os.Message
import android.util.Log
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Button
import android.widget.FrameLayout
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import kotlin.concurrent.thread
import kotlin.math.absoluteValue

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
        // REST endpoint for updating the default DE
        private const val SET_NEWDE = "http://127.0.0.1:$REST_PORT/set_newde"
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

    // ---- In-app overlay web pages (movies, QR "Open" links, ...) ----
    // Any page that is NOT served by the local HamClock server is shown in
    // this full-screen overlay WebView instead of hijacking the clock UI.
    // Dismiss it with the X button or the system back gesture/button.
    private var movieView: WebView? = null
    private var movieRoot: FrameLayout? = null

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        requestLocationPermissionIfNeeded()
        loadLastKnownPush()
        val root = FrameLayout(this)
        val web = WebView(this)
        root.addView(
            web,
            FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT
            )
        )
        setContentView(root)

        web.settings.javaScriptEnabled = true
        web.settings.domStorageEnabled = true
        web.settings.mediaPlaybackRequiresUserGesture = false
        web.settings.setSupportMultipleWindows(true)
        web.settings.loadWithOverviewMode = true
        web.settings.useWideViewPort = true
        // Keep the clock UI itself inside this WebView; route ALL other pages
        // (QR "Open Movie" links, window.open popups, link taps) to the
        // overlay viewer with its X close button instead.
        web.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                val u = request.url.toString()
                Log.d(TAG, "shouldOverrideUrlLoading: $u (local=${isLocalHamClockUrl(u)})")
                // Same-host pages (the clock) stay in place. Anything else is
                // remote content the user asked to see -- show it in the
                // overlay so they can X back out to the clock.
                return if (isLocalHamClockUrl(u)) {
                    false
                } else {
                    openExternalInOverlay(u)
                    true
                }
            }

            override fun onPageFinished(view: WebView, url: String) {
                super.onPageFinished(view, url)
                if (!serverReady) {
                    serverReady = true
                }
            }

            override fun shouldInterceptRequest(view: WebView, request: WebResourceRequest): WebResourceResponse? {
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

        // Intercept window.open() popups (e.g. "Open Movie" links) and route
        // them to the overlay viewer instead of being blocked.
        web.webChromeClient = object : WebChromeClient() {
            override fun onCreateWindow(
                view: WebView, isDialog: Boolean, isUserGesture: Boolean, resultMsg: Message
            ): Boolean {
                Log.d(TAG, "onCreateWindow: dialog=$isDialog userGesture=$isUserGesture")
                val temp = WebView(this@MainActivity).apply {
                    webViewClient = object : WebViewClient() {
                        override fun shouldOverrideUrlLoading(v: WebView, request: WebResourceRequest): Boolean {
                            val u = request.url.toString()
                            Log.d(TAG, "popup shouldOverrideUrlLoading: $u")
                            openExternalInOverlay(u)
                            (v.parent as? ViewGroup)?.removeView(v)
                            return true
                        }
                    }
                }
                val transport = temp.WebViewTransport()
                transport.setWebView(temp)
                resultMsg.obj = transport
                resultMsg.sendToTarget()
                return true
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
                // GPS follow is best-effort: a failure here must never crash the app.
                try {
                    flushPendingGps()
                } catch (e: Exception) {
                    Log.e(TAG, "GPS follow failed to start", e)
                }
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

    override fun onBackPressed() {
        if (movieRoot != null) {
            dismissOverlay()
            return
        }
        super.onBackPressed()
    }

    /**
     * Open a non-HamClock page (movie, QR "Open" link, external site) in a
     * full-screen overlay WebView with an upper-right "X" close button that
     * returns to the clock. The system back button also dismisses the overlay.
     */
    private fun openExternalInOverlay(url: String) {
        Log.d(TAG, "openExternalInOverlay: $url (movieRoot!=null=${movieRoot != null})")
        // Do nothing if an overlay is already showing
        if (movieRoot != null) return

        // Build the overlay container
        movieRoot = FrameLayout(this).apply {
            layoutParams = FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT
            )
        }

        // X close button in the upper-right corner
        val closeBtn = Button(this@MainActivity).apply {
            text = "X"
            setTextColor(android.graphics.Color.WHITE)
            background = android.graphics.drawable.ColorDrawable(android.graphics.Color.TRANSPARENT)
            setPadding(14, 14, 14, 14)
            gravity = Gravity.CENTER
            setOnClickListener { dismissOverlay() }
        }
        movieRoot?.addView(closeBtn, FrameLayout.LayoutParams(
            FrameLayout.LayoutParams.WRAP_CONTENT,
            FrameLayout.LayoutParams.WRAP_CONTENT
        ).apply {
            gravity = Gravity.RIGHT or Gravity.TOP
            setMargins(16, 16, 16, 0)
        })

        // The overlay WebView loads the external URL
        movieView = WebView(this).apply {
            settings.javaScriptEnabled = true
            settings.domStorageEnabled = true
            settings.mediaPlaybackRequiresUserGesture = false
            settings.setSupportMultipleWindows(true)
            settings.loadWithOverviewMode = true
            settings.useWideViewPort = true
            webViewClient = object : WebViewClient() {
                override fun shouldOverrideUrlLoading(
                    view: WebView, request: WebResourceRequest
                ): Boolean {
                    // Inside the overlay, same-host pages (the clock) close it
                    val u = request.url.toString()
                    return if (isLocalHamClockUrl(u)) {
                        dismissOverlay()
                        true
                    } else {
                        view.loadUrl(u)
                        true
                    }
                }
            }
            webChromeClient = object : WebChromeClient() {
                override fun onCreateWindow(
                    view: WebView, isDialog: Boolean, isUserGesture: Boolean, resultMsg: Message
                ): Boolean {
                    val temp = WebView(this@MainActivity).apply {
                        webViewClient = object : WebViewClient() {
                            override fun shouldOverrideUrlLoading(v: WebView, request: WebResourceRequest): Boolean {
                                val u = request.url.toString()
                                if (isLocalHamClockUrl(u)) {
                                    dismissOverlay()
                                } else {
                                    openExternalInOverlay(u)
                                }
                                (v.parent as? ViewGroup)?.removeView(v)
                                return true
                            }
                        }
                    }
                    val transport = temp.WebViewTransport()
                    transport.setWebView(temp)
                    resultMsg.obj = transport
                    resultMsg.sendToTarget()
                    return true
                }
            }
        }
        movieRoot?.addView(movieView, FrameLayout.LayoutParams(
            FrameLayout.LayoutParams.MATCH_PARENT,
            FrameLayout.LayoutParams.MATCH_PARENT
        ))
        // Attach the overlay to the activity's content view so it actually appears on screen
        (window.decorView.findViewById<ViewGroup>(android.R.id.content)!!).addView(movieRoot!!)
        movieView?.loadUrl(url)
    }

    /** Dismiss the overlay and return to the clock. */
    private fun dismissOverlay() {
        movieRoot?.let {
            (window.decorView.findViewById<ViewGroup>(android.R.id.content)!!).removeView(it)
            movieRoot = null
            movieView = null
        }
    }

    /** True if `url` is served by the local HamClock server (keep in the main WebView). */
    private fun isLocalHamClockUrl(url: String): Boolean {
        return url.startsWith("http://127.0.0.1:$REST_PORT/") ||
               url.startsWith("http://127.0.0.1:$RW_PORT/")    ||
               url.startsWith("http://127.0.0.1:8082/")
    }

    /**
     * Request location permissions.  Uses the greedy REQUEST_LOCATION_SOCKET
     * policy so follow works on Android 6+/7/8/9.  This is a no-op on API 23+
     * where the runtime permission dialog is shown.
     */
    private fun requestLocationPermissionIfNeeded() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            val perm = ActivityCompat.checkSelfPermission(
                this, Manifest.permission.ACCESS_FINE_LOCATION
            )
            if (perm != PackageManager.PERMISSION_GRANTED) {
                requestPermissions(
                    arrayOf(Manifest.permission.ACCESS_FINE_LOCATION,
                            Manifest.permission.ACCESS_COARSE_LOCATION),
                    REQ_LOC
                )
            }
        }
    }

    /**
     * Persist the last pushed location so a restart does not cause a duplicate
     * push on startup.
     */
    private fun loadLastKnownPush() {
        val f = File(filesDir, "lastgps.pb")
        if (f.exists()) {
            try {
                val lines = f.readLines()
                if (lines.size >= 2) {
                    lastPushedLat = lines[0].toDoubleOrNull()
                    lastPushedLng = lines[1].toDoubleOrNull()
                    lastPushMs = lines[2].toLongOrNull() ?: 0L
                }
            } catch (e: Exception) {
                Log.w(TAG, "loadLastKnownPush failed", e)
            }
        }
    }

    /**
     * On first location update, if the user had a previously-pushed DE we
     * confirm before overwriting it.
     */
    private fun flushPendingGps() {
        val lm = getSystemService(Context.LOCATION_SERVICE) as? LocationManager
        if (lm == null) {
            Log.w(TAG, "no LocationManager")
            return
        }
        locationManager = lm

        // Restart the listener in case the activity was recreated
        gpsListener = object : LocationListener {
            override fun onLocationChanged(loc: Location) {
                Log.d(TAG, "GPS: lat=${loc.latitude} lng=${loc.longitude} acc=${loc.accuracy}")
                pendingLat = loc.latitude
                pendingLng = loc.longitude
                // schedule the push on the UI thread (to avoid blocking GPS thread)
                uiPost { postGpsPush() }
            }
            override fun onStatusChanged(provider: String?, status: Int, extras: Bundle?) {}
        }

        // Try to get last known location first
        try {
            val loc = locationManager!!.getLastKnownLocation(LocationManager.GPS_PROVIDER)
            if (loc != null) {
                Log.d(TAG, "last known GPS: ${loc.latitude},${loc.longitude}")
                pendingLat = loc.latitude
                pendingLng = loc.longitude
                postGpsPush()
            }
        } catch (e: Exception) {
            Log.w(TAG, "getLastKnownLocation failed", e)
        }

        // Request continuous GPS updates
        try {
            locationManager!!.requestLocationUpdates(
                LocationManager.GPS_PROVIDER, MIN_TIME_MS, MIN_DIST_M, gpsListener!!,
                Looper.getMainLooper()
            )
            Log.i(TAG, "GPS follow started (GPS_PROVIDER)")
        } catch (e: SecurityException) {
            Log.e(TAG, "GPS permission not granted", e)
        }
    }

    private fun postGpsPush() {
        val lat = pendingLat
        val lng = pendingLng
        if (lat == null || lng == null) return

        // commit any pending update
        if (lastPushedLat == lat && lastPushedLng == lng && System.currentTimeMillis() - lastPushMs < MIN_TIME_MS) {
            return // nothing new
        }

        if (lastPushedLat != null && lastPushedLng != null) {
            val dLat = (lat - lastPushedLat!!).absoluteValue
            val dLng = (lng - lastPushedLng!!).absoluteValue
            if (dLat < 0.0001 && dLng < 0.0001) return // too small to matter
        }

        // send the update; the native server side may prompt if this overwrites
        // user-set DE values.  15 s between waves.
        thread(name = "hamclock-gps-push") {
            try {
                val params = String.format("grid=AB12&lat=%.5f&lng=%.5f&call=AA0XYZ", lat, lng)
                val u = URL(SET_NEWDE).openConnection() as HttpURLConnection
                u.requestMethod = "POST"
                u.setRequestProperty("Content-Type", "application/x-www-form-urlencoded")
                u.setRequestProperty("Content-Length", params.toByteArray().size.toString())
                u.outputStream.use { it.write(params.toByteArray()) }
                u.inputStream.use { Log.i(TAG, "set_newde response: ${it.bufferedReader().readText()}") }
                u.disconnect()
            } catch (e: Exception) {
                Log.e(TAG, "set_newde POST failed", e)
            }
        }

        lastPushedLat = lat
        lastPushedLng = lng
        lastPushMs = System.currentTimeMillis()

        // remember in file so restart does not do a duplicate
        try {
            val f = File(filesDir, "lastgps.pb")
            f.writeText("${lat}\n${lng}\n${lastPushMs}\n")
        } catch (e: Exception) {
            Log.w(TAG, "save lastgps failed", e)
        }
    }

    /**
     * Helper to run a runnable on the UI thread.
     */
    private fun uiPost(r: () -> Unit) {
        runOnUiThread { r() }
    }

    /**
    
     *
     * The binary is packaged as a native library (libhamclock.so), so the package
     * manager extracts it to nativeLibraryDir at install time. That directory is
     * executable (unlike filesDir on Android 10+), so we can exec it directly.
     * No per-ABI selection is needed here â€” the OS already placed the right ABI.
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
