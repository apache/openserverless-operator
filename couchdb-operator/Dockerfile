FROM python:3.11-slim-bullseye

RUN apt-get update && \
    apt-get upgrade -y && \
    apt-get install --no-install-recommends -y \
        ca-certificates curl unzip && \
    pip install --upgrade pip setuptools && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Installa kustomize
RUN curl -sLo /tmp/kustomize.tar.gz https://github.com/kubernetes-sigs/kustomize/releases/download/kustomize%2Fv5.3.0/kustomize_v5.3.0_linux_amd64.tar.gz && \
    tar -xzf /tmp/kustomize.tar.gz -C /usr/local/bin && \
    chmod +x /usr/local/bin/kustomize && \
    rm /tmp/kustomize.tar.gz

# Installa kubectl
RUN curl -LO https://dl.k8s.io/release/v1.29.0/bin/linux/amd64/kubectl && \
    install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl && \
    rm kubectl

WORKDIR /app

# Copia tutto nuvolaris (inclusi templates)
COPY ./nuvolaris /app/nuvolaris
COPY operator_handler.py /app/operator_handler.py

# Cartella per file dinamici di deploy
RUN mkdir -p /app/deploy/couchdb

# Installa dipendenze Python
RUN pip install kopf kubernetes pyyaml flatdict jinja2 backoff bcrypt

CMD ["kopf", "run", "--verbose", "--namespace=openserverless-system", "operator_handler.py"]
