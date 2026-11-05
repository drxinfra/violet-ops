# v.2.4 12.10.2026
### Fixed
- **Reload instead of restart** after a config change: `nginx -s reload` keeps open
  connections, a restart dropped them. See [nginx docs](https://nginx.org/en/docs/control.html).
- The firewall task runs only when `web_firewall_enabled` is `true`.

## Upgrade notes
- New variable `web_client_max_body`, default `64m`.
