from app import app

client = app.test_client()

with client.session_transaction() as sess:
    sess["user_id"] = 1

response = client.get("/advertise-with-us")
html = response.get_data(as_text=True)

print("STATUS:", response.status_code)
print("CSRF TOKEN FOUND:", 'name="csrf_token"' in html)

position = html.find("csrf_token")

if position >= 0:
    print("\n--- CSRF HTML ---")
    print(html[max(0, position - 150):position + 300])
else:
    print("\nCSRF TOKEN NOT FOUND IN RENDERED HTML")
