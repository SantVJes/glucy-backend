-- Usuario de solo lectura para Grafana. Se corre **una vez**, contra la base ya migrada:
--
--   docker compose exec -T base psql -U "$POSTGRES_USER" -d glucy \
--     -v usuario=glucy_lector -v secreto="$GLUCY_GRAFANA_DB_SECRETO" -f - < grafana/lector.sql
--
-- Por qué no es el usuario de la aplicación: el panel acepta consultas escritas a mano en la
-- interfaz, y con un usuario que puede escribir, un `DELETE FROM glucose_readings` queda a una
-- pulsación. Son datos de salud aunque estén seudonimizados, y el teléfono es el dueño del
-- dato (regla 1): esta base es una copia, pero una copia que se borra es una copia perdida.
--
-- `ALTER DEFAULT PRIVILEGES` es la parte que se olvida: sin ella, la tabla que cree la próxima
-- migración no se puede leer y el panel se rompe un mes después, cuando ya nadie recuerda esto.

\set ON_ERROR_STOP on

SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'usuario', :'secreto')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'usuario')
\gexec

SELECT format('ALTER ROLE %I PASSWORD %L', :'usuario', :'secreto')
\gexec

SELECT format('GRANT CONNECT ON DATABASE %I TO %I', current_database(), :'usuario')
\gexec

SELECT format('GRANT USAGE ON SCHEMA public TO %I', :'usuario')
\gexec

SELECT format('GRANT SELECT ON ALL TABLES IN SCHEMA public TO %I', :'usuario')
\gexec

SELECT format(
  'ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO %I', :'usuario'
)
\gexec

-- Y lo que NO se concede, dicho en voz alta: ni INSERT, ni UPDATE, ni DELETE, ni CREATE.
