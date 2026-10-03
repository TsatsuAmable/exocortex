# NemoCoder tooling

This directory contains reconstructible tooling for the NemoCoder apprenticeship.

The historical corpus bootstrap miner exports immutable Git merge provenance and
changed-path metadata only. It deliberately does not export patches or source
contents yet. Patch/content admission requires the later secret, leakage and
provenance gate.

Runtime corpus artifacts live outside Git under the Exocortex local state root
and are referenced by deterministic hashes.
