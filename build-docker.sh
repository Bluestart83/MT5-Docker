docker compose down

#docker image prune -a
docker system prune -a --volumes

docker build --progress=plain -f ./docker/Dockerfile -t bluestart83/mt5-docker:dev . && docker compose build --no-cache
#docker build --no-cache --progress=plain -f ./docker/Dockerfile -t bluestart83/mt5-docker:dev . && docker compose build --no-cache

#docker compose up -d

#docker push bluestart83/mt5-docker:dev
#docker push bluestart83/mt5-histo:dev

#docker build -f ./docker/Dockerfile.freqai_rl -t bluestart83/freqtrade:dev_freqaitorch_rl_bitget .
#docker push bluestart83/freqtrade:dev_freqaitorch_rl_bitget
