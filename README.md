# Corporate Liquidity & Recession Stress-Test (Free Starter)

## Run locally
1. Install Python 3.10+.
2. Open a terminal in this folder.
3. Run: `pip install -r requirements.txt`
4. Run: `streamlit run app.py`

## Deploy free
1. Create a GitHub account and a new public repository.
2. Upload `app.py` and `requirements.txt`.
3. Visit https://share.streamlit.io/
4. Sign in with GitHub, select the repository, choose `app.py`, and deploy.

## Current capabilities
- Searches the SEC's public company ticker directory.
- Retrieves SEC companyfacts XBRL data for US filers.
- Calculates basic current, quick and cash ratios where facts are available.
- Runs a simplified receivables-delay cash sensitivity.

## Important limitations
- This is a starter prototype, not a validated credit-risk model.
- SEC XBRL facts may have different reporting dates and durations; verify against filings.
- US SEC public-company data only in this version.
- PDF upload is currently a placeholder, not an automated parser.
- No AI API key is required.
- SEC requests should use a real contact email in the User-Agent before regular use.
