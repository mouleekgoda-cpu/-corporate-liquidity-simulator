import streamlit as st
import pandas as pd
import requests
import json
import re
from datetime import datetime

st.set_page_config(page_title="Corporate Liquidity Simulator", page_icon="📊", layout="wide")

SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
HEADERS = {"User-Agent": "CorporateLiquiditySimulator"}

st.title("Corporate Liquidity & Recession Stress-Test")
st.caption("Free prototype • Public US SEC data + manual document upload • Educational analysis, not investment advice")
sec_contact = st.sidebar.text_input("Contact email for SEC requests", placeholder="you@example.com")
if sec_contact.strip():
    HEADERS["User-Agent"] = f"CorporateLiquiditySimulator {sec_contact.strip()}"
else:
    st.sidebar.info("Add your email before searching SEC data, as requested by the SEC.")

@st.cache_data(ttl=3600, show_spinner=False)
def load_tickers():
    r = requests.get(SEC_TICKERS_URL, headers=HEADERS, timeout=20)
    r.raise_for_status()
    data = r.json()
    return {v["title"].lower(): {"ticker": v["ticker"], "cik": str(v["cik_str"]).zfill(10)}
            for v in data.values()}

@st.cache_data(ttl=3600, show_spinner=False)
def load_company_facts(cik):
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()

def find_company(name, tickers):
    q = name.strip().lower()
    if q in tickers:
        return tickers[q]
    matches = [(k,v) for k,v in tickers.items() if q in k]
    if len(matches) == 1:
        return matches[0][1]
    if matches:
        return {"matches": matches[:15]}
    return None

def latest_fact(facts, candidates):
    units = facts.get("facts", {}).get("us-gaap", {})
    for tag in candidates:
        item = units.get(tag)
        if not item:
            continue
        vals = []
        for unit, entries in item.get("units", {}).items():
            for e in entries:
                if e.get("form") in ("10-K", "10-Q", "20-F", "40-F") and "val" in e:
                    vals.append((e.get("end",""), e["val"], e.get("fy"), e.get("fp"), e.get("form")))
        if vals:
            vals.sort(key=lambda x: x[0], reverse=True)
            return vals[0][1], vals[0][0], tag
    return None, None, None

def fact_value(facts, tags):
    value, end, tag = latest_fact(facts, tags)
    return value

def fmt(x):
    if x is None:
        return "Not found"
    return f"${x/1_000_000:,.1f}m"

st.markdown("### 1. Find a US-listed company")
company_name = st.text_input("Company name (e.g. Apple, Microsoft, Tesla)", placeholder="Enter company name")
if st.button("Find company and analyse", type="primary"):
    if not company_name.strip():
        st.warning("Enter a company name.")
    else:
        try:
            with st.spinner("Finding company in SEC records..."):
                tickers = load_tickers()
                result = find_company(company_name, tickers)
                if result is None:
                    st.error("No exact match found. Try its official company name or ticker symbol.")
                elif "matches" in result:
                    st.session_state["matches"] = result["matches"]
                    st.info("Several matches found. Select the correct company below.")
                else:
                    st.session_state["company"] = result
                    st.session_state["company_name"] = company_name
        except Exception as e:
            st.error(f"Could not reach SEC data right now: {e}")

if "matches" in st.session_state:
    options = st.session_state["matches"]
    choice = st.selectbox("Choose company", options, format_func=lambda x: f"{x[0].title()} (ticker: {x[1]['ticker']})")
    if st.button("Use selected company"):
        st.session_state["company"] = choice[1]
        st.session_state["company_name"] = choice[0].title()
        del st.session_state["matches"]

