FROM python:3.13-slim
# One dependency: a Postgres driver, to seed the database and to read the audit
# table (which no endpoint exposes). Everything else is the standard library.
RUN pip install --no-cache-dir "psycopg[binary]==3.2.*"
WORKDIR /parity
COPY parity.py .
CMD ["python", "parity.py"]
