from pathlib import Path
import pandas as pd

pd.set_option("display.width", 250)
pd.set_option("display.max_columns", None)

ROOT = Path(__file__).resolve().parent.parent
df = pd.read_csv(ROOT / "data" / "DataCoSupplyChainDataset.csv", encoding="cp1252")
us = df[df["Order Country"] == "Estados Unidos"]
print(pd.crosstab(us["Order Status"], us["Delivery Status"], margins=True))