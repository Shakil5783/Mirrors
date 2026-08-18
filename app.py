import os
import time
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

# 0 = unlimited
MAX_DOWNLOAD_MBPS = float(
    os.environ.get("MAX_DOWNLOAD_MBPS", "0")
)

HTML = """
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport"
      content="width=device-width,initial-scale=1">

<title>Cloud Mirror Dashboard</title>

<style>
* {
    box-sizing: border-box;
}

body {
    margin: 0;
    padding: 25px 15px;
    font-family: Arial,sans-serif;
    background: #0f172a;
    color: #e5e7eb;
}

.container {
    max-width: 780px;
    margin: auto;
}

.card {
    background: #1e293b;
    padding: 25px;
    border-radius: 16px;
    box-shadow: 0 10px 40px #0005;
}

h1 {
    margin-top: 0;
}

input {
    width: 100%;
    padding: 14px;
    margin: 10px 0;
    border-radius: 9px;
    border: 1px solid #475569;
    background: #0f172a;
    color: white;
}

button {
    width: 100%;
    padding: 14px;
    border: 0;
    border-radius: 9px;
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
    padding: 18px;
    background: #0f172a;
    border-radius: 10px;
    word-break: break-all;
}

.progress {
    width: 100%;
    height: 22px;
    background: #334155;
    border-radius: 20px;
    overflow: hidden;
    margin: 15px 0;
}

.bar {
    height: 100%;
    width: 0%;
    background: #22c55e;
    transition: width .3s;
}

.stats {
    display: grid;
    grid-template-columns: repeat(2,1fr);
    gap: 10px;
    margin-top: 15px;
}

.stat {
    background: #1e293b;
    padding: 12px;
    border-radius: 8px;
}

.label {
    color: #94a3b8;
    font-size: 12px;
}

.value {
    font-size: 17px;
    font-weight: bold;
    margin-top: 4px;
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
Remote URL → Mirror → Direct Download
</p>

<form method="POST" action="/mirror">

<input
 name="url"
 type="url"
 placeholder="https://example.com/file.zip"
 required>

<button type="submit">
Create Mirror
</button>

</form>

</div>
</div>

</body>
</html>
"""


def public_host(hostname):

    if not hostname:
        return False

    hostname = hostname.lower().rstrip(".")

    blocked = {
        "localhost",
        "localhost.localdomain",
        "metadata.google.internal",
        "instance-data",
    }

    if hostname in blocked:
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

        if parsed.scheme not in (
            "http",
            "https"
        ):
            return False, "Only HTTP/HTTPS URLs are allowed."

        if not public_host(parsed.hostname):
            return False, "Private/internal URL blocked."

        return True, ""

    except Exception:

        return False, "Invalid URL."


def filename_from_url(url, job_id):

    name = os.path.basename(
        urlparse(url).path
    )

    if not name:
        name = f"download-{job_id}.bin"

    safe = "".join(
        c for c in name
        if c.isalnum() or c in "._-"
    )

    if not safe:
        safe = f"download-{job_id}.bin"

    return safe


def download_file(job_id, url):

    try:

        valid, error = validate_url(url)

        if not valid:
            raise Exception(error)

        jobs[job_id] = {
            "status": "connecting",
            "progress": 0,
            "downloaded": 0,
            "total": 0,
            "speed": 0,
            "eta": 0,
        }

        response = requests.get(
            url,
            stream=True,
            timeout=(20, 60),
            allow_redirects=True,
            headers={
                "User-Agent": "CloudMirror/1.0"
            },
        )

        response.raise_for_status()

        # Validate final redirect
        valid, error = validate_url(
            response.url
        )

        if not valid:
            raise Exception(
                "Redirect destination blocked."
            )

        total = int(
            response.headers.get(
                "Content-Length",
                0
            )
        )

        filename = filename_from_url(
            response.url,
            job_id
        )

        path = os.path.join(
            DATA_DIR,
            f"{job_id}-{filename}"
        )

        downloaded = 0
        started = time.monotonic()
        last_update = started

        jobs[job_id]["status"] = "downloading"
        jobs[job_id]["total"] = total

        with open(path, "wb") as file:

            for chunk in response.iter_content(
                chunk_size=1024 * 1024
            ):

                if not chunk:
                    continue

                # Optional speed limiter
                if MAX_DOWNLOAD_MBPS > 0:

                    target_seconds = (
                        (len(chunk) / 1024 / 1024)
                        / MAX_DOWNLOAD_MBPS
                    )

                    elapsed_chunk = 0

                    if target_seconds > elapsed_chunk:
                        time.sleep(
                            target_seconds
                            - elapsed_chunk
                        )

                file.write(chunk)

                downloaded += len(chunk)

                now = time.monotonic()

                elapsed = max(
                    now - started,
                    0.001
                )

                speed = downloaded / elapsed

                if total > 0:

                    progress = (
                        downloaded * 100 / total
                    )

                    eta = (
                        (total - downloaded)
                        / speed
                        if speed > 0
                        else 0
                    )

                else:

                    progress = 0
                    eta = 0

                # Update roughly every 0.2 sec
                if now - last_update >= 0.2:

                    jobs[job_id].update({
                        "progress": round(
                            progress, 2
                        ),
                        "downloaded": downloaded,
                        "total": total,
                        "speed": speed,
                        "eta": eta,
                    })

                    last_update = now

        jobs[job_id].update({
            "status": "completed",
            "progress": 100,
            "downloaded": downloaded,
            "total": total,
            "speed": downloaded / max(
                time.monotonic() - started,
                0.001
            ),
            "eta": 0,
            "filename": os.path.basename(path),
        })

    except Exception as exc:

        jobs[job_id] = {
            "status": "error",
            "error": str(exc),
        }


