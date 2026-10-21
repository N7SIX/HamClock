/*
 * hc_home.h - portable home-directory lookup.
 *
 * HamClock needs the user's home directory to find its config/eeprom files
 * and to expand a leading "~" in file names.  The variable that holds it
 * differs by platform:
 *
 *   - Unix, Linux, macOS, Android (Termux): HOME
 *   - Windows: no HOME by default, so fall back to USERPROFILE and then
 *     to HOMEDRIVE+HOMEPATH.
 *
 * The returned string is heap allocated and must be free()d by the caller.
 * NULL is returned when no home directory can be determined, so callers must
 * check the result rather than assuming a usable pointer.
 */

#ifndef _HC_HOME_H
#define _HC_HOME_H

#include <stdlib.h>
#include <string.h>

static inline char *hc_get_home(void)
{
    const char *home = getenv("HOME");

#ifdef _WIN32

    if (!home || !*home) {
        home = getenv("USERPROFILE");
    }
    if (!home || !*home) {
        const char *drive = getenv("HOMEDRIVE");
        const char *path  = getenv("HOMEPATH");
        if (drive && *drive) {
            size_t dl = strlen(drive);
            size_t pl = path ? strlen(path) : 0;
            char *both = (char *) malloc(dl + pl + 1);
            if (both) {
                memcpy(both, drive, dl);
                if (pl)
                    memcpy(both + dl, path, pl);
                both[dl + pl] = '\0';
                return both;
            }
        }
        return NULL;
    }

#else

    if (!home || !*home)
        return NULL;

#endif

    return strdup(home);
}

#endif /* _HC_HOME_H */