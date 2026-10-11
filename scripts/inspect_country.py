from pathlib import Path
import pandas as pd

# 项目根目录 = 这个脚本所在文件夹的上一级
ROOT = Path(__file__).resolve().parent.parent
PATH = ROOT / "data" / "DataCoSupplyChainDataset.csv"

print("Looking for:", PATH)
print("File exists:", PATH.exists())

# 这个 CSV 是 Windows-1252 编码
df = pd.read_csv(PATH, encoding="cp1252")

print()
print("ALL COLUMNS:")
for c in df.columns:
    print("  ", c)

print()
for col in [c for c in df.columns if "country" in c.lower()]:
    print(f"=== {col}: top 20 values ===")
    print(df[col].value_counts().head(20))
    print()