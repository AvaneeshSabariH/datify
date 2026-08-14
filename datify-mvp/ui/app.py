import streamlit as st
import pandas as pd
import requests
import json
import os
import streamlit.components.v1 as components

# API base URL for FastAPI backend
API_BASE_URL = os.getenv("DATIFY_API_URL", "http://127.0.0.1:8000")

st.set_page_config(
    page_title="Datify MVP - Copilot",
    page_icon="🤖",
    layout="wide"
)

# Custom header styling
st.markdown("""
<style>
    .main-title {
        font-size: 2.5rem;
        font-weight: 700;
        color: #0F172A;
        margin-bottom: 0.5rem;
    }
    .subtitle {
        font-size: 1.1rem;
        color: #64748B;
        margin-bottom: 2rem;
    }
    .badge {
        background-color: #E2E8F0;
        color: #475569;
        padding: 0.2rem 0.6rem;
        border-radius: 0.25rem;
        font-size: 0.85rem;
        font-weight: 500;
    }
</style>
""", unsafe_allow_html=True)

st.markdown('<div class="main-title">🤖 Datify MVP</div>', unsafe_allow_html=True)
st.markdown('<div class="subtitle">Autonomous, privacy-first Data Scientist Copilot (FastAPI + SQLite + Claude 3.5 Sonnet)</div>', unsafe_allow_html=True)

# Session state initialization
if "session_id" not in st.session_state:
    st.session_state.session_id = "mvp_session_1"
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "csv_path" not in st.session_state:
    st.session_state.csv_path = ""

# Sidebar config
with st.sidebar:
    st.header("Settings")
    st.session_state.session_id = st.text_input("Session ID", value=st.session_state.session_id)
    
    # Check if API is running
    try:
        health_resp = requests.get(f"{API_BASE_URL}/health", timeout=2)
        if health_resp.status_code == 200:
            st.markdown('<span class="badge" style="background-color: #DCFCE7; color: #15803D;">● Backend Online</span>', unsafe_allow_html=True)
        else:
            st.markdown('<span class="badge" style="background-color: #FEE2E2; color: #B91C1C;">● Backend Error</span>', unsafe_allow_html=True)
    except Exception:
        st.markdown('<span class="badge" style="background-color: #FEE2E2; color: #B91C1C;">● Backend Offline</span>', unsafe_allow_html=True)
        
    st.markdown("---")
    st.markdown("### How to use:")
    st.write("1. Upload a CSV dataset.")
    st.write("2. Ask Datify to clean, analyze, or visualize data.")
    st.write("3. View executing Python code, changes to CSV, and generated interactive chart.")

# Upload dataset
uploaded_file = st.file_uploader("Upload CSV Dataset", type=["csv"])

if uploaded_file:
    # Save uploaded file locally to a temp path
    temp_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "temp"))
    os.makedirs(temp_dir, exist_ok=True)
    
    # Store standard path
    file_path = os.path.join(temp_dir, uploaded_file.name)
    st.session_state.csv_path = file_path
    
    # Save the file
    with open(file_path, "wb") as f:
        f.write(uploaded_file.getbuffer())
        
    # Read and display preview
    df = pd.read_csv(file_path)
    
    col1, col2 = st.columns([1, 1])
    with col1:
        st.subheader("Dataset Preview")
        st.dataframe(df.head(10), use_container_width=True)
    with col2:
        st.subheader("Dataset Info")
        st.write(f"**Filename:** `{uploaded_file.name}`")
        st.write(f"**Shape:** {df.shape[0]} rows, {df.shape[1]} columns")
        st.write(f"**Local Path:** `{file_path}`")
        
        # Add Rollback / Undo button
        if st.button("⏪ Undo Last Change (Rollback)", use_container_width=True):
            try:
                resp = requests.post(
                    f"{API_BASE_URL}/rollback",
                    json={
                        "file_path": file_path,
                        "session_id": st.session_state.session_id
                    }
                )
                if resp.status_code == 200:
                    st.success("Successfully rolled back to the previous checkpoint!")
                    st.rerun()
                else:
                    st.error(f"Rollback failed: {resp.json().get('detail')}")
            except Exception as e:
                st.error(f"Failed to connect to backend: {e}")

    # Query Input
    st.subheader("Ask Datify Copilot")
    query = st.text_input("Ask a question, request data cleaning, or design a chart:", placeholder="e.g. 'Plot age distribution' or 'Clean null values in Age column'")
    
    if st.button("Send Query", type="primary"):
        if not query:
            st.warning("Please enter a query.")
        else:
            with st.spinner("Analyzing dataset with Claude & running Python code..."):
                try:
                    payload = {
                        "query": query,
                        "file_path": file_path,
                        "session_id": st.session_state.session_id
                    }
                    resp = requests.post(f"{API_BASE_URL}/analyze", json=payload)
                    
                    if resp.status_code == 200:
                        data = resp.json()
                        st.session_state.chat_history.append({
                            "query": query,
                            "status": data.get("status"),
                            "message": data.get("message"),
                            "python_code": data.get("python_code"),
                            "chart_json": data.get("chart_json"),
                            "attempts": data.get("attempts")
                        })
                    else:
                        st.error(f"Error ({resp.status_code}): {resp.json().get('detail', 'Unknown error occurred')}")
                except Exception as e:
                    st.error(f"Failed to communicate with API backend: {e}")

    # Display Query Results History
    if st.session_state.chat_history:
        st.subheader("Execution Output & Visualization")
        latest = st.session_state.chat_history[-1]
        
        c_status = latest["status"]
        if c_status == "success":
            st.success(f"Executed code successfully in {latest['attempts']} attempt(s)!")
        else:
            st.error(f"Execution failed: {latest['message']}")
            
        col_code, col_chart = st.columns([1, 1])
        
        with col_code:
            st.markdown("### Executed Python Code")
            st.code(latest["python_code"], language="python")
            
        with col_chart:
            st.markdown("### Apache ECharts Visualization")
            chart_config = latest["chart_json"]
            
            if chart_config:
                # Embed Apache ECharts via HTML
                echarts_html = f"""
                <!DOCTYPE html>
                <html>
                <head>
                    <meta charset="utf-8">
                    <!-- Import ECharts from CDN -->
                    <script src="https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js"></script>
                </head>
                <body>
                    <div id="chart-container" style="width: 100%; height: 400px;"></div>
                    <script type="text/javascript">
                        var chartDom = document.getElementById('chart-container');
                        var myChart = echarts.init(chartDom);
                        var option = {json.dumps(chart_config)};
                        myChart.setOption(option);
                        
                        // Resize chart on window resize
                        window.addEventListener('resize', function() {{
                            myChart.resize();
                        }});
                    </script>
                </body>
                </html>
                """
                components.html(echarts_html, height=430)
            else:
                st.info("No visualization returned by the agent for this query.")
else:
    st.info("Please upload a CSV file to begin.")
