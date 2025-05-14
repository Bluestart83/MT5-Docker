#!/bin/bash

winecfg -v=win10
wineboot -i

cd /root/.wine/drive_c/fx/ && wget "https://download.mql5.com/cdn/web/metaquotes.software.corp/mt5/mt5setup.exe"
#cd /root/.wine/drive_c/fx/ && wget -O mt5setup.exe "https://download.mql5.com/cdn/web/14111/mt5/vantageinternational5setup.exe"
/usr/bin/wine64 /root/.wine/drive_c/fx/mt5setup.exe /auto

