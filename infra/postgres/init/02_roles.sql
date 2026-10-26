\getenv app_user APP_DB_USER
\getenv app_password APP_DB_PASSWORD
\getenv ro_password GRAFANA_RO_PASSWORD

CREATE ROLE :"app_user" LOGIN PASSWORD :'app_password';
CREATE ROLE grafana_ro LOGIN PASSWORD :'ro_password';

GRANT CONNECT ON DATABASE :"DBNAME" TO :"app_user", grafana_ro;
GRANT USAGE ON SCHEMA public TO :"app_user", grafana_ro;

GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO :"app_user";
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO :"app_user";

GRANT SELECT ON ALL TABLES IN SCHEMA public TO grafana_ro;
