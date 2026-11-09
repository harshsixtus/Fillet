# Fillet - one image for local Docker runs and for Hugging Face Spaces (Docker SDK).
FROM python:3.11-slim

# OpenCascade / VTK (used by CadQuery) need a few system graphics libraries, even headless.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 libglib2.0-0 libxrender1 libxext6 libsm6 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Hugging Face Spaces run containers as user 1000; use the same locally.
RUN useradd -m -u 1000 user
USER user
# Install into a virtual environment, not `pip install --user`: the CAD sandbox runs `python -I`
# (isolated mode), which ignores user site-packages but does include a venv's packages.
ENV HOME=/home/user VIRTUAL_ENV=/home/user/venv PATH=/home/user/venv/bin:$PATH PYTHONUNBUFFERED=1
RUN python -m venv /home/user/venv
WORKDIR /home/user/app

COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=user . .

# Public-demo safety switches (override with env vars / Space secrets).
ENV T2C_SERVER_MODE=1 MAX_BUILDS_PER_HOUR=12
EXPOSE 7860
HEALTHCHECK CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:7860/_stcore/health')"
CMD ["streamlit", "run", "app.py", "--server.port=7860", "--server.address=0.0.0.0", "--server.headless=true"]
