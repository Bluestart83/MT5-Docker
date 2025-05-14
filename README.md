Fork de fx-tinny

# Instructions:
- Install docker
- Fill account in for into docker compose file
- docker compose up
- goto http://localhost:8000 to access the remote desktop
- goto http://localhost:8001/docs to access swagger api

# Changes in this FORK:
- No custom exe, we download it directly from Metatrader !
- Added some API for history and tick fetch, and order modify (not fully tested)
- Now use last version of Wine-HQ ! (that is supported by MT5 officially)
- Added config save in docker compose in order to keep config between image launches!
It's needded when using generic images, because MT5 Servers DNS like are not fetched.

# See:
https://medium.com/@asc686f61/use-mt5-in-linux-with-docker-and-python-f8a9859d65b1

