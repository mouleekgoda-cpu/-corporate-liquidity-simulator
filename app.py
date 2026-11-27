import re
import math
import requests
import pandas as pd
import streamlit as st
import yfinance as yf
from datetime import datetime

st.set_page_config(
    page_title="Corporate Crisis & Liquidity Simulator",
    page_icon="📉",
    layout="wide"
)

st.title("Corporate Crisis & Liquidity Simulator")
st.caption(
    "Enter an Indian listed company name. The app retrieves available public market financials "
    "and runs automated cash-runway scenarios. Free prototype; not investment or credit advice."
)

YAHOO_SEARCH = "https://query1.finance.yahoo.com/v1/finance/search"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"

@st.cache_data(ttl=1800, show_spinner=False)
def search_indian_companies(query: str):
    response = requests.get(
        YAHOO_SEARCH,
        params={"q": query, "quotesCount": 20, "newsCount": 0, "region": "IN", "lang": "en-IN"},
        headers={"User-Agent": USER_AGENT},
        timeout=20
    )
    response.raise_for_status()
    payload = response.json()
    quotes = payload.get("quotes", [])
    found = []
    seen = set()
    for item in quotes:
        symbol = item.get("symbol", "")
        qtype = item.get("quoteType", "")
        if qtype != "EQUITY" or not (symbol.endswith(".NS") or symbol.endswith(".BO")):
            continue
        if symbol in seen:
            continue
        seen.add(symbol)
        found.append({
            "symbol": symbol,
            "name": item.get("longname") or item.get("shortname") or symbol,
            "exchange": item.get("exchDisp") or ("NSE" if symbol.endswith(".NS") else "BSE")
        })
    # Prefer NSE quote when Yahoo returns both NSE and BSE listings.
    found.sort(key=lambda x: (0 if x["symbol"].endswith(".NS") else 1, x["name"].lower()))
    return found[:12]

@st.cache_data(ttl=1800, show_spinner=False)
def get_statements(symbol: str):
    company = yf.Ticker(symbol)
    return {
        "balance_annual": company.balance_sheet,
        "income_annual": company.income_stmt,
        "cashflow_annual": company.cashflow,
        "balance_quarterly": company.quarterly_balance_sheet,
        "income_quarterly": company.quarterly_income_stmt,
        "cashflow_quarterly": company.quarterly_cashflow,
    }

def norm(value):
    return re.sub(r"[^a-z0-9]", "", str(value).lower())

def get_row_value(frame, aliases):
    if frame is None or getattr(frame, "empty", True):
        return None
    rows = {norm(idx): idx for idx in frame.index}
    for alias in aliases:
        key = norm(alias)
        if key in rows:
            series = frame.loc[rows[key]]
            if isinstance(series, pd.DataFrame):
                series = series.iloc[0]
            for value in series.tolist():
                try:
                    number = float(value)
                    if math.isfinite(number):
                        return number
                except (TypeError, ValueError):
                    continue
    return None

def latest_period(frame):
    if frame is None or getattr(frame, "empty", True):
        return "Not available"
    try:
        d = pd.to_datetime(frame.columns[0])
        return d.strftime("%d %b %Y")
    except Exception:
        return str(frame.columns[0])

def crore(value):
    if value is None:
        return "Not available"
    return f"₹{value / 10_000_000:,.2f} Cr"

