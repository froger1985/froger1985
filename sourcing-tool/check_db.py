import sqlite3
import json

conn = sqlite3.connect("data/sourcing.db")
conn.row_factory = sqlite3.Row

rows = conn.execute(
    "SELECT title, condition, description, extra_images, image_url "
    "FROM source_listings "
    "WHERE source='mercari_likes' AND stock_state != '' "
    "LIMIT 3"
).fetchall()

for r in rows:
    imgs = json.loads(r["extra_images"]) if r["extra_images"] else []
    print("タイトル:", r["title"][:40])
    print("  condition   :", r["condition"])
    print("  description :", repr(r["description"][:80]) if r["description"] else "(空)")
    print("  image_url   :", r["image_url"][:80] if r["image_url"] else "(空)")
    print("  extra_images:", len(imgs), "件 /", imgs[0][:60] if imgs else "(空)")
    print()

conn.close()
