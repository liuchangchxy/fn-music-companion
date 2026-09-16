# All compilation occurs on the NAS. Pinned source trees live in vendor/ and
# are fetched there exactly once before an image build.
FROM rust:1.89-bookworm AS dupsonic-build
WORKDIR /src/dupsonic
COPY vendor/dupsonic/ ./
# The upstream commit ships an out-of-date lockfile. Regenerate it inside this
# reproducible build stage, then enforce that exact resolved graph for compile.
RUN cargo generate-lockfile && cargo build --release --locked

FROM debian:bookworm AS taglib-build
ARG TAGLIB_VERSION=2.1.1
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential ca-certificates cmake curl libutfcpp-dev zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /src
RUN curl -fsSL "https://github.com/taglib/taglib/archive/refs/tags/v${TAGLIB_VERSION}.tar.gz" -o taglib.tar.gz \
    && tar -xzf taglib.tar.gz \
    && cmake -S "taglib-${TAGLIB_VERSION}" -B taglib-build -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/usr/local \
    && cmake --build taglib-build --parallel 2 \
    && cmake --install taglib-build

FROM taglib-build AS ncmdump-build
WORKDIR /src/ncmdump
COPY vendor/ncmdump/ ./
RUN cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DCMAKE_PREFIX_PATH=/usr/local \
    && cmake --build build --parallel 2

FROM debian:bookworm AS metadata-build
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential libjpeg-dev libxml2-dev libxslt1-dev python3 python3-pip python3-venv zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /src
COPY vendor/beets/ ./beets/
COPY vendor/sacad/ ./sacad/
COPY patches/ ./patches/
RUN python3 ./patches/sacad-max-concurrent.py ./sacad/sacad/recurse.py
RUN python3 -m venv /opt/metadata-venv \
    && /opt/metadata-venv/bin/pip install --no-cache-dir ./beets[fetchart,lyrics,embedart] ./sacad \
    && (/opt/metadata-venv/bin/pip install --no-cache-dir zhconv \
        || echo "zhconv unavailable; domestic_provider falls back to its built-in table")

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates ffmpeg jdupes libchromaprint-tools libjpeg62-turbo libxml2 libxslt1.1 python3 tini zlib1g \
    && rm -rf /var/lib/apt/lists/*
COPY --from=taglib-build /usr/local/lib/ /usr/local/lib/
COPY --from=dupsonic-build /src/dupsonic/target/release/dupsonic /usr/local/bin/dupsonic
COPY --from=ncmdump-build /src/ncmdump/build/ncmdump /usr/local/bin/ncmdump
COPY --from=metadata-build /opt/metadata-venv /opt/metadata-venv
COPY app.py pipeline.py domestic_provider.py dashboard.html* *.png *.ico /opt/music-rebuild/
RUN dpkg-query -W -f='${Package}=${Version}\n' ffmpeg jdupes libchromaprint-tools python3 > /opt/music-rebuild/debian-packages.lock \
    && ldconfig \
    && groupadd --system --gid 1001 music \
    && useradd --system --uid 1000 --gid music --create-home music \
    && chmod 755 /opt/music-rebuild/app.py /opt/music-rebuild/pipeline.py /opt/music-rebuild/domestic_provider.py \
    && chmod 644 /opt/music-rebuild/dashboard.html* /opt/music-rebuild/*.png /opt/music-rebuild/*.ico 2>/dev/null || true
ENV PATH="/opt/metadata-venv/bin:${PATH}"
# Running as container root allows seamless read/write on mounted NAS volumes without host privilege escalation
WORKDIR /opt/music-rebuild
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["dupsonic", "--help"]
