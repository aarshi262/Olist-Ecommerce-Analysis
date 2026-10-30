
import sqlite3
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="Olist E-Commerce Intelligence Analyzer",
    page_icon="📊",
    layout="wide",
)

BASE_DIR = Path(__file__).resolve().parent

DB_PATH = BASE_DIR / "olist.db"
ZIP_PATH = BASE_DIR / "olist.zip"

if not DB_PATH.exists():
    if ZIP_PATH.exists():
        with zipfile.ZipFile(ZIP_PATH, "r") as zip_ref:
            zip_ref.extract("olist.db", BASE_DIR)
    else:
        st.error("Database ZIP file not found!")
        st.stop()

st.title("📊 Olist E-Commerce Intelligence Analyzer")
st.caption("Brazilian E-Commerce | Sales | Reviews | Delivery Insights")


@st.cache_data
def load_data(db_path, modified_time):
    with sqlite3.connect(db_path) as conn:
        tables = pd.read_sql_query(
            "SELECT name FROM sqlite_master WHERE type='table'",
            conn,
        )["name"].tolist()

        required = {"orders", "payments", "reviews"}
        missing = required - set(tables)

        if missing:
            raise ValueError(f"Missing database tables: {sorted(missing)}")

        orders = pd.read_sql_query("SELECT * FROM orders", conn)
        payments = pd.read_sql_query("SELECT * FROM payments", conn)
        reviews = pd.read_sql_query("SELECT * FROM reviews", conn)

    date_cols = [
        "order_purchase_timestamp",
        "order_approved_at",
        "order_delivered_carrier_date",
        "order_delivered_customer_date",
        "order_estimated_delivery_date",
    ]

    for col in date_cols:
        if col in orders.columns:
            orders[col] = pd.to_datetime(orders[col], errors="coerce")

    for col in ["payment_value", "payment_installments"]:
        if col in payments.columns:
            payments[col] = pd.to_numeric(payments[col], errors="coerce")

    if "review_score" in reviews.columns:
        reviews["review_score"] = pd.to_numeric(
            reviews["review_score"], errors="coerce"
        )

    orders["month"] = (
        orders["order_purchase_timestamp"].dt.to_period("M").astype(str)
    )

    return orders, payments, reviews


try:
    orders_all, payments_all, reviews_all = load_data(
        str(DB_PATH), DB_PATH.stat().st_mtime
    )
except Exception as exc:
    st.error(f"Database loading error: {exc}")
    st.stop()

st.sidebar.header("🔎 Dashboard Filters")

valid_dates = orders_all["order_purchase_timestamp"].dropna()

if valid_dates.empty:
    st.error("No valid order purchase dates found.")
    st.stop()

min_date = valid_dates.min().date()
max_date = valid_dates.max().date()

date_range = st.sidebar.date_input(
    "Purchase date range",
    value=(min_date, max_date),
    min_value=min_date,
    max_value=max_date,
)

if isinstance(date_range, (tuple, list)) and len(date_range) == 2:
    start_date, end_date = date_range
else:
    start_date = end_date = date_range

all_statuses = sorted(orders_all["order_status"].dropna().unique())
selected_statuses = st.sidebar.multiselect(
    "Order status",
    all_statuses,
    default=all_statuses,
)

payment_types = sorted(payments_all["payment_type"].dropna().unique())
selected_payments = st.sidebar.multiselect(
    "Payment type",
    payment_types,
    default=payment_types,
)

exclude_last_month = st.sidebar.checkbox(
    "Exclude last (possibly partial) month",
    value=False,
)

date_mask = orders_all["order_purchase_timestamp"].dt.date.between(
    start_date, end_date
)

orders = orders_all[
    date_mask & orders_all["order_status"].isin(selected_statuses)
].copy()

if exclude_last_month and not orders.empty:
    last_month = orders_all["month"].max()
    orders = orders[orders["month"] != last_month].copy()

if orders.empty:
    st.warning("No orders match these filters. Change the date or status filters.")
    st.stop()

order_ids = orders["order_id"].dropna().unique()

