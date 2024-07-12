FROM ubuntu:22.04
RUN apt-get update && apt-get -y install curl
RUN sh -c "$(curl --location https://taskfile.dev/install.sh)" -- -d -b /usr/bin
CMD sleep inf
