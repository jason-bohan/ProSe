"""Emulation-testing harness: local mock servers and synthetic data generators.

Stdlib-only, matching the project's no-network-dependency design (see README
"Design for low-capability models"). These emulate the external systems the
real code talks to instead of pulling in a separate mock-server dependency:

- ``mock_endpoints``: an in-process HTTP server that emulates the CFPB, RECAP
  (CourtListener), and FTC endpoints ``prose.crawler`` calls over the wire.
- ``synthetic``: seeded random generators standing in for Faker to fuzz the
  matcher/doc pipeline with varied, deterministic data.
- ``device_emulator``: a local WebSocket "glasses" receiver standing in for
  physical smart-glasses hardware, for testing ``prose.device`` transports.
"""
