from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
df = pd.read_csv(ROOT / "data" / "DataCoSupplyChainDataset.csv", encoding="cp1252")
us = df[df["Order Country"] == "Estados Unidos"]

# 1. 这几列在美国子集里有多少是空的？
for col in ["Product Description", "Order Zipcode", "Customer Zipcode"]:
    print(f"{col}: {us[col].isna().mean() * 100:.1f}% empty")

# 2. Email 和 Password 是真实内容还是已经被遮盖？（只看有几种不同的值，不打印具体内容）
for col in ["Customer Email", "Customer Password"]:
    print(f"{col}: {us[col].nunique()} distinct values")