if "company" in st.session_state:
    company = st.session_state["company"]
    st.markdown("---")
    st.subheader(f"{st.session_state.get('company_name','Company')}  ·  {company['ticker']}")
    try:
        with st.spinner("Downloading latest available SEC company facts..."):
            facts = load_company_facts(company["cik"])
        tags = {
            "Cash and cash equivalents": ["CashAndCashEquivalentsAtCarryingValue", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"],
            "Current assets": ["AssetsCurrent"],
            "Current liabilities": ["LiabilitiesCurrent"],
            "Total assets": ["Assets"],
            "Total liabilities": ["Liabilities"],
            "Long-term debt": ["LongTermDebtCurrent", "LongTermDebtNoncurrent", "LongTermDebt"],
            "Revenue": ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet"],
            "Operating cash flow": ["NetCashProvidedByUsedInOperatingActivities"],
            "Capital expenditure": ["PaymentsToAcquirePropertyPlantAndEquipment"],
            "Interest expense": ["InterestExpenseNonOperating", "InterestAndDebtExpense"],
            "Inventory": ["InventoryNet"],
            "Receivables": ["AccountsReceivableNetCurrent"],
        }
        vals = {label: fact_value(facts, candidates) for label, candidates in tags.items()}
        c1,c2,c3 = st.columns(3)
        c1.metric("Cash & equivalents", fmt(vals["Cash and cash equivalents"]))
        c2.metric("Current assets", fmt(vals["Current assets"]))
        c3.metric("Current liabilities", fmt(vals["Current liabilities"]))
        current_ratio = (vals["Current assets"] / vals["Current liabilities"]
                         if vals["Current assets"] is not None and vals["Current liabilities"] not in (None,0) else None)
        quick_ratio = ((vals["Current assets"] - (vals["Inventory"] or 0)) / vals["Current liabilities"]
                       if vals["Current assets"] is not None and vals["Current liabilities"] not in (None,0) else None)
        cash_ratio = (vals["Cash and cash equivalents"] / vals["Current liabilities"]
                      if vals["Cash and cash equivalents"] is not None and vals["Current liabilities"] not in (None,0) else None)
        m1,m2,m3 = st.columns(3)
        m1.metric("Current ratio", f"{current_ratio:.2f}x" if current_ratio is not None else "Not available")
        m2.metric("Quick ratio (rough)", f"{quick_ratio:.2f}x" if quick_ratio is not None else "Not available")
        m3.metric("Cash ratio", f"{cash_ratio:.2f}x" if cash_ratio is not None else "Not available")
        st.caption("SEC XBRL facts are reported values, not necessarily from the same reporting date or duration. Verify each item in the source filing before relying on ratios.")
        st.markdown("### Extracted financial data")
        df = pd.DataFrame([{"Metric": k, "Latest value (USD)": v, "Approx. USD millions": round(v/1_000_000,2) if v is not None else None} for k,v in vals.items()])
        st.dataframe(df, use_container_width=True, hide_index=True)
        st.markdown("### 2. Recession stress test")
        a,b,c = st.columns(3)
        revenue_drop = a.slider("Revenue decline (%)", 0, 70, 20, 5)
        margin_drop = b.slider("Operating margin decline (percentage points)", 0, 20, 3, 1)
        collection_delay = c.slider("Extra receivable days", 0, 90, 20, 5)
        st.caption("This first version provides a simplified sensitivity test. It does not yet build a full monthly cash-flow forecast or estimate default probability.")
        revenue = vals["Revenue"]
        cash = vals["Cash and cash equivalents"]
        receivables = vals["Receivables"]
        liabilities = vals["Current liabilities"]
        if revenue is not None and cash is not None:
            lost_revenue = revenue * revenue_drop/100
            extra_wc = (revenue/365) * collection_delay
            stressed_cash = cash - extra_wc
            st.metric("Illustrative cash after extra collection delay", fmt(stressed_cash), delta=fmt(-extra_wc) + " vs reported cash", delta_color="inverse")
            st.write(f"Revenue shock assumption: **{revenue_drop}%**. This is not the same as a cash loss; the actual impact depends on variable costs, margins, collections and management actions.")
            if stressed_cash < 0:
                st.error("The simplified sensitivity indicates a potential cash pressure. This is not a conclusion that the company will fail.")
            elif liabilities and stressed_cash < liabilities:
                st.warning("Stressed cash is below reported current liabilities. Current liabilities are not all immediately payable, so this is a screening flag, not a failure prediction.")
            else:
                st.success("No immediate cash shortfall indicated by this simplified test. This does not establish recession survival.")
        else:
            st.info("Revenue or cash data was not found in the selected SEC facts. Upload financial statements below for manual review.")
        st.markdown("### 3. Original SEC source")
        st.link_button("Open SEC company filings", f"https://www.sec.gov/edgar/browse/?CIK={company['cik']}&owner=exclude")
    except Exception as e:
        st.error(f"Could not retrieve or process company facts: {e}")

st.markdown("---")
st.markdown("### 4. Upload a company document")
uploaded = st.file_uploader("Upload an annual report or financial statement (PDF)", type=["pdf"])
if uploaded:
    st.success(f"Document received: {uploaded.name}")
    st.info("In this starter version, uploaded PDFs are not automatically parsed. Use the SEC analysis for supported US issuers, or share the document in ChatGPT for detailed extraction.")

st.markdown("---")
st.caption("Limitations: Free prototype. Initial automated data coverage is US SEC filers only. Indian and other private-company filings are not automatically integrated yet. Data availability varies by company and filing taxonomy. This tool is not investment, lending or credit advice.")