@app.route("/")
def dashboard():

    return render_template_string(
        HTML
    )


@app.route("/mirror", methods=["POST"])
def mirror():

    url = request.form.get(
        "url",
        ""
    ).strip()

    valid, error = validate_url(url)

    if not valid:
        return f"""
        <h2>❌ Invalid URL</h2>
        <p>{error}</p>
        <a href="/">Back</a>
        """, 400

    job_id = uuid.uuid4().hex[:12]

    jobs[job_id] = {
        "status": "queued",
        "progress": 0,
    }

    threading.Thread(
        target=download_file,
        args=(job_id, url),
        daemon=True,
    ).start()

    return redirect(
        f"/status/{job_id}"
    )


@app.route("/status/<job_id>")
def status(job_id):

    if job_id not in jobs:
        return "Job not found", 404

    return """
<!doctype html>
<html>
<head>

<meta charset="utf-8">
<meta name="viewport"
      content="width=device-width,initial-scale=1">

<title>Mirror Status</title>

<style>
body {
    font-family: Arial;
    background: #0f172a;
    color: white;
    padding: 25px;
}

.box {
    max-width: 750px;
    margin: auto;
    background: #1e293b;
    padding: 25px;
    border-radius: 15px;
}

.progress {
    height: 24px;
    background: #334155;
    border-radius: 20px;
    overflow: hidden;
}

.bar {
    height: 100%;
    background: #22c55e;
    width: 0%;
}

.stats {
    display: grid;
    grid-template-columns: repeat(2,1fr);
    gap: 10px;
    margin-top: 15px;
}

.stat {
    background: #0f172a;
    padding: 15px;
    border-radius: 8px;
}

a {
    color: #60a5fa;
}
</style>

</head>

<body>

<div class="box">

<h2 id="title">
⏳ Preparing mirror...
</h2>

<div class="progress">
<div class="bar" id="bar"></div>
</div>

<div class="stats">

<div class="stat">
<div>Progress</div>
<strong id="progress">0%</strong>
</div>

<div class="stat">
<div>Speed</div>
<strong id="speed">0 MB/s</strong>
</div>

<div class="stat">
<div>Downloaded</div>
<strong id="downloaded">0 MB</strong>
</div>

<div class="stat">
<div>Total</div>
<strong id="total">Unknown</strong>
</div>

<div class="stat">
<div>ETA</div>
<strong id="eta">--</strong>
</div>

</div>

<div id="result"></div>

</div>

<script>

const jobId = location.pathname.split("/").pop();

function mb(bytes) {
    return (bytes / 1024 / 1024).toFixed(2);
}

function formatETA(seconds) {

    if (!seconds || seconds <= 0)
        return "--";

    seconds = Math.round(seconds);

    const h = Math.floor(seconds / 3600);
    const m = Math.floor(
        (seconds % 3600) / 60
    );
    const s = seconds % 60;

    if (h > 0)
        return `${h}h ${m}m ${s}s`;

    if (m > 0)
        return `${m}m ${s}s`;

    return `${s}s`;
}

async function update() {

    try {

        const response =
            await fetch(
                `/api/status/${jobId}`
            );

        const data =
            await response.json();

        if (data.status === "error") {

            document.getElementById(
                "title"
            ).innerText =
                "❌ Download Failed";

            document.getElementById(
                "result"
            ).innerText =
                data.error || "Unknown error";

            return;
        }

        document.getElementById(
            "progress"
        ).innerText =
            `${data.progress || 0}%`;

        document.getElementById(
            "bar"
        ).style.width =
            `${data.progress || 0}%`;

        document.getElementById(
            "speed"
        ).innerText =
            `${mb(data.speed || 0)} MB/s`;

        document.getElementById(
            "downloaded"
        ).innerText =
            `${mb(data.downloaded || 0)} MB`;

        document.getElementById(
            "total"
        ).innerText =
            data.total
                ? `${mb(data.total)} MB`
                : "Unknown";

        document.getElementById(
            "eta"
        ).innerText =
            formatETA(data.eta);

        if (data.status === "completed") {

            document.getElementById(
                "title"
            ).innerText =
                "✅ Mirror Ready";

            const url =
                `${location.origin}/files/${encodeURIComponent(data.filename)}`;

            document.getElementById(
                "result"
            ).innerHTML = `
                <br>
                <p>
                    <a href="${url}">
                        ⬇️ Download File
                    </a>
                </p>

                <input
                    value="${url}"
                    readonly
                    style="
                    width:100%;
                    padding:12px;
                    box-sizing:border-box;
                    "
                >
            `;

            return;
        }

        document.getElementById(
            "title"
        ).innerText =
            "⏳ Downloading...";

        setTimeout(update, 1000);

    } catch (e) {

        setTimeout(update, 2000);
    }
}

update();

</script>

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
        os.environ.get(
            "PORT",
            "8080"
        )
    )

    app.run(
        host="0.0.0.0",
        port=port
    )
