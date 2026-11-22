def test_home_redirects_to_frontend(client):
    response = client.get("/", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == "/app/"


def test_frontend_is_served(client):
    response = client.get("/app/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Songly Insights" in response.text


def test_frontend_assets_are_served(client):
    assert client.get("/app/app.js").status_code == 200
    assert client.get("/app/style.css").status_code == 200


def test_missing_asset_uses_error_format(client):
    response = client.get("/app/missing.js")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
