### NewsStats


## 1️⃣ Setup the environment

```bash
cd api/stats
(python3 -m venv venv )
source venv/bin/activate
(install required packages)
```
## 2️⃣ Execute Same validation ans extract json data  

This module generates json data for further analysis. We will only get data files if the news goes to VALIDATES status.

```bash
python collector.py \
  --text "Text to validate" \
  --num_runs 2 \
  --timeout 200 \

```
## 2️⃣ BIS  Generate json data from existing orders

We can get the same output using preexisting orders by setting order_id in output/orders.csv directly and executing this module.


```bash
python refetch_orders.py

```

## 3️⃣ Generate Stat News

Once we get json data file we can excute stat module. We need the output/orders.csv and related directories properly informed with news data.

```bash
python stats_report.py

```