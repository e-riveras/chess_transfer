import berserk
import os

token = os.getenv('LICHESS_TOKEN')
session = berserk.TokenSession(token)
client = berserk.Client(session=session)

print(f"Berserk Version: {berserk.__version__}")
print("Client Attributes:")
for attr in dir(client):
    if not attr.startswith('_'):
        print(f" - {attr}")

print("\nIs 'studies' in client?", hasattr(client, 'studies'))
if hasattr(client, 'studies'):
    print("Studies Attributes:")
    print(dir(client.studies))
