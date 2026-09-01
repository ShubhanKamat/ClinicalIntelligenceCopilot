$env:COPILOT_API_URL = "http://127.0.0.1:8000"

python -m streamlit run `
    ".\ui\streamlit_app.py" `
    --server.port 8501
