### NewsStats


## 1️⃣ Setup the environment

```bash
cd api/tests
(python3 -m venv venv )
source venv/bin/activate
(install required packages)
```
## 2️⃣ Execute tests 


```bash
/home/adminu/blockchain/tfm/api/tests/
pytest .
pytest ./test_extraer_integration.py --> Check generate assertion internal endpoint
pytest ./test_ipfs_integration.py --> Upload and download ipfs content using internal endoints
pytest ./test_news-chain_integration.py -> tests post create and recovery using news-chain internal API
pytest test_news-handler.py --> Validates using gateway publishNew and recovers order ang assures thats reachs validated status 
pytest ./test_quotas.py --> Tests quota module using oath client using gateway and admin endpoints. 
pytest ./test_validator_api.py  --> Validates validation assertion and validator registration using internal API


```