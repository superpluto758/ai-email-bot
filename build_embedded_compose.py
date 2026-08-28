#!/usr/bin/env python3
"""Build a self-contained compose file with bot.py embedded.

Some NAS Docker interfaces only accept a pasted compose file and cannot mount a
local source file. This gzips bot.py, base64-encodes it into an environment
variable, and has the container write it out at startup.

    python3 build_embedded_compose.py > compose-embedded.yml

The payload is wrapped at 100 characters because some compose editors reject
very long lines.
"""

import base64
import gzip
import pathlib
import sys

HERE = pathlib.Path(__file__).parent
SOURCE = HERE / "bot.py"
COMPOSE = HERE / "docker-compose.yml"


def main():
    payload = base64.b64encode(gzip.compress(SOURCE.read_bytes(), 9)).decode()
    wrapped = "\n".join("        " + payload[i:i + 100]
                        for i in range(0, len(payload), 100))

    lines, out = COMPOSE.read_text().splitlines(), []
    for line in lines:
        # Drop the bind mount - the source is embedded instead
        if line.strip() == "- ./bot.py:/app/bot.py:ro":
            continue
        # Replace the startup command with one that unpacks the payload
        if line.strip() == "pip install --quiet --no-cache-dir imapclient":
            out.append("        mkdir -p /app /data")
            out.append("        printf '%s' \"$$BOT_B64\" | tr -d '\\n' "
                       "| base64 -d | gunzip > /app/bot.py")
        out.append(line)
        # Embed the payload as the last environment entry
        if line.strip().startswith("REPLY_DELAY_MAX:"):
            out.append("      BOT_B64: |")
            out.append(wrapped)

    sys.stdout.write("\n".join(out) + "\n")
    print("# embedded %d bytes of source" % len(payload), file=sys.stderr)


if __name__ == "__main__":
    main()
