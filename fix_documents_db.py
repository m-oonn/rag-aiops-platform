
import sqlite3
import os

DB_PATH = r"e:\闲鱼知识专区\RAG\ragPdfSystem\rag_system.db"

def fix_documents_table():
    if not os.path.exists(DB_PATH):
        print(f"Database {DB_PATH} not found.")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    columns_to_add = [
        ("chunking_config", "TEXT"), # JSON stored as TEXT
    ]

    print("Checking 'knowledge_documents' table schema...")
    try:
        # Get existing columns
        cursor.execute("PRAGMA table_info(knowledge_documents)")
        existing_columns = [row[1] for row in cursor.fetchall()]
        
        for col_name, col_type in columns_to_add:
            if col_name not in existing_columns:
                print(f"Adding column '{col_name}' to 'knowledge_documents' table...")
                try:
                    cursor.execute(f"ALTER TABLE knowledge_documents ADD COLUMN {col_name} {col_type}")
                    print(f"Successfully added '{col_name}'.")
                except sqlite3.OperationalError as e:
                    print(f"Error adding '{col_name}': {e}")
            else:
                print(f"Column '{col_name}' already exists.")
        
        conn.commit()
        print("Database schema update completed.")

    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    fix_documents_table()
