ARG LABKAG_DEPS_IMAGE=labkag-deps:py310
FROM ${LABKAG_DEPS_IMAGE}

WORKDIR /app

COPY app ./app
COPY scripts ./scripts
COPY Readme.md ./Readme.md
COPY docs ./docs

RUN mkdir -p /app/data/uploads /app/data/parsed /app/data/metadata

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