payments = payments_all[payments_all["order_id"].isin(order_ids)].copy()
payments = payments[payments["payment_type"].isin(selected_payments)].copy()

reviews = reviews_all[reviews_all["order_id"].isin(order_ids)].copy()

delivered = orders.dropna(
    subset=[
        "order_purchase_timestamp",
        "order_delivered_customer_date",
        "order_estimated_delivery_date",
    ]
).copy()

delivered["delivery_days"] = (
    delivered["order_delivered_customer_date"]
    - delivered["order_purchase_timestamp"]
).dt.total_seconds() / 86400

delivered["days_late"] = (
    delivered["order_delivered_customer_date"]
    - delivered["order_estimated_delivery_date"]
).dt.total_seconds() / 86400

delivered["on_time"] = delivered["days_late"] <= 0

on_time_rate = (
    delivered["on_time"].mean() if not delivered.empty else None
)
late_rate = (
    (~delivered["on_time"]).mean()
    if not delivered.empty
    else None
)

st.subheader("Business Overview")

k1, k2, k3, k4 = st.columns(4)

k1.metric("Total Orders", f"{orders['order_id'].nunique():,}")
k2.metric("Payment Value", f"R$ {payments['payment_value'].sum():,.2f}")
k3.metric(
    "Average Review Score",
    f"{reviews['review_score'].mean():.2f} / 5"
    if reviews["review_score"].notna().any()
    else "N/A",
)
k4.metric(
    "On-Time Delivery",
    f"{on_time_rate:.1%}" if on_time_rate is not None else "N/A",
)

st.caption(
    "Payment Value is the sum of recorded payment transactions, not profit. "
    "Payment-type filters affect payment metrics; order counts remain based "
    "on the selected orders."
)

st.divider()

overview_tab, sales_tab, review_tab, delivery_tab, data_tab = st.tabs(
    ["Overview", "Sales & Payments", "Customer Reviews", "Delivery", "Data Explorer"]
)

with overview_tab:
    left, right = st.columns(2)

    with left:
        st.subheader("Orders by Status")
        status_counts = (
            orders["order_status"]
            .value_counts()
            .rename_axis("Order Status")
            .reset_index(name="Orders")
        )

        chart = (
            alt.Chart(status_counts)
            .mark_bar()
            .encode(
                x=alt.X("Order Status:N", sort="-y"),
                y=alt.Y("Orders:Q"),
                tooltip=["Order Status", "Orders"],
            )
            .interactive()
        )
        st.altair_chart(chart, use_container_width=True)

    with right:
        st.subheader("Monthly Order Trend")
        monthly = (
            orders.dropna(subset=["order_purchase_timestamp"])
            .groupby("month")
            .size()
            .reset_index(name="Orders")
            .sort_values("month")
        )

        if not monthly.empty:
            st.line_chart(monthly.set_index("month"))

    st.subheader("Order Data Preview")
    st.dataframe(orders.head(10), use_container_width=True)

with sales_tab:
    total_payment_value = payments["payment_value"].sum()
    order_payment_values = payments.groupby("order_id")["payment_value"].sum()

    s1, s2, s3 = st.columns(3)
    s1.metric("Payment Value", f"R$ {total_payment_value:,.2f}")
    s2.metric(
        "Average Payment per Order",
        f"R$ {order_payment_values.mean():,.2f}"
        if not order_payment_values.empty else "N/A",
    )

    if "payment_installments" in payments.columns:
        s3.metric(
            "Average Installments",
            f"{payments['payment_installments'].mean():.1f}"
            if payments["payment_installments"].notna().any() else "N/A",
        )

    st.subheader("Payment Value by Payment Type")
    payment_mix = (
        payments.groupby("payment_type", dropna=False)["payment_value"]
        .sum()
        .reset_index()
        .sort_values("payment_value", ascending=False)
    )

    if not payment_mix.empty:
        payment_chart = (
            alt.Chart(payment_mix)
            .mark_bar()
            .encode(
                x=alt.X("payment_type:N", title="Payment Type", sort="-y"),
                y=alt.Y("payment_value:Q", title="Payment Value (R$)"),
                tooltip=[
                    "payment_type",
                    alt.Tooltip("payment_value:Q", format=",.2f"),
                ],
            )
            .interactive()
        )
        st.altair_chart(payment_chart, use_container_width=True)

    st.subheader("Monthly Payment Value")
    payment_monthly = payments.merge(
        orders[["order_id", "month"]].drop_duplicates("order_id"),
        on="order_id",
        how="inner",
    )

    monthly_payment = (
        payment_monthly.groupby("month")["payment_value"]
        .sum()
        .sort_index()
    )

    if not monthly_payment.empty:
        st.line_chart(monthly_payment)

