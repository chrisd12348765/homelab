# compose/ — app-layer IaC (your existing Docker Compose)

One folder per stack, each with a `docker-compose.yml`. These are the same files
the Ansible `docker` role deploys, so there's a single source of truth.

## Retrofit existing containers automatically

Reverse-engineer compose files from already-running containers with
[`docker-autocompose`](https://github.com/Red5d/docker-autocompose):

```bash
# on the host running the containers (or over SSH with DOCKER_HOST set)
docker run --rm -v /var/run/docker.sock:/var/run/docker.sock \
  ghcr.io/red5d/docker-autocompose <container1> <container2> ... \
  > compose/<stack>/docker-compose.yml
```

Then scrub any inline secrets/env into a SOPS-encrypted `.env` before committing.
