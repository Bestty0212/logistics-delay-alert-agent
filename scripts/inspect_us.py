from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
df = pd.read_csv(ROOT / "data" / "DataCoSupplyChainDataset.csv", encoding="cp1252")

# 1. Puerto Rico 会不会作为送达地出现？
print("Order Country values containing 'Puerto':")
print(df.loc[df["Order Country"].str.contains("Puerto", na=False), "Order Country"].value_counts())

# 2. 筛出美国，看行数和订单数
us = df[df["Order Country"] == "Estados Unidos"].copy()
print("\nUS rows (order items):", len(us))
print("US distinct orders:", us["Order Id"].nunique())

# 3. 日期范围，以及每个月的订单数（看哪个月之后数据变少或消失）
us["order_dt"] = pd.to_datetime(us["order date (DateOrders)"], errors="coerce")
print("\nUnparsed dates:", us["order_dt"].isna().sum())
print("Date range:", us["order_dt"].min(), "->", us["order_dt"].max())
print("\nDistinct orders per month:")
print(us.groupby(us["order_dt"].dt.to_period("M"))["Order Id"].nunique().to_string())

# 4. 各运输方式的延迟率
print("\nBy shipping mode:")
print(us.groupby("Shipping Mode").agg(
    rows=("Order Id", "size"),
    orders=("Order Id", "nunique"),
    late_pct=("Late_delivery_risk", lambda s: round(s.mean() * 100, 1)),
))

# 5. 配送状态
print("\nDelivery Status:")
print(us["Delivery Status"].value_counts())