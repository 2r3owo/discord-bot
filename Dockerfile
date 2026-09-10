FROM brainicism/bgutil-ytdlp-pot-provider:2.0.0-deno

USER root

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-pip python3-venv ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    && python3 -m venv /opt/venv

ENV PATH="/opt/venv/bin:$PATH"
ENV YTDLP_POT_PROVIDER_URL="http://127.0.0.1:4416"

WORKDIR /bot

COPY requirements.txt /bot/requirements.txt
RUN pip install --no-cache-dir -U pip \
    && pip install --no-cache-dir -r /bot/requirements.txt

COPY main.py /bot/main.py
COPY start.sh /bot/start.sh
RUN chmod +x /bot/start.sh

EXPOSE 8080

ENTRYPOINT ["/bot/start.sh"]
