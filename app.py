import os
import uuid
import socket
import ipaddress
import threading
from urllib.parse import urlparse

import requests
from flask import (
    Flask,
    request,
    redirect,
    jsonify,
    render_template_string,
    send_from_directory,
)

app = Flask(__name__)

DATA_DIR = "/data"
os.makedirs(DATA_DIR, exist_ok=True)

jobs = {}
MAX_REDIRECTS = 5


HTML = """
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">

<title>Cloud Mirror Dashboard</title>

<style>
* {
    box-sizing: border-box;
}

body {
    margin: 0;
    padding: 30px 15px;
    font-family: Arial, sans-serif;
    background: #0f172a;
    color: #e5e7eb;
}

.container {
    max-width: 760px;
    margin: auto;
}

.card {
    background: #1e293b;
    padding: 25px;
    border-radius: 16px;
    box-shadow: 0 10px 40px rgba(0,0,0,.3);
}

h1 {
    margin-top: 0;
}

input {
    width: 100%;
    padding: 14px;
    margin: 10px 0;
    border-radius: 10px;
    border: 1px solid #475569;
    background: #0f172a;
    color: white;
}

button {
    width: 100%;
    padding: 14px;
    border: 0;
    border-radius: 10px;
    cursor: pointer;
    font-weight: bold;
    background: #2563eb;
    color: white;
}

button:hover {
    background: #1d4ed8;
}

.box {
    margin-top: 20px;
    padding: 15px;
    background: #0f172a;
    border-radius: 10px;
    word-break: break-all;
}

a {
    color: #60a5fa;
}

.small {
    color: #94a3b8;
    font-size: 13px;
}
</style>
</head>

<body>

<div class="container">

<div class="card">

<h1>🚀 Cloud File Mirror</h1>

<p class="small">
Paste a direct URL to a file you are authorized to mirror.
</p>

<form method="POST" action="/mirror">

<input
    name="url"
    type="url"
    placeholder="https://example.com/file.zip"
    required
>

<button type="submit">
Create Mirror
</button>

</form>

{% if result %}
<div class="box">
{{ result|safe }}
</div>
{% endif %}

</div>

</div>

</body>
</html>
"""


def is_public_hostname(hostname):
    """
    Prevent requests to localhost, private networks,
    loopback, link-local and cloud metadata addresses.
    """

    if not hostname:
        return False

    hostname = hostname.lower().rstrip(".")

    blocked_names = {
        "localhost",
        "localhost.localdomain",
        "metadata.google.internal",
        "instance-data",
    }

    if hostname in blocked_names:
        return False

    try:
        addresses = socket.getaddrinfo(
            hostname,
            None,
            socket.AF_UNSPEC,
            socket.SOCK_STREAM,
        )
    except socket.gaierror:
        return False

    for item in addresses:
        ip = ipaddress.ip_address(item[4][0])

        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            return False

    return True


def validate_url(url):
    try:
        parsed = urlparse(url)

        if parsed.scheme not in ("http", "https"):
            return False, "Only HTTP/HTTPS URLs are allowed."

        if not parsed.hostname:
            return False, "Invalid hostname."

        if not is_public_hostname(parsed.hostname):
            return False, "Private/internal destinations are blocked."

        return True, ""

    except Exception:
        return False, "Invalid URL."


def get_filename(url, response, job_id):
    name = os.path.basename(urlparse(url).path)

    if not name or name in (".", ".."):
        name = f"download-{job_id}.bin"

    # Remove unsafe characters
    safe = "".join(
        c for c in name
        if c.isalnum() or c in "._-"
    )

    if not safe:
        safe = f"download-{job_id}.bin"

    return safe


