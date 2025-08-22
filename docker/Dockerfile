FROM msjpq/kde-vnc:focal

################ msjpq msjpq/wine-vnc bionic image stuff

ARG MONO_VER="10.0.0"
ARG GECKO_VER="2.47.4"

# WINE Prereq
RUN dpkg --add-architecture i386 && \
    add-apt-repository -y ppa:cybermax-dexter/sdl2-backport


## All Dependencies Satisfied
COPY docker/_root /
ENV PAGE_TITLE=Wine

WORKDIR /root/.wine/drive_c/

################ Wine

# Install dependencies for adding WineHQ repository
RUN apt-get update
RUN apt-get upgrade -y
RUN apt-get install -y sudo supervisor git wget software-properties-common xvfb \
    apt-transport-https ca-certificates gnupg curl

# Remove old wine and winbind
RUN apt-get remove -y wine* winbind

# Add WineHQ repository
RUN dpkg --add-architecture i386 && \
    wget -qO- https://dl.winehq.org/wine-builds/winehq.key | apt-key add - && \
    apt-add-repository 'deb https://dl.winehq.org/wine-builds/ubuntu/ focal main'

# Added
RUN apt install -y libgl1-mesa-dri mesa-utils x11-utils
# Forcer OpenGL logiciel (llvmpipe) partout
ENV LIBGL_ALWAYS_SOFTWARE=1
ENV MESA_LOADER_DRIVER_OVERRIDE=llvmpipe
ENV __GLX_VENDOR_LIBRARY_NAME=mesa

# Forcer WebView2/Chromium en software (pas de GPU)
ENV WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS="--disable-gpu --disable-gpu-compositing --use-angle=swiftshader --use-gl=swiftshader"

# Install latest stable Wine
RUN apt-get update && \
    apt-get install -y --install-recommends winehq-stable && \
    apt-get install -y winbind

# WINE Libs
# When Wine runs and needs Gecko/Mono, it looks in /usr/share/wine/mono and gecko
RUN mkdir -p /usr/share/wine /usr/share/wine/mono /usr/share/wine/gecko
ADD https://dl.winehq.org/wine/wine-mono/${MONO_VER}/wine-mono-${MONO_VER}-x86.msi /usr/share/wine/mono
ADD https://dl.winehq.org/wine/wine-gecko/${GECKO_VER}/wine-gecko-${GECKO_VER}-x86.msi /usr/share/wine/gecko
ADD https://dl.winehq.org/wine/wine-gecko/${GECKO_VER}/wine-gecko-${GECKO_VER}-x86_64.msi /usr/share/wine/gecko


# Wine Tricks
ADD https://raw.githubusercontent.com/Winetricks/winetricks/master/src/winetricks /usr/bin
RUN apt install -y wget zenity && \
    chmod +x /usr/bin/winetricks

ENV WINEPREFIX=/root/.wine
ENV WINEARCH=win64
ENV WINEDLLOVERRIDES="mscoree,mshtml="

# Initialize Wine and wait for it to complete
RUN wine wineboot --init && \
    while pgrep wineserver > /dev/null; do \
        echo "Waiting for wine to initialize..."; \
        sleep 1; \
    done

#RUN wineboot --init && wineserver -w

RUN apt install -y apt-utils bc cabextract

COPY ./docker/install_python.sh /root/.wine/drive_c/
RUN chmod +x /root/.wine/drive_c/install_python.sh && xvfb-run bash install_python.sh

