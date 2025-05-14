FROM msjpq/wine-vnc:bionic

WORKDIR /root/.wine/drive_c/
RUN apt-get update && apt-get install -y sudo supervisor git wget software-properties-common xvfb
RUN apt-get remove winbind && apt-get install -y winbind
RUN apt-get install -y curl && rm -rf /var/lib/apt/lists/*

ENV WINEPREFIX=/root/.wine \
    WINEDLLOVERRIDES="mscoree=" \
    WINEARCH=win64

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