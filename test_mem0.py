from mem0 import MemoryClient
import os
from dotenv import load_dotenv
load_dotenv()

key = os.getenv("MEM0_API_KEY")
uid = os.getenv("MEM0_USER_ID")
print(f"Connecting to mem0 with user_id: {uid}")

try:
    client = MemoryClient(api_key=key)
    client.add("Debashis Bera is a final-year CSE student looking for AI/ML and software engineering jobs.", user_id=uid)
    mems = client.get_all(filters={"user_id": uid})
    print(f"MEM0: CONNECTED! Memories stored: {len(mems)}")
    for i, m in enumerate(mems[:3]):
        print(f"  [{i}] {m.get('memory', str(m))[:80]}")
except Exception as e:
    print(f"MEM0 ERROR: {e}")
    import traceback
    traceback.print_exc()
