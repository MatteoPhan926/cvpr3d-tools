# Security boundaries

The runtime inspects local GLB/JSON/ZIP files. It does not download external URI
resources, load pickle/model weights, extract ZIPs or execute input contents.
File-size limits and structural checks are not a sandbox or complete security
audit. Checksums establish agreement with a manifest, not its authenticity.
Concurrent modification of inputs is outside the guarantee.

Writes refuse existing files. GLB counts come from declarations; the toolkit
does not validate decoded geometry, pixels, visual quality or complete glTF
conformance. Keep untrusted assets out of privileged processes.

Development packaging checks install only the locally built wheel and execute
its code/tests in a temporary environment. Do not use the release checker as a
sandbox for arbitrary downloaded Python packages.

Use the repository's private vulnerability reporting channel if enabled. If
none is available, ask the maintainer for a private channel without posting
credentials, exploit details or private assets. No security response SLA is
promised. A reporting channel must be confirmed before the first release.
