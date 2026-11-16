# MarketPilot AI

MarketPilot AI is a local single-user MVP for managing products, calculating pricing guidance, and generating review-only marketplace listing previews. It includes SQLite persistence, validated local image storage, a Google ADK multi-agent workflow, and a Streamlit dashboard.

## Requirements

- Python 3.10 or newer
- A Gemini API key in `.env` to run live agent workflows. Tests use mocked agent outputs and do not call Gemini.

## Setup

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `.env` and set `GEMINI_API_KEY` to a newly generated key. Do not commit `.env`. Revoke any key that was previously pasted into chat before creating a replacement.

## Initialize the local database

```powershell
python init_db.py
```

The SQLite database defaults to `marketpilot.db`. Product images default to `uploads/products/`. Both locations can be changed in `.env`.

The database layer provides product create, read, update, list and delete operations, and stores workflow runs and their partial or completed results. Uploaded image helpers validate JPG, JPEG, PNG and WebP image content, enforce the 5 MB and five-image limits, assign unique filenames, and delete a product's stored images when the product is deleted.

## Run a product AI workflow

Create a product record through the Python database service, note its ID, then run:

```powershell
.\.venv\Scripts\python.exe -c "from database.db import initialize_database; from database.products import create_product; initialize_database(); print(create_product({'name':'Tea cup','description':'Blue ceramic cup for tea','specifications':'Color: blue; material: ceramic','manufacturing_cost':100,'packaging_cost':10,'shipping_cost':5,'fixed_marketplace_fees':5,'commission_rate':0.10,'desired_profit_margin':0.20,'sku':'CUP-1'}))"
.\.venv\Scripts\python.exe run_agents.py --product-id 1
```

The workflow uses ADK LLM agents for product analysis, SEO descriptions, marketing, and Amazon/Flipkart previews. It runs deterministic pricing in Python and saves each successful output and any workflow errors in SQLite. The local app allows 20 workflows per day and one active workflow at a time. Marketplace results are previews only; no listing is published. The Gemini model is configured by `GEMINI_MODEL` and defaults to `gemini-3.8-flash`.

## Run the local dashboard

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1
```

Open the local URL printed by Streamlit (normally `http://127.0.0.1:8501`). Demo mode keeps its sample product and uploaded image in the current session only, makes no Gemini calls, labels every simulated AI sample as demo data, and uses the Python pricing engine for sample financial results. The Marketplace Distribution page saves seller review edits and approval status only; it does not publish listings.

## Run the current checks

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

## Configuration

`GEMINI_MODEL` defaults to `gemini-3.8-flash`. Other configurable settings include `DATABASE_PATH`, `UPLOAD_DIR`, `MAX_WORKFLOWS_PER_DAY`, `MAX_IMAGE_MB` and `MAX_IMAGES_PER_PRODUCT`.
