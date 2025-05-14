FROM msjpq/wine-vnc:bionic

WORKDIR /root/.wine/drive_c/

# Install dependencies for adding WineHQ repository
RUN apt-get update && apt-get install -y sudo supervisor git wget software-properties-common xvfb \
    apt-transport-https ca-certificates gnupg curl

# Remove old wine and winbind
RUN apt-get remove -y wine* winbind

# Add WineHQ repository
RUN dpkg --add-architecture i386 && \
    wget -qO- https://dl.winehq.org/wine-builds/winehq.key | apt-key add - && \
    apt-add-repository 'deb https://dl.winehq.org/wine-builds/ubuntu/ bionic main'

# Install latest stable Wine
RUN apt-get update && \
    apt-get install -y --install-recommends winehq-stable && \
    apt-get install -y winbind && \
    rm -rf /var/lib/apt/lists/*

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

COPY ./docker/*.py /root/.wine/drive_c/fx/

CMD ["/usr/bin/supervisord"]