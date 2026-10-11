from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
df = pd.read_csv(ROOT / "data" / "DataCoSupplyChainDataset.csv", encoding="cp1252")
us = df[df["Order Country"] == "Estados Unidos"].copy()

# 1. 标签是否和"实际天数 > 承诺天数"一致？
us["late_calc"] = (us["Days for shipping (real)"] > us["Days for shipment (scheduled)"]).astype(int)
print("Label matches (real > scheduled):",
      round((us["late_calc"] == us["Late_delivery_risk"]).mean() * 100, 2), "%")

# 2. 配送状态和标签的关系（看取消订单被标成什么）
print("\nDelivery Status vs Late_delivery_risk:")
print(pd.crosstab(us["Delivery Status"], us["Late_delivery_risk"]))

# 3. 承诺天数和实际天数，按运输方式
print("\nScheduled vs real days by shipping mode:")
print(us.groupby("Shipping Mode")[["Days for shipment (scheduled)", "Days for shipping (real)"]]
        .agg(["mean", "min", "max"]).round(2))

# 4. 同一运输方式内，延迟率随州变化吗？（只看订单项>=100的州）
print("\nLate rate by state within each shipping mode (min 100 rows):")
g = us.groupby(["Shipping Mode", "Order State"]).agg(
    rows=("Order Id", "size"),
    late_pct=("Late_delivery_risk", lambda s: round(s.mean() * 100, 1)),
).reset_index()
g = g[g["rows"] >= 100]
print(g.groupby("Shipping Mode")["late_pct"].agg(["count", "min", "max"]))

# 5. 用"只按运输方式"的规则，在美国数据上的准确率
mode_late = us.groupby("Shipping Mode")["Late_delivery_risk"].mean()
us["pred"] = us["Shipping Mode"].map(lambda m: int(mode_late[m] > 0.5))
print("\nMode-only rule accuracy:",
      round((us["pred"] == us["Late_delivery_risk"]).mean() * 100, 1), "%")
print("Baseline 'never late' accuracy:",
      round((us["Late_delivery_risk"] == 0).mean() * 100, 1), "%")