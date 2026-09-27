FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.19 /uv /usr/local/bin/uv

# The venv lives outside /app so the chown below doesn't copy it into a second
# layer, and uv uses this image's Python instead of downloading its own.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# Exactly the versions in uv.lock; --frozen fails the build if it is stale.
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-cache

# Every root module, not a hand-maintained list. The list version silently
# omitted env.py and observability.py — both imported at the top of main.py —
# so the image built fine and then died on `import main` at container start.
# .dockerignore already excludes tests/, eval/, and scripts/.
COPY *.py ./
COPY knowledge/ knowledge/
COPY static/ static/
COPY data/ data/

RUN useradd -m appuser && mkdir -p cache db && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD python -c "import urllib.request,os; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",8000)}/healthz')"

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
