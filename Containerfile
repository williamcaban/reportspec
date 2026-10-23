# ReportSpec reference renderer (DRAFT). Fedora Python base, no network needed at run time.
#
#   podman build -t reportspec .                                  # Python 3.14 on Fedora 43 (default)
#   podman build --build-arg PY=313 -t reportspec:py313 .         # Python 3.13 on Fedora 42
#
#   podman run --rm -v "$PWD/out:/out:Z" reportspec render examples/model-release.report.md \
#       --input examples/inputs/model-release.jsonl --format pdf -o /out/model-release.pdf
#   podman run --rm reportspec conformance conformance
#
# Fonts: the image installs only the fallback families (Liberation, DejaVu). Red Hat Text and Red Hat Mono come
# from src/reportspec/fonts/ and are embedded byte for byte. Fedora's redhat-text-fonts / redhat-mono-fonts packages are NOT
# installed on purpose: they are the same font version (1.030) but OTF files, so with both present the family name
# "Red Hat Text" would resolve to two different files and break determinism (VISUAL-QA.md, VQA-13 and VQA-20).

ARG PY=314
FROM quay.io/fedora/python-${PY}

USER 0
# pango: WeasyPrint text layout. pandoc: optional DOCX export. poppler-utils: pdffonts/pdftotext for the font audit.
RUN dnf -y install --setopt=install_weak_deps=False \
        pango pandoc uv poppler-utils \
        liberation-sans-fonts liberation-mono-fonts dejavu-sans-fonts dejavu-sans-mono-fonts \
    && dnf clean all && rm -rf /var/cache/dnf \
    && fc-cache -f

WORKDIR /opt/app-root/reportspec
COPY --chown=1001:0 . .

# Install the locked dependencies (hash-checked, uv.lock) and the package itself into a virtualenv.
# uv is a build-time tool only: the entrypoint is the installed command, so the container runs offline with a read-only root.
ENV UV_PYTHON_DOWNLOADS=never UV_PYTHON_PREFERENCE=only-system UV_CACHE_DIR=/tmp/uv-cache UV_PROJECT_ENVIRONMENT=/opt/app-root/venv
USER 1001
RUN uv sync --frozen --no-dev --no-editable \
    && rm -rf /tmp/uv-cache \
    && chmod -R g=u /opt/app-root/venv /opt/app-root/reportspec   # OpenShift runs an arbitrary uid in group 0

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
ENTRYPOINT ["/opt/app-root/venv/bin/reportspec"]
CMD ["--help"]
