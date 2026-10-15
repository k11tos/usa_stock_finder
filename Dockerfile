FROM python:3.12-slim AS build
WORKDIR /py_app
COPY requirements.txt .
# Optional build-only trust bundle for managed build environments; never baked in.
RUN --mount=type=secret,id=pip_ca_bundle \
    if [ -f /run/secrets/pip_ca_bundle ]; then export PIP_CERT=/run/secrets/pip_ca_bundle; fi; \
    pip install --no-cache-dir -r requirements.txt

FROM python:3.12-slim
WORKDIR /py_app
COPY --from=build /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY . /py_app
# Verify the final runtime layer, including transitive broker/Telegram imports.
# Importing main does not invoke its guarded main() entrypoint or contact APIs.
RUN MPLCONFIGDIR=/tmp/matplotlib python -B -c "import main, broker_equity_snapshot_runner, performance_report_runner; from tools import broker_equity, krw_twr, krw_benchmarks, performance_report; import mojito, requests, telegram; from zoneinfo import ZoneInfo; ZoneInfo('Asia/Seoul')"
ENTRYPOINT [ "python" ]
CMD ["./main.py"]
