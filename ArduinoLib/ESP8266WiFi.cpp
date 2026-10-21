// Copyright 2026 Sean, N7SIX
/* simple network interface functions for unix.
 */

#ifdef _WIN32

/* Windows stub: WiFi scanning/status uses Linux/macOS-specific APIs
 * (getifaddrs, popen, wireless ioctls). Provide minimal stubs that
 * allow HamClock to compile and run in web-only mode. Network status
 * is assumed connected; detailed interface info is not available. */

#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <time.h>
#include <unistd.h>

#include "ESP8266WiFi.h"

class WiFi WiFi;
