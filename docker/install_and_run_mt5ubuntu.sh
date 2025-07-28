#!/bin/bash

# MetaTrader download url
URL_MT5="https://download.mql5.com/cdn/web/metaquotes.software.corp/mt5/mt5setup.exe"
# WebView2 Runtime download url
URL_WEBVIEW="https://msedge.sf.dl.delivery.mp.microsoft.com/filestreamingservice/files/c1336fd6-a2eb-4669-9b03-949fc70ace0e/MicrosoftEdgeWebview2Setup.exe"


winecfg -v=win10
wineboot -i

winetricks -q vcrun2015 corefonts
winetricks -q webview2
#cd /root/.wine/drive_c/fx/ && wget -O MicrosoftEdgeWebview2Setup.exe $URL_WEBVIEW
#/usr/bin/wine64 /root/.wine/drive_c/fx/MicrosoftEdgeWebview2Setup.exe /silent /install

cd /root/.wine/drive_c/fx/ && wget -O mt5setup.exe $URL_MT5
/usr/bin/wine64 /root/.wine/drive_c/fx/mt5setup.exe /auto

#rm -f /root/.wine/drive_c/fx/MicrosoftEdgeWebview2Setup.exe || true
rm -f /root/.wine/drive_c/fx/mt5setup.exe