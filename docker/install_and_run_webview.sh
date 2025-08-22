#!/bin/bash

set -e
#LOGFILE="/root/.wine/drive_c/fx/install.log"

# Commencer log
#exec > >(tee -a "$LOGFILE") 2>&1


# MetaTrader & WebView2 download URLs

#URL_WEBVIEW="https://msedge.sf.dl.delivery.mp.microsoft.com/filestreamingservice/files/c1336fd6-a2eb-4669-9b03-949fc70ace0e/MicrosoftEdgeWebview2Setup.exe"
# WebView2 v109 ✅ Direct Archive.org Link (v109.0.1518.78 x64) the last one working with Docker linux
URL_WEBVIEW="https://archive.org/download/microsoft-edge-web-view-2-runtime-installer-v109.0.1518.78/MicrosoftEdgeWebView2RuntimeInstallerX64.exe"


# Set up Wine environment
echo "[*] Configuring Wine..."
winecfg -v=win10
wineboot -i

mkdir -p /root/.wine/drive_c/fx/
cd /root/.wine/drive_c/fx/


# Optional: winetricks if needed later
winetricks -q corefonts
#winetricks -q vcrun2015
#winetricks -q dotnet48 msxml6
#export WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS="--disable-gpu --no-sandbox" 
#/usr/bin/wine64 reg add "HKCU\Environment" /v WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS /t REG_SZ /d "--disable-gpu --no-sandbox"

# Install WebView2 (required for MQL5 Market tab)
#echo "[*] Installing WebView2 Runtime..."
#wget -O MicrosoftEdgeWebview2Setup.exe "$URL_WEBVIEW"
wine MicrosoftEdgeWebview2Setup.exe /silent /install #&& wineserver -w
echo "Install FINISHED! WAIT 10s"
sleep 10
# Verification que l'installation a vraiment eu lieu
#if [ ! -d /root/.wine/drive_c/Program\ Files\ \(x86\)/Microsoft/EdgeWebView/ ]; then
#    echo "WebView2 installation failed file not found"
#    exit 1n
#fi

#rm -f /root/.wine/drive_c/fx/MicrosoftEdgeWebview2Setup.exe || true
