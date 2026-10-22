# cvpr3d-tools

Small offline tools for inspecting binary glTF (GLB) files and checking evidence
integrity. Python 3.10+; no runtime dependencies, GPU, model weights or API keys.

This is an alpha toolkit extracted from the newly authored maintenance layer
of CVPR_3D. It is not a reconstruction model, renderer, geometry repair system
or full glTF validator. No conference publication or production readiness is
claimed. ARTIVRA's ambition to make affordable 3D/VFX creation accessible to
independent creators is a long-term vision, not an achieved toolkit capability.

## Quickstart

From the toolkit checkout (not the separate historical research repository):

```sh
python -m cvpr3d --help
python -m cvpr3d demo panel.glb
python -m cvpr3d inspect panel.glb --output panel-report.json
python -m cvpr3d compare panel.glb panel.glb --require-preserved
python -m unittest discover -s tests -v
```

The synthetic fixture contains a triangle and an animated panel. It uses no
third-party assets and is not an AI generation result. Outputs refuse overwrite;
use fresh filenames when repeating commands. The tools do not display a viewer.

For installation, create a virtual environment, activate it for your shell,
then run `python -m pip install .`. The installed `cvpr3d` command has the same
interface. Installation needs the build backend; runtime is offline. There is
no assumed PyPI release: install from this checkout or a verified local wheel.

## What the commands establish

| Command | Checks | Does not establish |
| --- | --- | --- |
| `inspect asset.glb` | Container bounds, declared counts, references, embedded image hashes | Decoded geometry, image quality, full glTF conformance |
| `compare before.glb after.glb` | Exact material/texture/sampler definitions and image payload identity | UV, geometry, material assignment, motion or visual equivalence |
| `verify-files manifest.json` | Declared file hashes/sizes | Manifest authenticity, extra-file absence, ownership |
| `verify-checkpoint snapshot.manifest.json` | Local ZIP and payload hashes, member set and embedded manifest | Scientific validity; never extracts or executes payloads |

See [usage and manifest examples](docs/USAGE.md), [contributing](CONTRIBUTING.md),
[security boundaries](SECURITY.md), and [release checks](docs/RELEASING.md).

## License and provenance

This toolkit's included source, synthetic fixtures and documentation are under
the [MIT license](LICENSE); see [license scope](LICENSING.md) and
[provenance](NOTICE.md). The historical CVPR_3D artifacts, photographs, copied
dependencies, model outputs and Git history are not distributed here. Nothing
in this toolkit grants additional rights to that separate material.
