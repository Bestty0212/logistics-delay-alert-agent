from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
df = pd.read_csv(ROOT / "data" / "DataCoSupplyChainDataset.csv", encoding="cp1252")
us = df[(df["Order Country"] == "Estados Unidos") & (df["Delivery Status"] != "Shipping canceled")].copy()

od = pd.to_datetime(us["order date (DateOrders)"])
sd = pd.to_datetime(us["shipping date (DateOrders)"])
real = us["Days for shipping (real)"]

d_floor = (sd - od).dt.days
d_cal = (sd.dt.normalize() - od.dt.normalize()).dt.days
print("(ship - order).days == real:", round((d_floor == real).mean() * 100, 1), "%")
print("calendar-day diff == real:", round((d_cal == real).mean() * 100, 1), "%")
print("\nsample rows:")
print(pd.DataFrame({"order": od, "ship": sd, "real": real, "scheduled": us["Days for shipment (scheduled)"]}).head(8))

# 再多看几个下单时已知的特征，Standard Class 内部有没有信号
std = us[us["Shipping Mode"] == "Standard Class"].copy()
def show(name, key):
    print(f"\nStandard Class late % by {name}:")
    print(std.groupby(key)["Late_delivery_risk"]
            .agg(rows="size", late_pct=lambda s: round(s.mean() * 100, 1))
            .sort_values("late_pct", ascending=False).head(8))

g = std.groupby("Order State")["Late_delivery_risk"].transform("size")
show("state (>=150 rows)", std.loc[g >= 150, "Order State"])
show("quantity", std["Order Item Quantity"])
show("discount rate quartile", pd.qcut(std["Order Item Discount Rate"], 4, duplicates="drop"))
show("product price quartile", pd.qcut(std["Product Price"], 4, duplicates="drop"))