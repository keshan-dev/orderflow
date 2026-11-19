#!/bin/sh
# Creates 1 database and 1 owner per service, plus a read-only "cdc" user for Debezium.
# Runs once, the first time the postgres volume is created.
set -eu

create_db() {
  db="$1"; user="$2"; password="$3"
  psql -v ON_ERROR_STOP=1 -U postgres -d postgres \
    -v db="$db" -v user="$user" -v password="$password" <<'SQL'
CREATE ROLE :"user" LOGIN PASSWORD :'password';
CREATE DATABASE :"db" OWNER :"user";
GRANT CONNECT ON DATABASE :"db" TO cdc;
SQL
  # Tables are created later by each service's migrations. Default privileges let the
  # cdc user read them, and the service creates the "dbz_outbox" publication itself.
  psql -v ON_ERROR_STOP=1 -U postgres -d "$db" -v user="$user" <<'SQL'
GRANT USAGE ON SCHEMA public TO cdc;
ALTER DEFAULT PRIVILEGES FOR ROLE :"user" IN SCHEMA public GRANT SELECT ON TABLES TO cdc;
SQL
}

psql -v ON_ERROR_STOP=1 -U postgres -d postgres -v password="$CDC_DB_PASSWORD" <<'SQL'
CREATE ROLE cdc LOGIN REPLICATION PASSWORD :'password';
SQL

create_db orders_db orders_user "$ORDERS_DB_PASSWORD"
create_db inventory_db inventory_user "$INVENTORY_DB_PASSWORD"
create_db payments_db payments_user "$PAYMENTS_DB_PASSWORD"
