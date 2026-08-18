import os
import uuid
import threading
from urllib.parse import urlparse

import requests
from flask import Flask, request, redirect, jsonify, render_template_string, send_from_directory

app = Flask(__name__)

DOWNLOAD_DIR = "/data"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

jobs = {}

HTML = """
<!doctype html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1">
    <title>File Mirror Dashboard</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            max-width: 800px;
            margin: 50px auto;
            padding: 20px;
            background: #f5f5f5;
        }
        .box {
            background: white;
            padding: 25px;
            border-radius: 14px;
            box-shadow: 0 4px 20px #0001;
        }
        input {
            width: 100%;
            box-sizing: border-box;
            padding: 14px;
            margin: 10px 0;
            border: 1px solid #ddd;
            border-radius: 8px;
        }
        button {
            padding: 13px 20px;
            border: 0;
            border-radius: 8px;
            cursor: pointer;
        }
        .result {
            margin-top: 20px;
            padding: 15px;
            background: #eee;
            border-radius: 8px;
            word-break: break-all;
        }
    </style>
</head>
<body>
<div class="box">
    <h2>🚀 File Mirror Dashboard</h2>

    <form method="POST" action="/mirror">
        <input
            name="url"
            type="url"
            placeholder="https://example.com/file.zip"
            required
        >
        <button type="submit">Create Mirror</button>
    </form>

    {% if result %}
        <div class="result">
            {{ result|safe }}
        </div>
    {% endif %}
</div>
</body>
</html>
"""

def download_file(job_id, url):
    try:
        r = requests.get(
            url,
            stream=True,
            timeout=60,
            headers={"User-Agent": "Mozilla/5.0"}
        )
        r.raise_for_status()

        content_type = r.headers.get("Content-Type", "")
        if content_type.startswith("text/html"):
            raise Exception("Remote URL returned an HTML page, not a file.")

        name = os.path.basename(urlparse(url).path) or f"{job_id}.bin"

        safe_name = "".join(
            c for c in name
            if c.isalnum() or c in "._-"
        )

        path = os.path.join(DOWNLOAD_DIR, f"{job_id}-{safe_name}")

        with open(path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)

        jobs[job_id] = {
            "status": "completed",
            "filename": os.path.basename(path)
        }

    except Exception as e:
        jobs[job_id] = {
            "status": "error",
            "error": str(e)
        }


@app.route("/")
def index():
    return render_template_string(HTML)


@app.route("/mirror", methods=["POST"])
def mirror():
    url = request.form.get("url", "").strip()

    if not url.startswith(("http://", "https://")):
        return "Invalid URL", 400

    job_id = uuid.uuid4().hex[:12]

    jobs[job_id] = {
        "status": "downloading"
    }

    threading.Thread(
        target=download_file,
        args=(job_id, url),
        daemon=True
    ).start()

    return redirect(f"/status/{job_id}")


@app.route("/status/<job_id>")
def status(job_id):
    job = jobs.get(job_id)

    if not job:
        return "Job not found", 404

    if job["status"] == "downloading":
        return """
        <h2>Downloading...</h2>
        <p>Refresh this page after a while.</p>
        <meta http-equiv="refresh" content="5">
        """

    if job["status"] == "error":
        return jsonify(job)

    filename = job["filename"]

    return f"""
    <h2>✅ Mirror Ready</h2>
    <p>
        <a href="/files/{filename}">
            Download File
        </a>
    </p>
    <p>Filename: {filename}</p>
    """


@app.route("/files/<path:filename>")
def files(filename):
    return send_from_directory(
        DOWNLOAD_DIR,
        filename,
        as_attachment=True
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
