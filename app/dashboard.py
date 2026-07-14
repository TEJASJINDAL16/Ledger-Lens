"""LedgerLens Streamlit Dashboard (Phase 8).

4-tab dashboard featuring a clean, minimalist UI with Figma-inspired
aesthetics (custom CSS, purple charts, status pills).
"""

import json
from pathlib import Path
import duckdb
import pandas as pd
import streamlit as st
import altair as alt

from src.config import load_config, PROJECT_ROOT

st.set_page_config(page_title="LedgerLens", page_icon="💳", layout="wide")

# ---------------------------------------------------------
# Custom CSS (Figma Aesthetic)
# ---------------------------------------------------------
# Injecting CSS to style DataFrames, metrics, and create pill badges
custom_css = """
<style>
    /* Global Font & Background adjustments to feel clean */
    .stApp {
        background-color: #FFFFFF !important;
    }
    .stMarkdown, .stText, p, h1, h2, h3, h4, h5, h6, span {
        color: #111827 !important;
        font-family: 'Inter', sans-serif !important;
    }
    /* Style metric cards to match Figma */
    [data-testid="stMetricValue"] {
        font-size: 2.5rem !important;
        font-weight: 700 !important;
        color: #111827 !important;
    }
    [data-testid="stMetricLabel"] {
        font-size: 1rem !important;
        font-weight: 500 !important;
        color: #6B7280 !important;
    }
    /* Custom Pill Badges */
    .badge-green {
        background-color: #DEF7EC;
        color: #03543F;
        padding: 4px 12px;
        border-radius: 12px;
        font-size: 0.85rem;
        font-weight: 600;
        display: inline-block;
    }
    .badge-red {
        background-color: #FDE8E8;
        color: #9B1C1C;
        padding: 4px 12px;
        border-radius: 12px;
        font-size: 0.85rem;
        font-weight: 600;
        display: inline-block;
    }
    .badge-yellow {
        background-color: #FEF3C7;
        color: #92400E;
        padding: 4px 12px;
        border-radius: 12px;
        font-size: 0.85rem;
        font-weight: 600;
        display: inline-block;
    }
    .badge-gray {
        background-color: #F3F4F6;
        color: #374151;
        padding: 4px 12px;
        border-radius: 12px;
        font-size: 0.85rem;
        font-weight: 600;
        display: inline-block;
    }
</style>
"""
st.markdown(custom_css, unsafe_allow_html=True)

# ---------------------------------------------------------
# Data Loading
# ---------------------------------------------------------
@st.cache_resource
def get_db_connection():
    cfg = load_config()
    db_path = PROJECT_ROOT / cfg["paths"]["warehouse_db"]
    return duckdb.connect(str(db_path), read_only=True)

@st.cache_data
def load_scorecard():
    cfg = load_config()
    json_path = PROJECT_ROOT / cfg["paths"]["scorecard_json"]
    if json_path.exists():
        with open(json_path, "r") as f:
            return json.load(f)
    return {}

con = get_db_connection()
scorecard = load_scorecard()

# ---------------------------------------------------------
# UI Header
# ---------------------------------------------------------
st.title("💳 LedgerLens")
st.markdown("Enterprise spend analytics across all channels, driven by an automated Data Quality Pipeline.")

tab1, tab2, tab3, tab4 = st.tabs(["Data Health", "Merchant Intelligence", "Insights", "Decisions"])

# ---------------------------------------------------------
# TAB 1: DATA HEALTH
# ---------------------------------------------------------
with tab1:
    st.header("Pipeline Scorecard")
    st.markdown("Metrics comparing the raw inbound data to the clean Silver/Gold output.")
    
    col1, col2, col3, col4 = st.columns(4)
    if scorecard:
        col1.metric("Rows Quarantined", f"{scorecard.get('rows_quarantined', 0):,}")
        col2.metric("Exact Dupes Dropped", f"{scorecard.get('exact_duplicates_dropped', 0):,}")
        col3.metric("Near Dupes Flagged", f"{scorecard.get('near_duplicates_flagged', 0):,}")
        col4.metric("MCCs Imputed", f"{scorecard.get('mcc_imputed_count', 0):,}")
        
    st.divider()
    
    st.subheader("Health by Channel & Month (SLA Tracking)")
    st.markdown("Tracks upstream feed quality. SLA threshold is set at a 90% Health Score.")
    
    health_df = con.execute("SELECT * FROM v_data_health_by_source").df()
    if not health_df.empty:
        # Create a date column for the x-axis
        health_df["period"] = pd.to_datetime(health_df["year"].astype(str) + "-" + health_df["month"].astype(str) + "-01")
        
        # Clean multi-line chart for Health Score over time
        chart = alt.Chart(health_df).mark_line(point=True, strokeWidth=3).encode(
            x=alt.X('period:T', title='Month'),
            y=alt.Y('data_health_score:Q', title='Health Score', scale=alt.Scale(domain=[70, 100])),
            color=alt.Color('channel:N', title='Channel', scale=alt.Scale(scheme='set2')),
            tooltip=['channel', 'period', 'data_health_score']
        ).properties(title="")
        
        # Add the 90% SLA red line
        sla_line = alt.Chart(pd.DataFrame({'y': [90]})).mark_rule(color='#9B1C1C', strokeDash=[4,4]).encode(y='y:Q')
        
        st.altair_chart(chart + sla_line, use_container_width=True)

