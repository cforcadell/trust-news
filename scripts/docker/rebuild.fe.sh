docker compose  -f ../docker-compose.apis.yml down 'frontend-web_classic'
docker compose  -f ../docker-compose.apis.yml build 'frontend-web_classic'
docker compose  -f ../docker-compose.apis.yml up 'frontend-web_classic'