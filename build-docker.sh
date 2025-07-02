#docker build -f ./docker/Dockerfile.freqai -t bluestart83/mt5-docker:dev .
docker push bluestart83/mt5-docker:dev
docker push bluestart83/mt5-histo:dev

#docker build -f ./docker/Dockerfile.freqai_rl -t bluestart83/freqtrade:dev_freqaitorch_rl_bitget .
#docker push bluestart83/freqtrade:dev_freqaitorch_rl_bitget
