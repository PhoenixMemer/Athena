import sqlite3

# Connect to your business database
conn = sqlite3.connect("business.db")
cursor = conn.cursor()

try:
    # Run the SQL command to add the column
    cursor.execute("ALTER TABLE business_products ADD COLUMN lifetime_sold INTEGER DEFAULT 0;")
    conn.commit()
    print("✅ Database updated successfully! 'lifetime_sold' column added.")
except sqlite3.OperationalError as e:
    # This catches if you accidentally run it twice
    print(f"⚠️ Note: {e}")
finally:
    conn.close()