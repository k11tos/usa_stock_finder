FROM arm32v7/python:3.12-alpine

RUN apk update && \
        apk add --no-cache \
        bash

RUN apk add --update build-base python3-dev py-pip cmake

WORKDIR /py_app

COPY . /py_app

RUN pip install --no-cache-dir -r requirements_common1.txt

ENTRYPOINT [ "python" ]
CMD ["./usa_stock_finder.py"]
