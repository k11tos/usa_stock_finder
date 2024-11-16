FROM python:3.12-alpine AS build
WORKDIR /py_app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

FROM python:3.12-alpine
WORKDIR /py_app
COPY --from=build /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY . /py_app
ENTRYPOINT [ "python" ]
CMD ["./main.py"]
