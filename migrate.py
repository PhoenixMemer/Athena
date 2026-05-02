import sqlite3
import json
import os

def build_core_database():
    print("🚀 Initializing Athena Core Database Upgrade...")
    
    # 1. Create the Master Database
    conn = sqlite3.connect("athena_core.db")
    cursor = conn.cursor()

    # 2. Build the Tables
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS blacklists (
            user_id INTEGER PRIMARY KEY,
            reason TEXT DEFAULT 'No reason provided'
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS cupid_profiles (
            user_id INTEGER PRIMARY KEY,
            name TEXT, age INTEGER, min_age_pref INTEGER, max_age_pref INTEGER,
            gender TEXT, sexuality TEXT, timezone_offset INTEGER, energy TEXT,
            mind_trans BOOLEAN, is_trans BOOLEAN, mind_poly BOOLEAN, is_poly BOOLEAN,
            hobbies_and_likes TEXT, dislikes TEXT, raw_message_link TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS mod_stats (
            user_id INTEGER PRIMARY KEY,
            profile_data TEXT
        )
    ''')
    print("✅ Core tables created.")

    # 3. Migrate blacklist.json
    if os.path.exists("blacklist.json"):
        try:
            with open("blacklist.json", "r") as f:
                data = json.load(f)
                
            # JSONs are usually saved as lists [123, 456] or dicts {"123": "reason"}
            if isinstance(data, list):
                for user_id in data:
                    cursor.execute("INSERT OR IGNORE INTO blacklists (user_id) VALUES (?)", (int(user_id),))
            elif isinstance(data, dict):
                for user_id, reason in data.items():
                    cursor.execute("INSERT OR IGNORE INTO blacklists (user_id, reason) VALUES (?, ?)", (int(user_id), str(reason)))
            
            print(f"✅ Successfully migrated {len(data)} users from blacklist.json to SQLite!")
            
            # Rename the old file so Athena stops trying to use it
            os.rename("blacklist.json", "blacklist_BACKUP.json")
            print("🛡️ Renamed old blacklist.json to prevent conflicts.")
            
        except Exception as e:
            print(f"❌ Error migrating blacklist: {e}")
    else:
        print("⚠️ No blacklist.json found. Skipping migration.")

    conn.commit()
    conn.close()
    print("🎉 Phase 1 Database Migration Complete!")

if __name__ == "__main__":
    build_core_database()