FROM public.ecr.aws/lambda/python:3.12

# Install Tesseract
RUN dnf install -y \
    tesseract \
    tesseract-langpack-eng \
    && dnf clean all

WORKDIR ${LAMBDA_TASK_ROOT}

COPY requirements.txt .

RUN pip install \
    --no-cache-dir \
    -r requirements.txt

COPY app ./app

COPY lambda_handler.py .

CMD ["lambda_handler.handler"]