# ---------------------------------------------------------
# TAB 2: MERCHANT INTELLIGENCE
# ---------------------------------------------------------
with tab2:
    st.header("Merchant Resolution Dictionary")
    st.markdown("Search how raw descriptor strings mapped to canonical merchants.")
    
    col_search, col_slider = st.columns([2, 1])
    search_term = col_search.text_input("🔍 Search Descriptor or Merchant", "")
    min_confidence = col_slider.slider("Confidence Threshold", 0.0, 1.0, 0.0, 0.05)
    
    query = """
    SELECT 
        raw_descriptor,
        merchant_name,
        match_method,
        match_confidence
    FROM fct_transactions f
    JOIN dim_merchant m ON f.merchant_id = m.merchant_id
    WHERE match_confidence >= ?
    """
    params = [min_confidence]
    if search_term:
        query += " AND (lower(raw_descriptor) LIKE ? OR lower(merchant_name) LIKE ?)"
        params.extend([f"%{search_term.lower()}%", f"%{search_term.lower()}%"])
        
    query += " LIMIT 100"
    
    merch_df = con.execute(query, params).df()
    
    # We will render this as HTML to use our custom Pill badges
    if not merch_df.empty:
        html = "<table style='width:100%; border-collapse: collapse;'>"
        html += "<tr style='border-bottom: 1px solid #E5E7EB; color:#6B7280; text-align:left;'>"
        html += "<th style='padding:12px;'>Raw Descriptor</th><th style='padding:12px;'>Resolved Merchant</th><th style='padding:12px;'>Method</th><th style='padding:12px;'>Confidence</th></tr>"
        
        for _, row in merch_df.iterrows():
            conf = row["match_confidence"]
            # Color logic for pills
            if conf >= 0.9:
                badge_class = "badge-green"
                status_text = f"High ({conf:.2f})"
            elif conf >= 0.5:
                badge_class = "badge-yellow"
                status_text = f"Med ({conf:.2f})"
            elif conf > 0:
                badge_class = "badge-red"
                status_text = f"Low ({conf:.2f})"
            else:
                badge_class = "badge-gray"
                status_text = "Unresolved"
                
            method = row["match_method"].title()
                
            html += f"<tr style='border-bottom: 1px solid #E5E7EB;'>"
            html += f"<td style='padding:12px; font-family: monospace; color:#374151;'>{row['raw_descriptor']}</td>"
            html += f"<td style='padding:12px; font-weight:500;'>{row['merchant_name']}</td>"
            html += f"<td style='padding:12px; color:#6B7280;'>{method}</td>"
            html += f"<td style='padding:12px;'><span class='{badge_class}'>{status_text}</span></td>"
            html += "</tr>"
            
        html += "</table>"
        st.markdown(html, unsafe_allow_html=True)
    else:
        st.info("No records found matching those filters.")

# ---------------------------------------------------------
# TAB 3: INSIGHTS
# ---------------------------------------------------------
with tab3:
    st.header("Analytical Insights")
    
    # --- View 1: Top 10 Merchants Before vs After ---
    st.subheader("Top 10 Merchants: Raw vs Resolved")
    st.markdown("Shows how resolving fragmented descriptors radically changes the perceived top merchants.")
    
    top_df = con.execute("SELECT * FROM v_top_merchants_before_after").df()
    if not top_df.empty:
        # Grouped bar chart using Altair (Figma purple theme)
        chart_top = alt.Chart(top_df).mark_bar(color="#6366F1").encode(
            x=alt.X('total_spend:Q', title='Total Spend (₹)'),
            y=alt.Y('merchant_identity:N', sort='-x', title=''),
            color=alt.Color('state:N', legend=alt.Legend(title=""), scale=alt.Scale(range=["#D1D5DB", "#6366F1"])),
            row=alt.Row('state:N', title=''),
            tooltip=['merchant_identity', 'total_spend', 'rank']
        ).properties(height=250).resolve_scale(y='independent')
        
        st.altair_chart(chart_top, use_container_width=True)

    colA, colB = st.columns(2)
    
    # --- View 2: Duplicate Exposure ---
    with colA:
        st.subheader("Duplicate Exposure")
        exp_df = con.execute("SELECT * FROM v_duplicate_exposure").df()
        if not exp_df.empty:
            count = exp_df.iloc[0]["near_duplicate_txn_count"]
            val = exp_df.iloc[0]["total_exposure_inr"]
            if pd.isna(val): val = 0
            st.metric("Total ₹ Value in Near-Dupes", f"₹ {val:,.2f}", delta=f"{count} transactions flagged", delta_color="off")
            
    # --- View 3: Category Mix ---
    with colB:
        st.subheader("Category Spend (Imputed vs Explicit)")
        cat_df = con.execute("SELECT * FROM v_category_spend_mix").df()
        if not cat_df.empty:
            chart_cat = alt.Chart(cat_df).mark_bar().encode(
                x=alt.X('sum(total_spend_inr):Q', title='Spend (₹)'),
                y=alt.Y('merchant_category:N', sort='-x', title='Category'),
                color=alt.Color('mcc_imputed_flag:N', scale=alt.Scale(range=["#6366F1", "#FEF3C7"]), title="Imputed?"),
                tooltip=['merchant_category', 'mcc_imputed_flag', 'total_spend_inr']
            ).properties(height=300)
            st.altair_chart(chart_cat, use_container_width=True)

# ---------------------------------------------------------
# TAB 4: DECISIONS
# ---------------------------------------------------------
with tab4:
    st.header("Architectural Decisions Log")
    st.markdown("Governance is a feature. All pipeline compromises and assumptions are documented here.")
    
    decisions_path = PROJECT_ROOT / "docs" / "DECISIONS.md"
    if decisions_path.exists():
        st.markdown(decisions_path.read_text())
    else:
        st.warning("DECISIONS.md not found.")
