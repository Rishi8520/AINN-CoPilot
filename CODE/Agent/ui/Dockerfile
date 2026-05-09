FROM python:3.11-slim

WORKDIR /app

# Install only what the UI needs
RUN pip install --no-cache-dir \
    streamlit==1.35.0 \
    requests==2.31.0 \
    python-dotenv==1.0.1

COPY app.py .

EXPOSE 8501

# Disable Streamlit's telemetry and browser auto-open
CMD ["streamlit", "run", "app.py", \
     "--server.port=8501", \
     "--server.address=0.0.0.0", \
     "--browser.gatherUsageStats=false", \
     "--server.headless=true"]