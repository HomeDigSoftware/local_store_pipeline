store_pipeline:
  outputs:
    dev:
      type: sqlserver
      driver: 'ODBC Driver 17 for SQL Server'
      server: DESKTOP-E7P613O\STORE_DATA
      port: 1433
      database: POS_SANDBOX
      schema: stg
      user: tzaf
      password: '240683'
      threads: 4
      trust_cert: true
    prod:
      dbname: postgres
      host: db.wbppbatntprwjakmyumn.supabase.co
      pass: 0esDq0g6ULubjyyv
      port: 5432
      schema: store_pipeline
      threads: 1
      type: postgres
      user: postgres
  target: dev