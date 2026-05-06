# Quick Start: Running HamClock on Ubuntu (WSL2 or Native)

1. **Install dependencies:**
	```bash
	sudo apt update
	sudo apt install -y make g++ libx11-dev
	```

2. **Clone this repository:**
	```bash
	git clone https://github.com/N7SIX/HamClock
	cd HamClock
	```

3. **Build your desired size (examples):**
	- Standard:  
	  `make hamclock-800x480`
	- Full HD:  
	  `make hamclock-1600x960`
	- Ultra-wide:  
	  `make hamclock-2400x1440`

4. **Run HamClock:**
	```bash
	./hamclock-1600x960 -k -e 8080 -w 8081
	```
	- `-k` skips setup wizard
	- `-e` sets REST API port (default 8080)
	- `-w` sets web UI port (default 8081)

5. **(Optional) Make it full screen:**  
	Use your window manager’s maximize/full screen option.

---

# About This Version

This is a desktop-optimized fork of ESPHamClock by Clear Skys Institute, adapted for Linux and WSL2.
- **Original project:** https://clearskyinstitute.com/ham/HamClock/
- **This fork:** Focuses on running HamClock as a full-featured desktop or kiosk app, with REST API and web UI.
- **Supports:** Multiple screen sizes, REST API for integration, and easy use on laptops/desktops.

# ESPHamClock
This is a "fork" (not in the literal `git` sense) of the great ESPHamClock by Clear Skys Institute.  They optimzed their code for the ESP8266, I'm optimizing for use on a computer instead.

The `upstream` branch is a straight copy of https://clearskyinstitute.com/ham/HamClock/ESPHamClock.tgz (first commit was v2.69, build on 2021-10-16, committed here on 2021-11-01.)  Since the original ESPHamClock isn't in GitHub, I'll occasionally pull down the original source code and commit it to `upstream` whenever I want to merge upstream changes, but I don't guarantee I'll get every version here.  For the original, please go to the original source: https://clearskyinstitute.com/ham/HamClock/

See `README` in this directory for the original ESPHamClock README.

# HamClock
The `main` branch is where I'll be doing my work.