def download_file(job_id, url):

    try:

        jobs[job_id] = {
            "status": "connecting",
            "progress": 0,
            "downloaded": 0,
            "total": 0,
        }

        valid, error = validate_url(url)

        if not valid:
            raise Exception(error)

        session = requests.Session()

        response = session.get(
            url,
            stream=True,
            timeout=(20, 60),
            allow_redirects=True,
            headers={
                "User-Agent": "CloudMirror/1.0"
            },
        )

        response.raise_for_status()

        # Validate final redirected destination
        final_url = response.url

        valid, error = validate_url(final_url)

        if not valid:
            raise Exception(
                "Redirected to a private/internal destination."
            )

        total = int(
            response.headers.get("Content-Length", 0)
        )

        filename = get_filename(
            final_url,
            response,
            job_id
        )

        final_path = os.path.join(
            DATA_DIR,
            f"{job_id}-{filename}"
        )

        downloaded = 0

        jobs[job_id]["status"] = "downloading"
        jobs[job_id]["total"] = total

        with open(final_path, "wb") as file:

            for chunk in response.iter_content(
                chunk_size=1024 * 1024
            ):

                if not chunk:
                    continue

                file.write(chunk)

                downloaded += len(chunk)

                progress = (
                    int(downloaded * 100 / total)
                    if total > 0
                    else 0
                )

                jobs[job_id].update({
                    "progress": progress,
                    "downloaded": downloaded,
                })

        jobs[job_id].update({
            "status": "completed",
            "progress": 100,
            "filename": os.path.basename(final_path),
        })

    except Exception as exc:

        jobs[job_id] = {
            "status": "error",
            "error": str(exc),
        }


@app.route("/")
def dashboard():

    return render_template_string(
        HTML,
        result=None
    )


@app.route("/mirror", methods=["POST"])
def create_mirror():

    url = request.form.get("url", "").strip()

    valid, error = validate_url(url)

    if not valid:

        return render_template_string(
            HTML,
            result=f"<b>Error:</b> {error}"
        ), 400

    job_id = uuid.uuid4().hex[:12]

    jobs[job_id] = {
        "status": "queued",
        "progress": 0,
    }

    thread = threading.Thread(
        target=download_file,
        args=(job_id, url),
        daemon=True,
    )

    thread.start()

    return redirect(
        f"/status/{job_id}"
    )


@app.route("/status/<job_id>")
def status(job_id):

    job = jobs.get(job_id)

    if not job:
        return "Job not found", 404

    status_value = job.get("status")

    if status_value != "completed":

        if status_value == "error":

            return f"""
            <h2>❌ Download Failed</h2>
            <p>{job.get("error", "Unknown error")}</p>
            <p><a href="/">Back</a></p>
            """

        progress = job.get("progress", 0)

        return f"""
        <!doctype html>
        <html>
        <head>
        <meta http-equiv="refresh" content="3">
        </head>
        <body style="font-family:Arial;padding:40px">

        <h2>⏳ Downloading...</h2>

        <p>Status: {status_value}</p>

        <p>Progress: {progress}%</p>

        <progress value="{progress}" max="100"
                  style="width:100%;height:25px">
        </progress>

        <p>
        Downloaded:
        {job.get("downloaded", 0) // 1024 // 1024} MB
        </p>

        </body>
        </html>
        """

    filename = job["filename"]

    # Public mirror URL
    mirror_url = (
        request.host_url.rstrip("/")
        + "/files/"
        + filename
    )

    return f"""
    <!doctype html>
    <html>
    <body style="font-family:Arial;padding:40px">

    <h2>✅ Mirror Ready</h2>

    <p>
    <b>File:</b> {filename}
    </p>

    <p>
    <a href="{mirror_url}">
    Download File
    </a>
    </p>

    <p>
    Mirror URL:
    </p>

    <input
        value="{mirror_url}"
        readonly
        style="width:100%;padding:12px"
    >

    <br><br>

    <a href="/">Create another mirror</a>

    </body>
    </html>
    """


@app.route("/api/status/<job_id>")
def api_status(job_id):

    job = jobs.get(job_id)

    if not job:
        return jsonify({
            "error": "Job not found"
        }), 404

    return jsonify(job)


@app.route("/files/<path:filename>")
def files(filename):

    return send_from_directory(
        DATA_DIR,
        filename,
        as_attachment=True
    )


if __name__ == "__main__":

    port = int(
        os.environ.get("PORT", "8080")
    )

    app.run(
        host="0.0.0.0",
        port=port,
        threaded=True
        )
