import os
import json
import urllib.request
import osmium
import libsql_experimental as libsql

# 1. 北海道OSM PBFのダウンロード
print("1/3: 北海道のOSMデータをダウンロード中...")
pbf_url = "https://download.geofabrik.de/asia/japan/hokkaido-latest.osm.pbf"
urllib.request.urlretrieve(pbf_url, "hokkaido.pbf")

# 2. Turso接続
TURSO_URL = os.environ["TURSO_URL"]
TURSO_TOKEN = os.environ["TURSO_TOKEN"]

print("2/3: Turso データベースへ接続・初期化中...")
conn = libsql.connect(database=TURSO_URL, auth_token=TURSO_TOKEN)
cursor = conn.cursor()

cursor.execute("DROP TABLE IF EXISTS buildings")
cursor.execute("""
CREATE TABLE buildings (
    id INTEGER PRIMARY KEY, name TEXT, height REAL, polygon_json TEXT,
    min_lat REAL, max_lat REAL, min_lon REAL, max_lon REAL
)""")
conn.commit()

# 3. PBF解析とTurso高速書き込み
class HokkaidoUploader(osmium.SimpleHandler):
    def __init__(self, conn):
        super().__init__()
        self.conn = conn
        self.cursor = conn.cursor()
        self.count = 0
        self.batch = []

    def way(self, w):
        if 'building' in w.tags and len(w.nodes) >= 3:
            coords, lats, lons = [], [], []
            for node in w.nodes:
                if node.location.valid():
                    coords.append([node.lon, node.lat])
                    lats.append(node.lat)
                    lons.append(node.lon)

            if len(coords) >= 3:
                height = 12.0
                if 'height' in w.tags:
                    try:
                        height = float(w.tags['height'].replace('m', ''))
                    except ValueError:
                        pass
                elif 'building:levels' in w.tags:
                    try:
                        height = float(w.tags['building:levels']) * 3.5
                    except ValueError:
                        pass

                name = w.tags.get('name', 'Building')
                self.batch.append((
                    w.id, name, height, json.dumps(coords),
                    min(lats), max(lats), min(lons), max(lons)
                ))
                self.count += 1

                # 10,000件ごとにまとめて送信（通信回数を大幅削減）
                if len(self.batch) >= 10000:
                    self.flush()

    def flush(self):
        if self.batch:
            self.cursor.executemany("""
                INSERT OR REPLACE INTO buildings (id, name, height, polygon_json, min_lat, max_lat, min_lon, max_lon)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, self.batch)
            self.conn.commit()
            print(f"  -> 累計 {self.count} 件の建物を送信完了...")
            self.batch = []

print("3/3: データ解析およびTursoへ高速送信中...")
handler = HokkaidoUploader(conn)
handler.apply_file("hokkaido.pbf", locations=True)
handler.flush()

print(f"\n✨ 完了! 合計 {handler.count} 件の北海道データが Turso サーバーに保存されました！")