#COPY ./docker/install_and_run_mt5ubuntu.sh /root/.wine/drive_c/fx/
COPY ./docker/*.sh /root/.wine/drive_c/fx/
RUN chmod +x /root/.wine/drive_c/fx/install_and_run_webview.sh
COPY ./docker/install_and_run_mt5.sh /root/.wine/drive_c/fx/
RUN chmod +x /root/.wine/drive_c/fx/install_and_run_mt5.sh

COPY ./docker/supervisord.conf /etc/supervisor/conf.d/supervisord.conf

RUN wine wineboot --init && \
    while pgrep wineserver > /dev/null; do \
        echo "Waiting for wine to initialize..."; \
        sleep 1; \
    done


ADD https://archive.org/download/microsoft-edge-web-view-2-runtime-installer-v109.0.1518.78/MicrosoftEdgeWebView2RuntimeInstallerX64.exe /root/.wine/drive_c/fx/MicrosoftEdgeWebview2Setup.exe
#RUN wineboot --init && wineserver -w && \
#    xvfb-run -a -s "-screen 0 1024x768x24 -ac -nolisten tcp" \
#    bash /root/.wine/drive_c/fx/install_and_run_webview.sh

# Create a wrapper script that maintains Xvfb for multiple commands
RUN echo '#!/bin/bash\n\
export DISPLAY=:99\n\
Xvfb :99 -screen 0 1024x768x24 -ac &\n\
XVFB_PID=$!\n\
sleep 3\n\
\n\
# Run all the commands passed as arguments\n\
while [ $# -gt 0 ]; do\n\
    echo "Running: $1"\n\
    eval "$1"\n\
    shift\n\
done\n\
\n\
# Cleanup\n\
kill $XVFB_PID 2>/dev/null || true\n\
wait $XVFB_PID 2>/dev/null || true' > /opt/wine-with-xvfb.sh && chmod +x /opt/wine-with-xvfb.sh

# Run all Wine operations in a single Xvfb session
RUN /opt/wine-with-xvfb.sh \
    "wine wineboot --init && wineserver -w" \
    "bash /root/.wine/drive_c/fx/install_and_run_webview.sh" \
    "wine wineboot --update" \
    "bash /root/.wine/drive_c/fx/install_and_run_mt5.sh"

#RUN wineboot --init && wineserver -w && xvfb-run bash /root/.wine/drive_c/fx/install_and_run_webview.sh
#RUN wineboot --init && wineserver -w
#RUN wineboot --update

# Initialize Wine and wait for it to complete
#RUN wine wineboot --init && \
#   while pgrep wineserver > /dev/null; do \
#       echo "Waiting for wine to initialize..."; \
#       sleep 1; \
#   done

#RUN wineboot --init && wineserver -w

# # Télécharge l'installateur MSI WebView2 v109 (x64)
# ADD https://catalog.s.download.windowsupdate.com/c/msdownload/update/software/updt/2023/02/microsoftedgestandaloneinstallerx64_402402f6bb4b801ffdd039705423f20dbb347cd6.exe /root/.wine/drive_c/fx/MicrosoftEdgeWebView2RuntimeInstallerX64-109.exe
# RUN apt-get install -y p7zip-full
# # Extraire dans un dossier temporaire
# RUN mkdir -p /tmp/webview2_extract && cd /tmp/webview2_extract && 7z x /root/.wine/drive_c/fx/MicrosoftEdgeWebView2RuntimeInstallerX64-109.exe
# RUN ls /tmp/webview2_extract/
# RUN ls /tmp/webview2_extract/
# # Renommer le fichier extrait
# RUN mv "/tmp/webview2_extract/MicrosoftEdge_X64_109.0.1518.78.exe.{0D50BFEC-CD6A-4F9A-964C-C7416E3ACB10}" "/tmp/webview2_extract/MicrosoftEdge_X64_109.exe"
# # Installation avec xvfb-run
# RUN xvfb-run bash -c "wine /tmp/webview2_extract/MicrosoftEdge_X64_109.exe --msedgewebview --system-level --silent --do-not-launch-msedge --verbose-logging"
# RUN rm -rf /tmp/webview2_extract


#RUN xvfb-run bash /root/.wine/drive_c/fx/install_and_run_mt5.sh

#RUN set -x && \
#    xvfb-run --auto-servernum --server-args="-screen 0 1024x768x24" \
#      bash /root/.wine/drive_c/fx/install_and_run_mt5.sh  || true

RUN touch /root/.wine/.update-timestamp
RUN echo 'disable' > $WINEPREFIX/.update-timestamp


RUN mkdir -p /root/Desktop
COPY ./docker/metatrader5.desktop /root/Desktop/
#RUN gio set -t string /root/Desktop/metatrader5.desktop metadata::xfce-exe-checksum "$(sha256sum /root/Desktop/metatrader5.desktop | awk '{print $1}')"
#RUN gio set -t string /root/Desktop/metatrader5.desktop metadata::xfce-exe-checksum "53f7ef56e40b6f8b1a83b23cc73d973580452cd3b6e0042cfc2b34f065b9bb91"
#RUN /usr/bin/gio set -t string /root/Desktop/metatrader5.desktop metadata::xfce-exe-checksum "53f7ef56e40b6f8b1a83b23cc73d973580452cd3b6e0042cfc2b34f065b9bb91"

#RUN kwriteconfig5 --file kiorc --group "KDE Action Restrictions" --key "shell_access" true


COPY ./docker/*.py /root/.wine/drive_c/fx/

RUN rm -rf /var/lib/apt/lists/*

#RUN winetricks -q corefonts gdiplus vcrun2019 win10

CMD ["/usr/bin/supervisord"]