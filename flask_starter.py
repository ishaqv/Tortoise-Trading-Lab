from flask import Flask

app = Flask(__name__)

@app.route("/login/callback")
def callback():
    return "OK"

app.run(host="0.0.0.0", port=8080)