def get_company_metrics(data):
    # Prefer the latest available quarterly balance sheet for cash/debt/current assets.
    bs_q = data["balance_quarterly"]
    bs_a = data["balance_annual"]
    bs = bs_q if bs_q is not None and not bs_q.empty else bs_a
    income = data["income_annual"]
    cashflow = data["cashflow_annual"]

    metrics = {
        "cash": get_row_value(bs, [
            "Cash Cash Equivalents And Short Term Investments",
            "Cash And Cash Equivalents And Short Term Investments",
            "Cash And Cash Equivalents",
            "Cash",
        ]),
        "current_assets": get_row_value(bs, ["Current Assets", "Total Current Assets"]),
        "current_liabilities": get_row_value(bs, ["Current Liabilities", "Total Current Liabilities"]),
        "total_assets": get_row_value(bs, ["Total Assets"]),
        "total_liabilities": get_row_value(bs, ["Total Liabilities Net Minority Interest", "Total Liabilities"]),
        "inventory": get_row_value(bs, ["Inventory", "Inventory Net"]),
        "receivables": get_row_value(bs, ["Accounts Receivable", "Accounts Receivable Net Current", "Receivables"]),
        "current_debt": get_row_value(bs, [
            "Current Debt And Lease Obligation", "Current Debt",
            "Current Portion Of Long Term Debt", "Short Term Debt"
        ]),
        "long_debt": get_row_value(bs, [
            "Long Term Debt And Lease Obligation", "Long Term Debt",
            "Long Term Debt And Capital Lease Obligation"
        ]),
        "revenue": get_row_value(income, ["Total Revenue", "Operating Revenue", "Revenue"]),
        "cost_of_revenue": get_row_value(income, ["Cost Of Revenue", "Cost Of Goods And Services Sold", "Cost Of Goods Sold"]),
        "operating_income": get_row_value(income, ["Operating Income", "Operating Income Or Loss"]),
        "ebitda": get_row_value(income, ["EBITDA", "Normalized EBITDA"]),
        "operating_cash_flow": get_row_value(cashflow, [
            "Operating Cash Flow", "Cash Flow From Continuing Operating Activities",
            "Cash From Operations", "Total Cash From Operating Activities"
        ]),
        "capex": get_row_value(cashflow, [
            "Capital Expenditure", "Capital Expenditures",
            "Purchase Of Property Plant And Equipment", "Purchase Of PPE"
        ]),
        "interest_expense": get_row_value(income, [
            "Interest Expense Non Operating", "Interest Expense",
            "Interest And Debt Expense"
        ]),
        "balance_period": latest_period(bs),
        "income_period": latest_period(income),
        "cashflow_period": latest_period(cashflow),
    }
    if metrics["capex"] is not None:
        metrics["capex"] = abs(metrics["capex"])
    if metrics["interest_expense"] is not None:
        metrics["interest_expense"] = abs(metrics["interest_expense"])
    return metrics

SCENARIOS = {
    "Base case": {
        "revenue_drop": 0, "input_cost_inflation": 0, "receivable_days": 0,
        "inventory_days": 0, "rate_shock": 0, "disruption_pct": 0,
        "refinance_pct": 100, "capex_cut": 0,
        "description": "No additional crisis shock; historical cash generation continues."
    },
    "Mild recession": {
        "revenue_drop": 10, "input_cost_inflation": 3, "receivable_days": 10,
        "inventory_days": 5, "rate_shock": 0.5, "disruption_pct": 0.2,
        "refinance_pct": 80, "capex_cut": 15,
        "description": "Lower demand, modest cost pressure and slower collections."
    },
    "Severe recession": {
        "revenue_drop": 25, "input_cost_inflation": 7, "receivable_days": 25,
        "inventory_days": 15, "rate_shock": 1.5, "disruption_pct": 0.7,
        "refinance_pct": 50, "capex_cut": 30,
        "description": "Sharp demand contraction, margin pressure and tighter credit."
    },
    "Geopolitical war": {
        "revenue_drop": 30, "input_cost_inflation": 15, "receivable_days": 30,
        "inventory_days": 25, "rate_shock": 2.0, "disruption_pct": 2.0,
        "refinance_pct": 40, "capex_cut": 40,
        "description": "Export/logistics disruption, commodity inflation and weaker refinancing."
    },
    "Domestic civil conflict / unrest": {
        "revenue_drop": 35, "input_cost_inflation": 10, "receivable_days": 35,
        "inventory_days": 20, "rate_shock": 1.5, "disruption_pct": 2.5,
        "refinance_pct": 35, "capex_cut": 45,
        "description": "Business interruption, delayed collections, distribution disruption and tighter funding."
    },
    "Supply-chain blockade": {
        "revenue_drop": 20, "input_cost_inflation": 20, "receivable_days": 15,
        "inventory_days": 40, "rate_shock": 1.0, "disruption_pct": 1.5,
        "refinance_pct": 45, "capex_cut": 35,
        "description": "Input shortages, higher procurement costs, inventory build-up and delayed deliveries."
    },
    "Credit freeze": {
        "revenue_drop": 20, "input_cost_inflation": 5, "receivable_days": 25,
        "inventory_days": 10, "rate_shock": 3.0, "disruption_pct": 0.5,
        "refinance_pct": 0, "capex_cut": 40,
        "description": "Short-term debt cannot be rolled over and financing costs increase."
    },
    "Combined extreme crisis": {
        "revenue_drop": 50, "input_cost_inflation": 25, "receivable_days": 50,
        "inventory_days": 45, "rate_shock": 4.0, "disruption_pct": 4.0,
        "refinance_pct": 0, "capex_cut": 60,
        "description": "Severe simultaneous demand, input-cost, working-capital and refinancing shocks."
    },
}

