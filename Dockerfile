FROM python:3.12-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg ca-certificates && rm -rf /var/lib/apt/lists/*
COPY libtag.so.1 /usr/lib/x86_64-linux-gnu/libtag.so.1
COPY ncmdump /usr/local/bin/ncmdump
COPY fpcalc /usr/local/bin/fpcalc
COPY music_pipeline.py /app/music_pipeline.py
RUN chmod +x /usr/local/bin/ncmdump /usr/local/bin/fpcalc
WORKDIR /app
ENTRYPOINT ["python", "/app/music_pipeline.py"]
