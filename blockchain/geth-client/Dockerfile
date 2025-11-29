FROM ethereum/client-go:v1.10.1

ARG ACCOUNT_PASSWORD

COPY ./genesis.json /tmp

# Script de inicialización
RUN mkdir -p /root/.ethereum \
    && geth init /tmp/genesis.json \
    && rm -f ~/.ethereum/geth/nodekey \
    && /bin/sh -c 'if [ ! -d /root/.ethereum/keystore ] || [ "$(ls -A /root/.ethereum/keystore 2>/dev/null)" = "" ]; then \
         echo "$ACCOUNT_PASSWORD" > /tmp/pass && \
         geth account new --password /tmp/pass && \
         rm -f /tmp/pass; \
       fi'

ENTRYPOINT ["geth"]
