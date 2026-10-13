from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
DB = ROOT / "warehouse" / "foodflow.db"
TABLES = ["users", "restaurant", "food", "menu", "orders", "order_items", "reviews"]