with review_tab:
    st.subheader("Review Score Distribution")

    score_counts = (
        reviews["review_score"]
        .dropna()
        .value_counts()
        .sort_index()
        .rename_axis("Review Score")
        .reset_index(name="Reviews")
    )

    if not score_counts.empty:
        st.bar_chart(score_counts.set_index("Review Score"))

    st.subheader("Average Review Score by Month")
    review_monthly = reviews.merge(
        orders[["order_id", "month"]].drop_duplicates("order_id"),
        on="order_id",
        how="inner",
    )

    monthly_scores = (
        review_monthly.groupby("month")["review_score"]
        .mean()
        .sort_index()
    )

    if not monthly_scores.empty:
        st.line_chart(monthly_scores)

    st.caption(
        "Reviews are linked to orders using order_id. "
        "This dataset does not contain a customer table, so unique customers "
        "cannot be accurately calculated from these three tables alone."
    )

with delivery_tab:
    if delivered.empty:
        st.info("No delivered orders are available in this selection.")
    else:
        d1, d2, d3, d4 = st.columns(4)

        d1.metric("On-Time Rate", f"{on_time_rate:.1%}")
        d4.metric(
             "Late Delivery %",
              f"{late_rate:.2%}" if late_rate is not None else "N/A",
        )
        d2.metric(
            "Average Delivery Time",
            f"{delivered['delivery_days'].mean():.2f} days",
        )

        late_orders = delivered.loc[~delivered["on_time"], "days_late"]
        d3.metric(
            "Average Days Late",
            f"{late_orders.mean():.2f}" if not late_orders.empty else "0",
        )

        st.subheader("Delivery vs Estimated Date")
        st.caption("Negative = early, zero = on time, positive = late.")

        delay_data = delivered[["days_late"]].dropna().copy()
        delay_data["days_late"] = delay_data["days_late"].clip(-40, 40)

        delay_chart = (
            alt.Chart(delay_data)
            .mark_bar()
            .encode(
                x=alt.X(
                    "days_late:Q",
                    bin=alt.Bin(maxbins=40),
                    title="Days vs Estimated Delivery",
                ),
                y=alt.Y("count():Q", title="Orders"),
                tooltip=[alt.Tooltip("count():Q", title="Orders")],
            )
        )
        st.altair_chart(delay_chart, use_container_width=True)

        st.subheader("Monthly On-Time Delivery Rate")
        monthly_ontime = delivered.groupby("month")["on_time"].mean().sort_index()
        st.line_chart(monthly_ontime)

with data_tab:
    st.subheader("Filtered Orders")
    st.write(f"Showing up to 100 of {len(orders):,} filtered orders.")
    st.dataframe(orders.head(100), use_container_width=True)

    st.download_button(
        "Download Filtered Orders CSV",
        data=orders.to_csv(index=False).encode("utf-8"),
        file_name="olist_filtered_orders.csv",
        mime="text/csv",
    )

    st.download_button(
        "Download Filtered Payments CSV",
        data=payments.to_csv(index=False).encode("utf-8"),
        file_name="olist_filtered_payments.csv",
        mime="text/csv",
    )

    st.download_button(
        "Download Filtered Reviews CSV",
        data=reviews.to_csv(index=False).encode("utf-8"),
        file_name="olist_filtered_reviews.csv",
        mime="text/csv",
    )

st.divider()
st.caption("Olist E-Commerce Intelligence Analyzer | Python + SQLite + Streamlit")
