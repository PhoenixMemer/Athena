import sqlite3

def merge_databases():
    # Make sure these filenames match exactly what is in your folder!
    source_db = 'modsVSC.db'
    dest_db = 'mods.db'

    print(f"🔄 Connecting to {source_db} and {dest_db}...")
    src_conn = sqlite3.connect(source_db)
    src_cursor = src_conn.cursor()

    dest_conn = sqlite3.connect(dest_db)
    dest_cursor = dest_conn.cursor()

    # --- 1. MERGE PROFILES ---
    print("🛡️ Merging mod_profiles...")
    try:
        src_cursor.execute("SELECT user_id, rank, loa, training_score, training_completed, warnings, commendations FROM mod_profiles")
        profiles = src_cursor.fetchall()
        
        added_profiles = 0
        for profile in profiles:
            # INSERT OR IGNORE ensures we don't overwrite someone's existing stats in the main DB
            dest_cursor.execute('''
                INSERT OR IGNORE INTO mod_profiles 
                (user_id, rank, loa, training_score, training_completed, warnings, commendations)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', profile)
            
            # Check if a new row was actually added
            if dest_cursor.rowcount > 0:
                added_profiles += 1
                
        print(f"✅ Successfully added {added_profiles} missing profiles to the main database.")
    except Exception as e:
        print(f"⚠️ Error merging profiles: {e}")

    # --- 2. MERGE STRIKES ---
    print("⚔️ Merging mod_strikes...")
    try:
        src_cursor.execute("SELECT user_id, reason, timestamp FROM mod_strikes")
        strikes = src_cursor.fetchall()
        
        added_strikes = 0
        for strike in strikes:
            user_id, reason, timestamp = strike
            
            # Check if this exact strike already exists to prevent double-striking someone
            dest_cursor.execute('''
                SELECT 1 FROM mod_strikes 
                WHERE user_id = ? AND reason = ? AND timestamp = ?
            ''', (user_id, reason, timestamp))
            
            if not dest_cursor.fetchone():
                # We leave 'id' out of the insert so the destination database generates a safe, new ID
                dest_cursor.execute('''
                    INSERT INTO mod_strikes (user_id, reason, timestamp)
                    VALUES (?, ?, ?)
                ''', (user_id, reason, timestamp))
                added_strikes += 1
                
        print(f"✅ Successfully added {added_strikes} missing strikes to the main database.")
    except Exception as e:
        print(f"⚠️ Error merging strikes: {e}")

    # --- FINISH ---
    dest_conn.commit()
    src_conn.close()
    dest_conn.close()
    print("🎉 Merge complete! Your mods.db file is now fully updated.")

if __name__ == "__main__":
    merge_databases()