# HamClock Quick Guide

Project web site: [http://www.clearskyinstitute.com/ham/HamClock](http://www.clearskyinstitute.com/ham/HamClock)

HamClock is a kiosk-style application that provides real-time space weather, radio propagation models, operating events, and other information particularly useful to the radio amateur.

## Quick Install Guide (UNIX/Linux)

1. **Clone the repository:**
   ```sh
   git clone https://github.com/N7SIX/HamClock.git
   cd HamClock
   ```
2. **Build for your desired size:**
   ```sh
   make           # Shows available size/style options
   make <size>    # Example: make 1600x960
   sudo make install
   ```

## Quick Install Guide (ESP8266 Huzzah)

1. Install and run the Arduino IDE.
2. Configure as per the "ESP8266 Notes" tab at the project web page.
3. Open `ESPHamClock.ino` in the IDE.
4. Compile and upload:
   - Sketch → Compile
   - Sketch → Upload

## Quick Install Guide (Raspberry Pi)

1. **Update your system:**
   ```sh
   sudo apt update && sudo apt upgrade -y
   sudo apt install git build-essential libx11-dev libxft-dev libxext-dev -y
   ```
2. **Clone the HamClock repository:**
   ```sh
   git clone https://github.com/N7SIX/HamClock.git
   cd HamClock
   ```
3. **Build HamClock for your desired display size:**
   ```sh
   make           # Shows available size/style options
   make 1600x960  # Example for 1600x960 display
   ```
4. **Run HamClock:**
   ```sh
   ./hamclock-1600x960
   ```
5. *(Optional)* **Install HamClock system-wide:**
   ```sh
   sudo make install
   ```

---
For more details, visit the [HamClock project page](http://www.clearskyinstitute.com/ham/HamClock).
