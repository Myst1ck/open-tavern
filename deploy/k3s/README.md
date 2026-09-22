# Open Tavern — k3s deployment

Manifests for running the prod Open Tavern stack on the single-node k3s
cluster (`slave`) in the existing `home` namespace. Namespace is not managed
here — it already exists.

Exposed at `https://slave.tail7c13f3.ts.net/tavern` via traefik.

## Prerequisites

Images must exist in k3s' containerd before apply (`imagePullPolicy: Never`):

```sh
# build locally, then import into k3s containerd
podman save localhost/open-tavern_backend:latest | sudo k3s ctr images import -
podman save localhost/open-tavern_frontend:tavern | sudo k3s ctr images import -

# or if images are already in the local store
sudo k3s ctr images import open-tavern_backend.tar
sudo k3s ctr images import open-tavern_frontend.tar
```

Frontend build must bake the subpath:

```sh
podman build --build-arg VITE_BASE=/tavern/ -t localhost/open-tavern_frontend:tavern ./frontend
```

Optional OpenAI key (backend starts without it; AI features return 503):

```sh
kubectl -n home create secret generic open-tavern-openai \
  --from-literal=OPENAI_API_KEY=sk-...
```

## Apply order

```sh
kubectl apply -f deploy/k3s/backend.yaml
kubectl apply -f deploy/k3s/frontend.yaml
kubectl apply -f deploy/k3s/ingress.yaml

kubectl -n home rollout status deploy/open-tavern-backend
kubectl -n home rollout status deploy/open-tavern-frontend
```

PVC first, then backend (waits for it), then frontend, then ingress.

## Update an image

Rebuild → import → restart rollout:

```sh
podman build -t localhost/open-tavern_backend:latest ./backend
podman save localhost/open-tavern_backend:latest | sudo k3s ctr images import -
kubectl -n home rollout restart deploy/open-tavern-backend
kubectl -n home rollout status deploy/open-tavern-backend
```

Same flow for frontend (`deploy/open-tavern-frontend`,
`localhost/open-tavern_frontend:tavern`). `imagePullPolicy: Never` means a
rollout restart alone picks up the newly imported image — no registry needed.

## Notes

- SQLite lives on the `open-tavern-data` PVC (local-path, 1Gi) at
  `/data/open_tavern.db`. Single replica only.
- Frontend proxy target is read at runtime from
  `OPEN_TAVERN_PROXY_TARGET=http://backend:8000`.
