docker compose  -f docker-compose.apis.yml down 'news-handler'
docker compose  -f docker-compose.apis.yml build 'news-handler'
docker compose  -f docker-compose.apis.yml up 'news-handler'
