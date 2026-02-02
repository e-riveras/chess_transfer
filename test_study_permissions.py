import os
import requests

token = os.getenv('LICHESS_TOKEN')
if not token:
    print("No token found.")
    exit(1)

headers = {'Authorization': f'Bearer {token}'}
url = "https://lichess.org/api/study"
data = {'name': 'Test Study Permissions', 'visibility': 'private'}

print(f"Attempting to create a private test study...")
resp = requests.post(url, headers=headers, data=data)

print(f"Status Code: {resp.status_code}")
print(f"Response: {resp.text}")

if resp.status_code == 200:
    print("SUCCESS: Token has study:write permission.")
    # Clean up? We could delete it if we parse the ID, but it's private and harmless.
    study_id = resp.json().get('id')
    print(f"Created Study ID: {study_id}")
    # delete it
    requests.delete(f"https://lichess.org/api/study/{study_id}", headers=headers)
    print("Test study deleted.")
else:
    print("FAILURE: Token likely missing study:write permission.")
