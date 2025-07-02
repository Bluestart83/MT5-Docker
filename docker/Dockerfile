FROM msjpq/kde-vnc:focal

ARG MONO_VER="4.9.4"
ARG GECKO_VER="2.47.1"

RUN mkdir /_install


# WINE Prereq
ADD https://dl.winehq.org/wine-builds/winehq.key /_install
RUN dpkg --add-architecture i386 && \
    add-apt-repository -y ppa:cybermax-dexter/sdl2-backport && \
    apt-key add /_install/winehq.key && \
    apt-add-repository 'deb https://dl.winehq.org/wine-builds/ubuntu/ focal main' && \
    apt update


# WINE HQ
#RUN apt install -y winehq-devel



## All Dependencies Satisfied
COPY docker/_root /
ENV PAGE_TITLE=Wine




WORKDIR /root/.wine/drive_c/


################

# Install dependencies for adding WineHQ repository
RUN apt-get update && apt-get install -y sudo supervisor git wget software-properties-common xvfb \
    apt-transport-https ca-certificates gnupg curl

# Remove old wine and winbind
RUN apt-get remove -y wine* winbind

# Add WineHQ repository
RUN dpkg --add-architecture i386 && \
    wget -qO- https://dl.winehq.org/wine-builds/winehq.key | apt-key add - && \
    apt-add-repository 'deb https://dl.winehq.org/wine-builds/ubuntu/ focal main'

# Install latest stable Wine
RUN apt-get update && \
    apt-get install -y --install-recommends winehq-stable && \
    apt-get install -y winbind && \
    rm -rf /var/lib/apt/lists/*


# WINE Libs
RUN mkdir /usr/share/wine /usr/share/wine/mono /usr/share/wine/gecko
ADD https://dl.winehq.org/wine/wine-mono/${MONO_VER}/wine-mono-${MONO_VER}.msi /usr/share/wine/mono
ADD https://dl.winehq.org/wine/wine-gecko/${GECKO_VER}/wine-gecko-${GECKO_VER}-x86.msi /usr/share/wine/gecko
ADD https://dl.winehq.org/wine/wine-gecko/${GECKO_VER}/wine-gecko-${GECKO_VER}-x86_64.msi /usr/share/wine/gecko


# Wine Tricks
ADD https://raw.githubusercontent.com/Winetricks/winetricks/master/src/winetricks /usr/bin
RUN apt install -y wget zenity && \
    chmod +x /usr/bin/winetricks


ENV WINEPREFIX=/root/.wine \
    WINEDLLOVERRIDES="mscoree=" \
    WINEARCH=win64

# Initialize Wine and wait for it to complete
RUN wine wineboot --init && \
    while pgrep wineserver > /dev/null; do \
        echo "Waiting for wine to initialize..."; \
        sleep 1; \
    done

COPY ./docker/install_python.sh /root/.wine/drive_c/
RUN chmod +x /root/.wine/drive_c/install_python.sh && xvfb-run bash install_python.sh

COPY ./docker/install_and_run_mt5ubuntu.sh /root/.wine/drive_c/fx/
RUN chmod +x /root/.wine/drive_c/fx/install_and_run_mt5ubuntu.sh

COPY ./docker/*.sh /root/.wine/drive_c/fx/
COPY ./docker/supervisord.conf /etc/supervisor/conf.d/supervisord.conf

RUN xvfb-run bash /root/.wine/drive_c/fx/install_and_run_mt5ubuntu.sh || true

RUN touch /root/.wine/.update-timestamp
RUN echo 'disable' > $WINEPREFIX/.update-timestamp


RUN mkdir -p /root/Desktop
COPY ./docker/metatrader5.desktop /root/Desktop/
#RUN gio set -t string /root/Desktop/metatrader5.desktop metadata::xfce-exe-checksum "$(sha256sum /root/Desktop/metatrader5.desktop | awk '{print $1}')"
#RUN gio set -t string /root/Desktop/metatrader5.desktop metadata::xfce-exe-checksum "53f7ef56e40b6f8b1a83b23cc73d973580452cd3b6e0042cfc2b34f065b9bb91"
#RUN /usr/bin/gio set -t string /root/Desktop/metatrader5.desktop metadata::xfce-exe-checksum "53f7ef56e40b6f8b1a83b23cc73d973580452cd3b6e0042cfc2b34f065b9bb91"

#RUN kwriteconfig5 --file kiorc --group "KDE Action Restrictions" --key "shell_access" true


COPY ./docker/*.py /root/.wine/drive_c/fx/

CMD ["/usr/bin/supervisord"]