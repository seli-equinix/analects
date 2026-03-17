# Nutanix v4.2 Python SDK - Context Hub Documentation

Community-contributed documentation for the [Nutanix v4.2 Python SDK](https://developers.nutanix.com/sdk-reference) formatted for [Andrew Ng's Context Hub](https://github.com/andrewyng/context-hub).

## What is this?

This repository provides LLM-optimized documentation for all 12 Nutanix v4.2 Python SDK namespaces. It enables coding agents (Claude Code, Cursor, Copilot, etc.) to generate accurate, up-to-date Nutanix infrastructure automation code.

## Quick Start

```bash
# Install Context Hub CLI
npm install -g @aisuite/chub

# Search for Nutanix docs
chub search nutanix

# Get specific namespace docs
chub get nutanix/nutanix-sdk --lang py        # Overview + shared patterns
chub get nutanix/nutanix-vmm --lang py        # VM management
chub get nutanix/nutanix-prism --lang py      # Tasks, categories, batch
chub get nutanix/nutanix-clustermgmt --lang py # Clusters, hosts, storage
chub get nutanix/nutanix-networking --lang py  # Subnets, VPCs, VPN
```

## Coverage

| Namespace | Package | Version | API Classes | Methods |
|-----------|---------|---------|-------------|---------|
| **SDK Overview** | (all) | 4.2.1 | 112 | 644 |
| vmm | ntnx_vmm_py_client | 4.2.1 | 15 | 179 |
| prism | ntnx_prism_py_client | 4.2.1 | 7 | 37 |
| clustermgmt | ntnx_clustermgmt_py_client | 4.2.1 | 10 | 84 |
| networking | ntnx_networking_py_client | 4.2.1 | 35 | 118 |
| lifecycle | ntnx_lifecycle_py_client | 4.2.1 | 13 | 29 |
| microseg | ntnx_microseg_py_client | 4.2.1 | 5 | 33 |
| datapolicies | ntnx_datapolicies_py_client | 4.2.1 | 4 | 43 |
| dataprotection | ntnx_dataprotection_py_client | 4.2.1 | 6 | 31 |
| volumes | ntnx_volumes_py_client | 4.2.1 | 3 | 30 |
| licensing | ntnx_licensing_py_client | 4.3.1 | 3 | 19 |
| monitoring | ntnx_monitoring_py_client | 4.2.1 | 9 | 23 |
| aiops | ntnx_aiops_py_client | 4.2.1b1 | 2 | 18 |

## Directory Structure

```
content/nutanix/docs/
├── nutanix-sdk/python/DOC.md              # Overview, auth, shared patterns
├── nutanix-vmm/python/
│   ├── DOC.md                             # VM lifecycle, images, templates
│   └── references/vm-api-complete.md      # All 69 VmApi methods
├── nutanix-prism/python/DOC.md            # Tasks, categories, batch ops
├── nutanix-clustermgmt/python/
│   ├── DOC.md                             # Clusters, hosts, storage containers
│   └── references/clusters-api-complete.md
├── nutanix-networking/python/
│   ├── DOC.md                             # Subnets, VPCs, gateways
│   └── references/api-classes.md          # All 35 API classes
├── nutanix-lifecycle/python/DOC.md        # LCM updates, inventory
├── nutanix-microseg/python/DOC.md         # Flow security policies
├── nutanix-dataprotection/python/DOC.md   # Snapshots, failover, DR
├── nutanix-datapolicies/python/DOC.md     # Protection/recovery plans
├── nutanix-volumes/python/DOC.md          # Volume groups, iSCSI
├── nutanix-licensing/python/DOC.md        # License management
├── nutanix-monitoring/python/DOC.md       # Alerts, events, audits
└── nutanix-aiops/python/DOC.md            # Capacity planning (beta)
```

## Requirements

- Prism Central pc.2024.1+ and AOS 6.8+
- Python 3.9+

## Validation

```bash
chub build content/nutanix/ --validate-only --json
```

## Sources
- [Nutanix SDK Reference](https://developers.nutanix.com/sdk-reference)
- [Official Code Samples](https://github.com/nutanixdev/code-samples/tree/master/python/v4api_sdk)
- [PyPI packages](https://pypi.org/search/?q=ntnx+py+client)
