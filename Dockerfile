FROM python:3.11-slim-bookworm@sha256:f06d01d4ba3f8ad5af45a3ec87df19c1d317d8e8961edc0fabda61811af6f7cf
COPY --from=ghcr.io/astral-sh/uv:0.12.5@sha256:e85be844203885286c60ffad8a858d48afb6c5a5c237ca0e67f12e74b8f174b1 /uv /uvx /bin/
WORKDIR /app
ENV PYTHONPATH=/app/src \
    PATH=/app/.venv/bin:$PATH \
    HF_HOME=/opt/meridian-model-cache \
    UV_PYTHON_DOWNLOADS=never \
    UV_NO_SYNC=1 \
    PYTHONUNBUFFERED=1
COPY uv.lock pyproject.toml .python-version ./
RUN uv sync --frozen --no-dev --group ui --group maintenance --no-install-project
COPY . .
# Fetch exactly the verified model/tokenizer revision at build time, never at runtime.
RUN python -c "from meridian.agents.policy.retrieval import embed_query; from meridian.agents.policy.chunking import tokenizer; assert len(embed_query('large_transaction')) == 384"
RUN useradd --create-home --uid 10001 meridian && chown -R meridian:meridian /opt/meridian-model-cache
ENV HF_HUB_OFFLINE=1
USER meridian
CMD ["python", "-m", "uvicorn", "meridian.main:app", "--host", "0.0.0.0", "--port", "8000"]
