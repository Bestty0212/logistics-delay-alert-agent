from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
df = pd.read_csv(ROOT / "data" / "DataCoSupplyChainDataset.csv", encoding="cp1252")
us = df[df["Order Country"] == "Estados Unidos"].copy()

# A. 那 2.3% 的不一致来自哪里？
us["late_calc"] = (us["Days for shipping (real)"] > us["Days for shipment (scheduled)"]).astype(int)
mm = us[us["late_calc"] != us["Late_delivery_risk"]]
print("Mismatch rows:", len(mm))
print(mm["Delivery Status"].value_counts())

# B. 排除取消订单后的延迟率
act = us[us["Delivery Status"] != "Shipping canceled"].copy()
print("\nRows after excluding canceled:", len(act), "| distinct orders:", act["Order Id"].nunique())
print(act.groupby("Shipping Mode")["Late_delivery_risk"]
        .agg(rows="size", late_pct=lambda s: round(s.mean() * 100, 1)))
print("Overall late %:", round(act["Late_delivery_risk"].mean() * 100, 1))

# C. 只按运输方式的规则：混淆矩阵、精确率、召回率
mode_late = act.groupby("Shipping Mode")["Late_delivery_risk"].mean()
act["pred"] = act["Shipping Mode"].map(lambda m: int(mode_late[m] > 0.5))
tp = int(((act.pred == 1) & (act.Late_delivery_risk == 1)).sum())
fp = int(((act.pred == 1) & (act.Late_delivery_risk == 0)).sum())
fn = int(((act.pred == 0) & (act.Late_delivery_risk == 1)).sum())
tn = int(((act.pred == 0) & (act.Late_delivery_risk == 0)).sum())
print("\nConfusion: TP", tp, "FP", fp, "FN", fn, "TN", tn)
print("Precision:", round(tp / (tp + fp) * 100, 1), "%")
print("Recall:", round(tp / (tp + fn) * 100, 1), "%")
print("Accuracy:", round((tp + tn) / len(act) * 100, 1), "%")
print("Baseline (never late) accuracy:", round((act.Late_delivery_risk == 0).mean() * 100, 1), "%")

# D. Standard Class 里，什么能区分延迟？（只用下单时已知的信息）
std = act[act["Shipping Mode"] == "Standard Class"].copy()
dt = pd.to_datetime(std["order date (DateOrders)"])
std["weekday"] = dt.dt.day_name()
std["month"] = dt.dt.to_period("M").astype(str)
for col in ["weekday", "month", "Department Name", "Customer Segment"]:
    print(f"\nStandard Class late % by {col}:")
    print(std.groupby(col)["Late_delivery_risk"]
            .agg(rows="size", late_pct=lambda s: round(s.mean() * 100, 1))
            .sort_values("late_pct", ascending=False).head(10))