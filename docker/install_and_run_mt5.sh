#!/bin/bash

set -e
#LOGFILE="/root/.wine/drive_c/fx/install.log"

# Commencer log
#exec > >(tee -a "$LOGFILE") 2>&1


# MetaTrader & WebView2 download URLs
URL_MT5="https://download.mql5.com/cdn/web/metaquotes.software.corp/mt5/mt5setup.exe"

# Set up Wine environment
echo "[*] Configuring Wine..."
winecfg -v=win10
wineboot -i




# Install MetaTrader 5
echo "[*] Installing MetaTrader 5..."
cd /root/.wine/drive_c/fx/
wget -O mt5setup.exe "$URL_MT5" && wine mt5setup.exe /auto && wineserver -w
sleep 10
# Vérification que l'installation a vraiment eu lieu
if [ ! -f "/root/.wine/drive_c/Program Files/MetaTrader 5/terminal64.exe" ]; then
    echo "MT5 installation failed (file not found)"
    #exit 1
fi

# Clean up installers
#rm -f MicrosoftEdgeWebview2Setup.exe mt5setup.exe

echo "[✔] MT5 + WebView2 installed. You can now log in via VNC and use the Market tab."
ls