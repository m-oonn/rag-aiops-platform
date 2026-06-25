from src.database.sql_session import engine, Base
from src.database.models import *

print("Creating tables...")
Base.metadata.create_all(bind=engine)
print("Tables created.")
