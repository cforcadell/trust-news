# Filed deployment documentation — not to use

> [!WARNING]
> This directory retains historical references. Its commands, profiles,
> topology, TLS and components may be obsolete and do not constitute a
> procedimiento operativo.

The current sources are:

- [`skaffold-local.md`](../skaffold-local.md) for Kind within the local VM;
- [`skaffold-server.md`](../skaffold-server.md) for Hetzner;
- [`k8s-common.md`](../k8s-common.md) for shared procedures;
- [`gitlab-github-release-workflow.md`](../gitlab-github-release-workflow.md)
for deployment, promotion and release.

Do not copy from these files listeners `0.0.0.0`, `latest` images, ZooKeeper configuration, unsafe TLS options or destructive commands without contrasting them with current sources.
