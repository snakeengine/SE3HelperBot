import os, sqlite3, sys, textwrap

DB = os.path.join("data", "shop.db")

def connect():
    if not os.path.exists(DB):
        print("DB not found:", DB); sys.exit(1)
    return sqlite3.connect(DB)

def list_rows():
    con = connect(); cur = con.cursor()
    cur.execute("SELECT id, user_id, platform, url, status, verified_views FROM promo_submissions ORDER BY id ASC")
    rows = cur.fetchall()
    if not rows:
        print("No rows.")
    else:
        for r in rows:
            print(f"id={r[0]} | user_id={r[1]} | platform={r[2]} | status={r[4]} | views={r[5]}")
            print("  url:", r[3])
    con.close()

def show_row(row_id:int):
    con = connect(); cur = con.cursor()
    cur.execute("SELECT id, user_id, platform, url, status, verified_views FROM promo_submissions WHERE id=?", (row_id,))
    r = cur.fetchone()
    if not r:
        print("Not found id", row_id); return
    print(f"id={r[0]} | user_id={r[1]} | platform={r[2]} | status={r[4]} | views={r[5]}")
    print("  url:", r[3])
    con.close()

def update_uid(row_id:int, new_uid:int):
    con = connect(); cur = con.cursor()
    cur.execute("UPDATE promo_submissions SET user_id=? WHERE id=?", (new_uid, row_id))
    con.commit()
    print("OK. Updated user_id for id", row_id, "->", new_uid)
    con.close()

def help_msg():
    print(textwrap.dedent("""\
        Usage:
          python tools\\promo_fix.py list
          python tools\\promo_fix.py show <id>
          python tools\\promo_fix.py update <id> <new_user_id>
    """))

if __name__ == "__main__":
    if len(sys.argv) < 2:
        help_msg(); sys.exit(0)
    cmd = sys.argv[1]
    if cmd == "list":
        list_rows()
    elif cmd == "show" and len(sys.argv) == 3:
        show_row(int(sys.argv[2]))
    elif cmd == "update" and len(sys.argv) == 4:
        update_uid(int(sys.argv[2]), int(sys.argv[3]))
    else:
        help_msg()
