"""
Two patches applied at Docker build time:

1. config_json_str — chromadb crashes on empty '{}' config.
   Sets the correct default CollectionConfigurationInternal JSON.

2. index_metadata.pickle — pickles were stored as plain dicts (old chromadb).
   Current chromadb expects PersistentData class instances (.dimensionality etc).
   Converts all dict-based pickles to PersistentData instances.
"""
import os
import pickle
import sqlite3
import json

#  Patch 1: config_json_str 
from chromadb.api.configuration import CollectionConfigurationInternal

DB_PATH = "data/chromadb/chroma.sqlite3"
config_str = json.dumps(CollectionConfigurationInternal().to_json())

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()
cur.execute("SELECT name, config_json_str FROM collections")
for name, existing in cur.fetchall():
    if not existing or existing.strip() in ("{}", "null", ""):
        cur.execute(
            "UPDATE collections SET config_json_str = ? WHERE name = ?",
            (config_str, name),
        )
        print(f"[config] patched: {name}")
    else:
        print(f"[config] ok: {name}")
conn.commit()
conn.close()

#  Patch 2: index_metadata.pickle 
from chromadb.segment.impl.vector.local_persistent_hnsw import PersistentData

CHROMA_DIR = "data/chromadb"

for entry in os.listdir(CHROMA_DIR):
    pickle_path = os.path.join(CHROMA_DIR, entry, "index_metadata.pickle")
    if not os.path.isfile(pickle_path):
        continue

    with open(pickle_path, "rb") as f:
        data = pickle.load(f)

    if isinstance(data, dict):
        # Convert dict → PersistentData instance
        obj = PersistentData(
            dimensionality=data.get("dimensionality") or 384,  # all-MiniLM-L6-v2 = 384
            total_elements_added=data.get("total_elements_added", 0),
            id_to_label=data.get("id_to_label", {}),
            label_to_id=data.get("label_to_id", {}),
            id_to_seq_id=data.get("id_to_seq_id", {}),
        )
        with open(pickle_path, "wb") as f:
            pickle.dump(obj, f, pickle.HIGHEST_PROTOCOL)
        print(f"[pickle] converted dict→PersistentData: {entry}")
    else:
        print(f"[pickle] already PersistentData: {entry}")

print("All patches applied.")