def simulate(metrics, assumptions, months=36):
    cash = metrics["cash"]
    revenue = metrics["revenue"]
    cfo = metrics["operating_cash_flow"]
    capex = metrics["capex"] or 0
    cogs = metrics["cost_of_revenue"]
    current_debt = metrics["current_debt"] or 0
    long_debt = metrics["long_debt"] or 0

    required = [cash, revenue, cfo]
    if any(v is None for v in required):
        return None

    # Estimates are explicit and conservative; no undisclosed credit lines are assumed.
    cogs = cogs if cogs is not None else revenue * 0.65
    variable_cost_ratio = min(0.95, max(0.20, cogs / revenue)) if revenue > 0 else 0.65
    contribution_margin = 1 - variable_cost_ratio
    annual_debt = current_debt + long_debt
    floating_share_assumption = 0.50

    monthly_revenue = revenue / 12
    monthly_cogs = cogs / 12
    monthly_cfo = cfo / 12
    monthly_capex = capex / 12 * (1 - assumptions["capex_cut"] / 100)

    extra_receivables = revenue / 365 * 0.70 * assumptions["receivable_days"]
    extra_inventory = cogs / 365 * assumptions["inventory_days"]
    one_off_working_capital = extra_receivables + extra_inventory

    monthly_sales_loss_cash = monthly_revenue * (assumptions["revenue_drop"] / 100) * contribution_margin
    monthly_input_cost_shock = monthly_cogs * (assumptions["input_cost_inflation"] / 100)
    monthly_disruption_cost = revenue * (assumptions["disruption_pct"] / 100) / 12
    annual_interest_shock = annual_debt * floating_share_assumption * (assumptions["rate_shock"] / 100)
    monthly_interest_shock = annual_interest_shock / 12

    non_refinanced_current_debt = current_debt * (1 - assumptions["refinance_pct"] / 100)
    monthly_principal = non_refinanced_current_debt / 12

    rows = []
    balance = cash
    first_negative = None
    for month in range(1, months + 1):
        wc_outflow = one_off_working_capital if month == 1 else 0
        operating_cash = monthly_cfo - monthly_sales_loss_cash - monthly_input_cost_shock - monthly_disruption_cost
        principal_outflow = monthly_principal if month <= 12 else 0
        net_change = operating_cash - monthly_capex - monthly_interest_shock - principal_outflow - wc_outflow
        opening = balance
        balance += net_change
        if balance < 0 and first_negative is None:
            first_negative = month
        rows.append({
            "Month": month,
            "Opening cash (₹ Cr)": opening / 10_000_000,
            "Net cash movement (₹ Cr)": net_change / 10_000_000,
            "Closing cash (₹ Cr)": balance / 10_000_000,
        })

    return {
        "rows": pd.DataFrame(rows),
        "months_to_exhaustion": first_negative,
        "ending_cash": balance,
        "minimum_cash": min(r["Closing cash (₹ Cr)"] for r in rows) * 10_000_000,
        "working_capital_shock": one_off_working_capital,
        "monthly_burn": max(0, -(
            monthly_cfo - monthly_sales_loss_cash - monthly_input_cost_shock - monthly_disruption_cost
            - monthly_capex - monthly_interest_shock - monthly_principal
        )),
        "assumptions": assumptions,
        "estimated_variable_cost_ratio": variable_cost_ratio,
    }

def risk_label(result):
    if result is None:
        return "Insufficient data"
    m = result["months_to_exhaustion"]
    if m is None:
        return "No cash exhaustion within 36 months"
    if m <= 6:
        return "Critical cash risk"
    if m <= 12:
        return "High cash risk"
    if m <= 24:
        return "Elevated cash risk"
    return "Cash exhaustion after 24 months"

# Single required user input
company_query = st.text_input(
    "Enter Indian company name",
    placeholder="Example: Reliance Industries, Tata Motors, Infosys",
    key="company_query"
)

if st.button("Analyse company and run crisis simulations", type="primary", use_container_width=True):
    if not company_query.strip():
        st.warning("Enter a company name.")
    else:
        st.session_state.pop("company_choice", None)
        st.session_state.pop("company_matches", None)
        try:
            with st.spinner("Searching Indian listed companies..."):
                matches = search_indian_companies(company_query.strip())
            if not matches:
                st.error(
                    "No matching Indian NSE/BSE-listed company was found in the free search source. "
                    "The company may be private, unlisted, newly listed, or unavailable through this data provider."
                )
                st.markdown(
                    "[Search NSE financial results](https://www.nseindia.com/companies-listing/corporate-filings-financial-results) · "
                    "[Search NSE annual reports](https://www.nseindia.com/companies-listing/corporate-filings-annual-reports) · "
                    "[Search BSE corporate filings](https://www.bseindia.com/corporates.html)"
                )
            elif len(matches) == 1:
                st.session_state["company_choice"] = matches[0]
            else:
                # Automatically prefer a close name match, but retain a selector if names are ambiguous.
                exact = [m for m in matches if company_query.strip().lower() in m["name"].lower()]
                st.session_state["company_matches"] = matches
                st.session_state["suggested_match"] = exact[0]["symbol"] if exact else matches[0]["symbol"]
        except Exception as exc:
            st.error(f"Company search failed: {exc}")

