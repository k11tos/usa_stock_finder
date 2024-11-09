FROM python:3.12-alpine

RUN apk update && \
        apk add --no-cache \
        bash

WORKDIR /py_app

COPY . /py_app

RUN pip install --no-cache-dir -r requirements.txt

ENTRYPOINT [ "python" ]
CMD ["./usa_stock_finder.py"]
