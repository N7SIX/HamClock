package my.hamradio.n7six.hamclock

import android.Manifest
import android.annotation.SuppressLint
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Color
import android.location.Location
import android.location.LocationListener
import android.location.LocationManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Looper
import android.os.Message
import android.util.Log
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.view.WindowInsets
import android.view.WindowManager
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Button
import android.widget.FrameLayout
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
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

        // Injected into live.html after load. Two jobs:
        //  1) Forces #hamclock-cvs to cover the entire viewport. live.html's own
        //     initCanvas() "shrinks to fit preserving aspect" and centers the
        //     canvas, which leaves letterbox rows on tablets whose aspect ratio
        //     differs from the clock's 5:3 (1600x960). The stylesheet's
        //     !important beats the page's inline width/height/position no matter
        //     when the first frame arrives.
        //  2) Overrides getAppCoords() so pointer events are mapped against the
        //     STRETCHED canvas rect with independent X/Y scales (native app
        //     coords are always 800x480) -- otherwise taps drift and the strip
        //     below the clock maps to out-of-range coords.
        private val FILL_JS = """
            (function fillN7six() {
              try {
                try {
                  var vp = document.querySelector('meta[name=viewport]');
                  if (!vp) {
                    vp = document.createElement('meta');
                    vp.name = 'viewport';
                    (document.head || document.documentElement).appendChild(vp);
                  }
                  vp.content = 'width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no,viewport-fit=cover';
                } catch (e0) { }
                var el0 = document.getElementById('hamclock-cvs');
                if (!el0) { setTimeout(fillN7six, 300); return; }
                if (!document.getElementById('n7six-fill')) {
                  var st = document.createElement('style');
                  st.id = 'n7six-fill';
                  st.textContent =
                    'html,body{margin:0!important;padding:0!important;width:100%!important;height:100%!important;overflow:hidden!important;background:#000!important;}' +
                    '#hamclock-cvs{position:fixed!important;top:0!important;left:0!important;right:0!important;bottom:0!important;' +
                    'margin:0!important;padding:0!important;width:100vw!important;height:100vh!important;object-fit:fill!important;background:#000!important;}';
                  (document.head || document.documentElement).appendChild(st);
                }
                window.getAppCoords = function (event) {
                  var el = document.getElementById('hamclock-cvs');
                  if (!el) return undefined;
                  var r = el.getBoundingClientRect();
                  if (!r.width || !r.height) return undefined;
                  return { x: Math.round((event.clientX - r.left) * 800 / r.width),
                           y: Math.round((event.clientY - r.top) * 480 / r.height) };
                };
              } catch (e) { }
            })();
        """
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
        // Edge-to-edge must be requested before the first layout pass so the
        // content view is never measured with system-bar insets (the rows
        // visible at the top/bottom of the tablet).
        // (WindowCompat is API 20+; only touch it on 21+ via the isolated
        // ModernKiosk helper so 4.x Dalvik never verifies those references.
        // 4.x relies on the fullscreen flags in applyKioskWindow() instead.)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
            try { ModernKioskPreLayout.apply(window) } catch (_: Exception) { }
        }
        val root = FrameLayout(this)
        root.setFitsSystemWindows(false)
        val web = WebView(this)
        web.setFitsSystemWindows(false)
        // The WebView itself must never be inset by system bars: consume the
        // insets at the parent so legacy fitSystemWindows padding never leaves
        // the top/bottom rows you see on the tablet.
        // (setOnApplyWindowInsetsListener is API 20+; 4.x uses
        // fitSystemWindows padding, which we already disabled above, so skip.
        // The listener is installed via a separate helper object so Dalvik on
        // 4.x never verifies WindowInsets references inside onCreate.)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.KITKAT_WATCH) {
            LegacyInsets.install(root)
        }
        root.addView(
            web,
            FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT
            )
        )
        setContentView(root)

        root.keepScreenOn = true
        web.keepScreenOn = true

        // ---- Kiosk display window: edge-to-edge + always-on screen ----
        applyKioskWindow()

        web.settings.javaScriptEnabled = true
        web.settings.domStorageEnabled = true
        // mediaPlaybackRequiresUserGesture is API 17+: safe (minSdk is 17), but
        // guard anyway so a backport/older stub can never NoSuchMethodError.
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.JELLY_BEAN_MR1) {
            try { web.settings.mediaPlaybackRequiresUserGesture = false } catch (_: Exception) { }
        }
        // The live web UI receives "open <url>" over its websocket (staged by the
        // native side when the user taps a link such as "Open Guide") and calls
        // window.open() from that async message handler -- not a user-gesture
        // context, so WebView popup gating would silently block it by default.
        web.settings.javaScriptCanOpenWindowsAutomatically = true
        web.settings.setSupportMultipleWindows(true)
        // loadWithOverviewMode=false: overview mode zooms out to a wide
        // viewport so 100vw no longer equals the LCD width (letterbox rows).
        // The injected viewport meta + 100vw/100vh CSS then maps 1:1 to glass.
        web.settings.loadWithOverviewMode = false
        web.settings.useWideViewPort = true
        web.settings.setSupportZoom(false)
        web.settings.builtInZoomControls = false
        web.settings.displayZoomControls = false
        web.isVerticalScrollBarEnabled = false
        web.isHorizontalScrollBarEnabled = false
        web.overScrollMode = View.OVER_SCROLL_NEVER
        web.scrollBarStyle = View.SCROLLBARS_INSIDE_OVERLAY
        // Keep the clock UI itself inside this WebView; route ALL other pages
        // (QR "Open Movie" links, window.open popups, link taps) to the
        // overlay viewer with its X close button instead.
        // Compat split: API 21+ gets the full WebResourceRequest overrides,
        // API 17-20 gets only the legacy String overloads (Dalvik verifies
        // every override signature at class-load, so a single client class
        // mixing both would fail verification on 4.x).
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
            web.webViewClient = ModernMainClient()
        } else {
            web.webViewClient = LegacyMainClient()
        }

        // Intercept window.open() popups (e.g. "Open Movie" links) and route
        // them to the overlay viewer instead of being blocked.
        web.webChromeClient = object : WebChromeClient() {
            override fun onProgressChanged(view: WebView, newProgress: Int) {
                super.onProgressChanged(view, newProgress)
                // live.html sizes its canvas on the first frame, which can
                // arrive after onPageFinished -- re-assert fill at 100%.
                if (newProgress == 100) {
                    try {
                        val u = view.url ?: return
                        if (isLocalHamClockUrl(u)) runFillJs(view)
                    } catch (_: Exception) { }
                }
            }

            override fun onCreateWindow(
                view: WebView, isDialog: Boolean, isUserGesture: Boolean, resultMsg: Message
            ): Boolean {
                Log.d(TAG, "onCreateWindow: dialog=$isDialog userGesture=$isUserGesture")
                val temp = WebView(this@MainActivity).apply {
                    // Same verifier split as the main client: only hand 4.x the
                    // legacy String overload.
                    webViewClient = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
                        ModernPopupClient()
                    } else {
                        LegacyPopupClient()
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

        // WebViews cannot render PDFs (no built-in plugin), so the User Guide and
        // other .pdf links would come up as a blank overlay. Hand them to the
        // system browser / PDF viewer via ACTION_VIEW instead -- the same
        // destination a scanned QR code reaches. Fall back to the overlay if no
        // activity on this device claims the URL.
        if (url.substringBefore('?').endsWith(".pdf", ignoreCase = true)) {
            try {
                startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)))
                return
            } catch (e: Exception) {
                Log.w(TAG, "no PDF viewer for $url, falling back to overlay: $e")
            }
        }

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
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.JELLY_BEAN_MR1) {
                try { settings.mediaPlaybackRequiresUserGesture = false } catch (_: Exception) { }
            }
            settings.setSupportMultipleWindows(true)
            settings.loadWithOverviewMode = true
            settings.useWideViewPort = true
            // Same verifier split as the main client.
            webViewClient = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
                ModernOverlayClient()
            } else {
                LegacyOverlayClient()
            }
            webChromeClient = object : WebChromeClient() {
                override fun onCreateWindow(
                    view: WebView, isDialog: Boolean, isUserGesture: Boolean, resultMsg: Message
                ): Boolean {
                    val temp = WebView(this@MainActivity).apply {
                        webViewClient = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
                            ModernOverlayPopupClient()
                        } else {
                            LegacyOverlayPopupClient()
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

    // ---- Verifier-safe WebView clients (Dalvik on API 17-19 rejects any class
    // whose method signatures reference WebResourceRequest, so modern and
    // legacy variants must live in separate inner classes and only the right
    // one is ever instantiated behind an SDK_INT guard) ----

    /** API 21+: full-featured main-clock client. */
    private inner class ModernMainClient : WebViewClient() {
        override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
            return handleMainUrl(view, request.url.toString())
        }

        override fun onPageFinished(view: WebView, url: String) {
            super.onPageFinished(view, url)
            if (!serverReady) serverReady = true
            if (isLocalHamClockUrl(url)) runFillJs(view)
        }

        override fun shouldInterceptRequest(view: WebView, request: WebResourceRequest): WebResourceResponse? {
            return proxyLocalRequest(request.url.toString())
        }

        override fun onReceivedError(view: WebView, request: WebResourceRequest, error: android.webkit.WebResourceError) {
            val url = request.url?.toString() ?: ""
            if (isLocalHamClockUrl(url)) {
                Log.i(TAG, "Local server connection lost/restarting ($url), auto-reconnecting...")
                thread {
                    if (waitForServer(30_000)) {
                        runOnUiThread { view.loadUrl(URL_TO_LOAD) }
                    }
                }
            }
        }
    }

    /** API 17-20: legacy String overloads only (no WebResourceRequest refs). */
    private inner class LegacyMainClient : WebViewClient() {
        @Suppress("DEPRECATION")
        override fun shouldOverrideUrlLoading(view: WebView, url: String): Boolean {
            return handleMainUrl(view, url)
        }

        override fun onPageFinished(view: WebView, url: String) {
            super.onPageFinished(view, url)
            if (!serverReady) serverReady = true
            if (isLocalHamClockUrl(url)) runFillJs(view)
        }

        @Suppress("DEPRECATION")
        override fun shouldInterceptRequest(view: WebView, url: String): WebResourceResponse? {
            return proxyLocalRequest(url)
        }

        @Suppress("DEPRECATION")
        override fun onReceivedError(view: WebView, errorCode: Int, description: String?, failingUrl: String?) {
            val url = failingUrl ?: ""
            if (isLocalHamClockUrl(url)) {
                Log.i(TAG, "Legacy Local server connection lost/restarting ($url), auto-reconnecting...")
                thread {
                    if (waitForServer(30_000)) {
                        runOnUiThread { view.loadUrl(URL_TO_LOAD) }
                    }
                }
            }
        }
    }

    /** API 21+: popup client for window.open() from the main WebView. */
    private inner class ModernPopupClient : WebViewClient() {
        override fun shouldOverrideUrlLoading(v: WebView, request: WebResourceRequest): Boolean {
            return handlePopupUrl(v, request.url.toString())
        }
    }

    /** API 17-20: legacy popup client. */
    private inner class LegacyPopupClient : WebViewClient() {
        @Suppress("DEPRECATION")
        override fun shouldOverrideUrlLoading(v: WebView, url: String): Boolean {
            return handlePopupUrl(v, url)
        }
    }

    /** API 21+: overlay client (external pages + clock-dismiss). */
    private inner class ModernOverlayClient : WebViewClient() {
        override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
            return handleOverlayUrl(view, request.url.toString())
        }
    }

    /** API 17-20: legacy overlay client. */
    private inner class LegacyOverlayClient : WebViewClient() {
        @Suppress("DEPRECATION")
        override fun shouldOverrideUrlLoading(view: WebView, url: String): Boolean {
            return handleOverlayUrl(view, url)
        }
    }

    /** API 21+: overlay-popup client. */
    private inner class ModernOverlayPopupClient : WebViewClient() {
        override fun shouldOverrideUrlLoading(v: WebView, request: WebResourceRequest): Boolean {
            val u = request.url.toString()
            if (isLocalHamClockUrl(u)) dismissOverlay() else openExternalInOverlay(u)
            (v.parent as? ViewGroup)?.removeView(v)
            return true
        }
    }

    /** API 17-20: legacy overlay-popup client. */
    private inner class LegacyOverlayPopupClient : WebViewClient() {
        @Suppress("DEPRECATION")
        override fun shouldOverrideUrlLoading(v: WebView, url: String): Boolean {
            if (isLocalHamClockUrl(url)) dismissOverlay() else openExternalInOverlay(url)
            (v.parent as? ViewGroup)?.removeView(v)
            return true
        }
    }

    /** True if `url` is served by the local HamClock server (keep in the main WebView). */
    private fun isLocalHamClockUrl(url: String): Boolean {
        return url.startsWith("http://127.0.0.1:$REST_PORT/") ||
               url.startsWith("http://127.0.0.1:$RW_PORT/")    ||
               url.startsWith("http://127.0.0.1:8082/")
    }

    /**
     * Shared link router used by BOTH main-WebView shouldOverrideUrlLoading
     * overloads: the clock stays in place, everything else goes to the overlay
     * viewer (with its X close button) so the user can get back to the clock.
     */
    private fun handleMainUrl(view: WebView, u: String): Boolean {
        Log.d(TAG, "shouldOverrideUrlLoading: $u (local=${isLocalHamClockUrl(u)})")
        return if (isLocalHamClockUrl(u)) {
            false
        } else {
            openExternalInOverlay(u)
            true
        }
    }

    /** Shared popup router used by BOTH onCreateWindow temp-WebView overloads. */
    private fun handlePopupUrl(v: WebView, u: String): Boolean {
        Log.d(TAG, "popup shouldOverrideUrlLoading: $u")
        openExternalInOverlay(u)
        (v.parent as? ViewGroup)?.removeView(v)
        return true
    }

    /**
     * Shared overlay router: same-host pages (the clock) dismiss the overlay,
     * everything else stays inside it (4.x-safe view.loadUrl, no JS bridge).
     */
    private fun handleOverlayUrl(view: WebView, u: String): Boolean {
        return if (isLocalHamClockUrl(u)) {
            dismissOverlay()
            true
        } else {
            @Suppress("DEPRECATION") view.loadUrl(u)
            true
        }
    }

    /** Shared localhost proxy used by BOTH shouldInterceptRequest overloads. */
    private fun proxyLocalRequest(u: String): WebResourceResponse? {
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

    /**
     * Run FILL_JS on every WebView. evaluateJavascript() is API 19+; on 17/18
     * fall back to loadUrl("javascript:...") (runs async, no result needed).
     */
    private fun runFillJs(view: WebView) {
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.KITKAT) {
                view.evaluateJavascript(FILL_JS, null)
            } else {
                @Suppress("DEPRECATION")
                view.loadUrl("javascript:" + Uri.encode(FILL_JS))
            }
        } catch (_: Exception) { }
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

        // Request continuous GPS updates.
        // The 5-arg Looper overload is API 24+; on 17-23 use the 4-arg variant
        // (delivers on the calling thread -- we post to UI via uiPost anyway).
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N) {
                locationManager!!.requestLocationUpdates(
                    LocationManager.GPS_PROVIDER, MIN_TIME_MS, MIN_DIST_M, gpsListener!!,
                    Looper.getMainLooper()
                )
            } else {
                @Suppress("DEPRECATION")
                locationManager!!.requestLocationUpdates(
                    LocationManager.GPS_PROVIDER, MIN_TIME_MS, MIN_DIST_M, gpsListener!!
                )
            }
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
        val src = File(applicationInfo.nativeLibraryDir, "libhamclock.so")
        if (!src.exists()) {
            throw IllegalStateException(
                "native server binary missing: ${src.absolutePath} " +
                    "(nativeLibraryDir=${applicationInfo.nativeLibraryDir})"
            )
        }
        val dst = File(filesDir, "hamclock")
        try {
            src.copyTo(dst, overwrite = true)
            dst.setExecutable(true, false)
        } catch (e: Exception) {
            Log.w(TAG, "Failed to copy native binary to filesDir: $e", e)
        }
        return if (dst.exists()) dst else src
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
            } catch (e: Exception) {
                Log.d(TAG, "waitForServer: port $RW_PORT not yet open (${e.message})")
            }
            Thread.sleep(300)
        }
        return false
    }

    /**
     * Kiosk display window: full-bleed edge-to-edge + always-on screen.
     * - Draws behind status/nav bars and hides them (immersive sticky; a
     *   swipe peeks them transiently) so HamClock covers the entire LCD.
     * - FLAG_KEEP_SCREEN_ON stops dim / screensaver / LCD sleep while this
     *   activity is visible (no permission needed; auto-cleared on pause).
     * - showWhenLocked/turnScreenOn keeps the clock up over the lockscreen.
     * Must be re-applied in onResume/onWindowFocusChanged because the system
     * clears immersive flags whenever another window takes focus.
     */
    private fun applyKioskWindow() {
        // Modern edge-to-edge touches API 30+ classes; on 4.x the mere
        // reference can fail verification, so only call it on 21+ (the helper
        // object below keeps those references out of MainActivity's own
        // verified method bodies).
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
            ModernKiosk.apply(window)
        }
        // Ignore screen dimming, screensaver, and LCD sleep while HamClock
        // is showing: stops the system idle timer for this window.
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        // Show over the lockscreen + wake the screen if it was off.
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O_MR1) {
            try {
                setShowWhenLocked(true)
                setTurnScreenOn(true)
            } catch (_: Exception) { }
        } else {
            @Suppress("DEPRECATION")
            window.addFlags(
                WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED or
                WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON
            )
        }
        // Immersive sticky exists since API 19; 17/18 fall back to plain
        // fullscreen flags (constants are inlined so no verification risk).
        @Suppress("DEPRECATION")
        try {
            var flags = (
                View.SYSTEM_UI_FLAG_FULLSCREEN or
                View.SYSTEM_UI_FLAG_HIDE_NAVIGATION or
                View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN or
                View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION or
                View.SYSTEM_UI_FLAG_LAYOUT_STABLE
            )
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.KITKAT) {
                flags = flags or View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
            }
            window.decorView.systemUiVisibility = flags
        } catch (_: Exception) { }
    }

    /**
     * API 21+ pre-layout edge-to-edge request (isolated so onCreate itself
     * carries no WindowCompat references for 4.x Dalvik to verify).
     */
    private object ModernKioskPreLayout {
        fun apply(window: android.view.Window) {
            try { WindowCompat.setDecorFitsSystemWindows(window, false) } catch (_: Exception) { }
        }
    }

    /**
     * API 21+ only: edge-to-edge + bar colors + InsetsController. Lives in its
     * own nested object (never called on 4.x) so Dalvik on API 17-19 never
     * verifies these API 21-30 class/method references.
     */
    private object ModernKiosk {
        fun apply(window: android.view.Window) {
            try {
                WindowCompat.setDecorFitsSystemWindows(window, false)
            } catch (_: Exception) { }
            try {
                window.statusBarColor = Color.BLACK
                window.navigationBarColor = Color.BLACK
            } catch (_: Exception) { }
            // Draw into the display-cutout (notch/camera) area on API 28+.
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
                try {
                    window.attributes = window.attributes.apply {
                        layoutInDisplayCutoutMode =
                            WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_SHORT_EDGES
                    }
                } catch (_: Exception) { }
            }
            // Hide status + navigation bars (compat wrapper handles API 21-29).
            try {
                WindowInsetsControllerCompat(window, window.decorView).apply {
                    hide(WindowInsetsCompat.Type.systemBars())
                    systemBarsBehavior =
                        WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
                }
            } catch (_: Exception) { }
        }
    }

    override fun onResume() {
        super.onResume()
        applyKioskWindow()
    }

    /**
     * Re-enter immersive mode whenever we regain focus (returning from the
     * system browser or the overlay viewer, dismissing a dialog, ...): the
     * system may un-hide the bars while another window has focus.
     */
    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        if (hasFocus) {
            applyKioskWindow()
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        try { serverProc?.destroy() } catch (e: Exception) { }
    }

    /**
     * API 20+ only: consumes window insets so legacy fitSystemWindows padding
     * never leaves top/bottom rows. Lives in its own nested object so Dalvik on
     * API 17-19 never verifies WindowInsets references (verifier checks the
     * referencing method's whole class at load; isolating keeps MainActivity
     * itself clean). Only called behind an SDK_INT guard in onCreate.
     */
    private object LegacyInsets {
        fun install(root: FrameLayout) {
            try {
                root.setOnApplyWindowInsetsListener { v, insets ->
                    v.setPadding(0, 0, 0, 0)
                    WindowInsets.CONSUMED
                }
            } catch (_: Exception) { }
        }
    }
}
