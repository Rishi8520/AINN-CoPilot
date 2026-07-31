# Third-Party Notices

The original source code of this project (**TelcoMind — AI-Native Digital Twin Copilot
with Intent-Driven Self-Healing**) is licensed under the **Apache License, Version 2.0**.
See [LICENSE](LICENSE) for the full text.

This project incorporates, depends on, or references third-party software, base images,
frameworks, and external publications. **All such third-party materials remain under their
own respective licenses and terms.** Apache License 2.0 applies only to this project's own
source code and **does not relicense, sublicense, or alter the terms of any third-party
software, standards document, or upstream project.**

The lists below are provided for informational purposes. Exact license versions and terms
are defined by each upstream project and its distribution. Where authoritative license
evidence is not bundled in this repository, the category is listed without asserting an
exact license identifier.

## Python Dependencies

This project uses Python packages declared in the repository requirements files (for
example `CODE/requirements.txt` and per-service requirements). Each package is governed by
its own license (commonly MIT, BSD, Apache-2.0, or similar) as published by its maintainers.
Refer to each package's distribution metadata for authoritative terms.

## Docker Base Images

Container images are built from third-party base images referenced in the project
Dockerfiles. Each base image and the software it contains remains subject to its own
license and the terms of its provider/registry.

## Simulation Stack (OMNeT++, INET, Simu5G)

- **OMNeT++** — simulation framework; governed by its own license terms.
- **INET Framework** — governed by its own license terms.
- **Simu5G** — governed by its own license terms.

These components are optional for the default quickstart (which uses recorded replay) and
are not redistributed or relicensed by this project. Consult each project's upstream
distribution for authoritative license information.

## Standards and Specification Materials (3GPP, ETSI, O-RAN)

- **3GPP materials**
- **ETSI materials**
- **O-RAN materials**

Telecommunications standards documents and specifications are the property of their
respective standards development organizations and are subject to those organizations'
copyright and redistribution policies. **This project's Apache 2.0 license does not grant
any rights to these standards documents.**

> **Redistribution review flag:** Any third-party standards PDFs that may be present in the
> repository require explicit redistribution-permission review before inclusion in any
> public submission archive. Such PDFs are **excluded** from the generated submission
> archive unless redistribution permission is explicitly established.

## Optional Hugging Face Models

Optional model artifacts obtainable from the Hugging Face Hub are governed by their
individual model licenses and usage terms. These are **not** required for, or included in,
the default deterministic quickstart.

## Optional NVIDIA and vLLM Components

Optional GPU-accelerated inference components (for example NVIDIA software and **vLLM**)
are governed by their own licenses and terms. These are optional, are **not** used by the
default quickstart, and are not redistributed by this project.

## No Legal Guarantee

This notice is provided for informational purposes only and does not constitute legal
advice or a warranty of any kind. Users and redistributors are responsible for verifying
and complying with all applicable third-party license terms and standards-redistribution
policies.