if "company_matches" in st.session_state:
    matches = st.session_state["company_matches"]
    options = [m["symbol"] for m in matches]
    name_by_symbol = {m["symbol"]: m for m in matches}
    default_index = options.index(st.session_state.get("suggested_match", options[0]))
    selected_symbol = st.selectbox(
        "Select the correct company (only when search returns similar names)",
        options,
        index=default_index,
        format_func=lambda s: f"{name_by_symbol[s]['name']} — {name_by_symbol[s]['symbol']}"
    )
    if st.button("Confirm company"):
        st.session_state["company_choice"] = name_by_symbol[selected_symbol]

if "company_choice" in st.session_state:
    selected = st.session_state["company_choice"]
    symbol = selected["symbol"]
    st.markdown("---")
    st.subheader(f"{selected['name']}  ·  {symbol}")
    st.caption(f"Exchange: {selected['exchange']} · Data provider: Yahoo Finance public financial statements")

    try:
        with st.spinner("Retrieving latest available financial statements and calculating scenarios..."):
            statements = get_statements(symbol)
            metrics = get_company_metrics(statements)

        # Data quality and reporting periods
        required_for_model = ["cash", "revenue", "operating_cash_flow"]
        missing = [k for k in required_for_model if metrics.get(k) is None]
        st.markdown("### Financial data retrieved automatically")
        p1, p2, p3 = st.columns(3)
        p1.metric("Cash & equivalents", crore(metrics["cash"]))
        p2.metric("Annual revenue", crore(metrics["revenue"]))
        p3.metric("Annual operating cash flow", crore(metrics["operating_cash_flow"]))

        q1, q2, q3 = st.columns(3)
        current_ratio = (
            metrics["current_assets"] / metrics["current_liabilities"]
            if metrics["current_assets"] is not None and metrics["current_liabilities"] not in (None, 0) else None
        )
        cash_ratio = (
            metrics["cash"] / metrics["current_liabilities"]
            if metrics["cash"] is not None and metrics["current_liabilities"] not in (None, 0) else None
        )
        total_debt = (metrics["current_debt"] or 0) + (metrics["long_debt"] or 0)
        q1.metric("Current ratio", f"{current_ratio:.2f}x" if current_ratio is not None else "Not available")
        q2.metric("Cash ratio", f"{cash_ratio:.2f}x" if cash_ratio is not None else "Not available")
        q3.metric("Reported debt (identified)", crore(total_debt))

        st.caption(
            f"Balance sheet period: {metrics['balance_period']} · "
            f"Income statement period: {metrics['income_period']} · "
            f"Cash-flow period: {metrics['cashflow_period']}"
        )

        detail_rows = [
            ("Cash and equivalents", metrics["cash"]),
            ("Current assets", metrics["current_assets"]),
            ("Current liabilities", metrics["current_liabilities"]),
            ("Receivables", metrics["receivables"]),
            ("Inventory", metrics["inventory"]),
            ("Current debt", metrics["current_debt"]),
            ("Long-term debt", metrics["long_debt"]),
            ("Revenue", metrics["revenue"]),
            ("Cost of revenue", metrics["cost_of_revenue"]),
            ("Operating income", metrics["operating_income"]),
            ("EBITDA", metrics["ebitda"]),
            ("Operating cash flow", metrics["operating_cash_flow"]),
            ("Capital expenditure", metrics["capex"]),
            ("Interest expense", metrics["interest_expense"]),
        ]
        detail = pd.DataFrame([
            {"Financial item": label, "Value (₹ crore)": round(value / 10_000_000, 2) if value is not None else None}
            for label, value in detail_rows
        ])
        with st.expander("See all extracted financial figures"):
            st.dataframe(detail, use_container_width=True, hide_index=True)

        st.markdown("### Crisis survival simulation")
        if missing:
            st.error(
                "Insufficient financial data for a responsible runway forecast. Missing: "
                + ", ".join(missing)
                + ". No survival conclusion has been generated."
            )
        else:
            results = {}
            summary_rows = []
            for scenario_name, assumptions in SCENARIOS.items():
                result = simulate(metrics, assumptions)
                results[scenario_name] = result
                if result["months_to_exhaustion"] is None:
                    runway_text = ">36 months"
                else:
                    runway_text = f"{result['months_to_exhaustion']} months"
                summary_rows.append({
                    "Scenario": scenario_name,
                    "Cash runway": runway_text,
                    "Minimum projected cash": crore(result["minimum_cash"]),
                    "Cash after 36 months": crore(result["ending_cash"]),
                    "Assessment": risk_label(result)
                })

            summary_df = pd.DataFrame(summary_rows)
            st.dataframe(summary_df, use_container_width=True, hide_index=True)

            st.markdown("### How long can the company continue?")
            cols = st.columns(3)
            focus_names = ["Severe recession", "Geopolitical war", "Combined extreme crisis"]
            for i, scenario_name in enumerate(focus_names):
                result = results[scenario_name]
                if result["months_to_exhaustion"] is None:
                    runway = ">36 months"
                else:
                    runway = f"{result['months_to_exhaustion']} months"
                cols[i].metric(scenario_name, runway, risk_label(result))

            selected_scenario = st.selectbox("View monthly cash forecast", list(SCENARIOS.keys()), index=7)
            forecast = results[selected_scenario]["rows"].copy()
            st.line_chart(forecast.set_index("Month")[["Closing cash (₹ Cr)"]])
            st.dataframe(forecast, use_container_width=True, hide_index=True)

            st.markdown("### What the model assumed")
            assumption = SCENARIOS[selected_scenario]
            st.write(assumption["description"])
            a1, a2, a3, a4 = st.columns(4)
            a1.metric("Revenue decline", f"{assumption['revenue_drop']}%")
            a2.metric("Input-cost inflation", f"{assumption['input_cost_inflation']}%")
            a3.metric("Extra collection delay", f"{assumption['receivable_days']} days")
            a4.metric("Inventory days increase", f"{assumption['inventory_days']} days")
            a5, a6, a7, a8 = st.columns(4)
            a5.metric("Interest-rate shock", f"+{assumption['rate_shock']} pp")
            a6.metric("Disruption cost", f"{assumption['disruption_pct']}% of annual revenue")
            a7.metric("Short-term debt refinanced", f"{assumption['refinance_pct']}%")
            a8.metric("Capex reduction assumed", f"{assumption['capex_cut']}%")

            with st.expander("Important modelling limitations — read before relying on the result"):
                st.markdown(
                    """
                    - This is a deterministic scenario model, not a prediction that a war, recession or civil conflict will occur.
                    - It uses the latest annual cash-flow and income statement data available from Yahoo Finance, plus the latest available balance sheet.
                    - Historical annual operating cash flow is treated as the starting cash-generation baseline. The model applies estimated revenue, input-cost, disruption and funding shocks.
                    - Receivables are assumed to represent 70% of sales for the incremental collection-delay calculation.
                    - 50% of identified debt is assumed to be floating-rate for interest-rate shock calculations.
                    - Current debt is assumed to fall due across the next 12 months; long-term debt maturities are not available in this simplified model.
                    - Undrawn bank facilities, restricted cash, guarantees, covenants, detailed debt maturity schedules, asset sales, management actions and subsidiary cash restrictions are not reliably captured.
                    - The output is cash exhaustion under stated assumptions, not a legal insolvency opinion or a guarantee of survival.
                    - Financial data provider coverage can be incomplete or delayed. Verify with the company's official filings before making decisions.
                    """
                )

        yahoo_url = f"https://finance.yahoo.com/quote/{symbol}/financials/"
        st.markdown("### Verify against original filings")
        st.markdown(
            f"- [Yahoo Finance financial statements]({yahoo_url})  \n"
            f"- [NSE financial results](https://www.nseindia.com/companies-listing/corporate-filings-financial-results)  \n"
            f"- [NSE annual reports](https://www.nseindia.com/companies-listing/corporate-filings-annual-reports)  \n"
            f"- [BSE corporate filings](https://www.bseindia.com/corporates.html)"
        )

    except Exception as exc:
        st.error(
            f"Financial statements could not be retrieved for {symbol}: {exc}. "
            "The source may be temporarily rate-limited or may not publish usable financial statements."
        )

st.markdown("---")
st.caption(
    "Coverage: Indian NSE/BSE-listed companies with financial data available from Yahoo Finance. "
    "Private/unlisted companies and some smaller listed companies may not have sufficient free structured data. "
    "No paid API or AI key is used. Data retrieval depends on a third-party public data source."
)
