# Changelog

## Unreleased
- Round 1-wire humidity values to 2 decimals.

## 1.0.2 - 2026-01-06
- Detect EVOK v2 vs v3 inputs using `/rest/all` (`input` vs `di`).
- Apply full EVOK filter on v3 so temp/1-wire updates arrive over WS.

## 1.0.1 - 2026-01-04
- WARNING: To support multiple devices, this update will rename all entities.
- Merge `evok-ws-client` to local and add real-time 1-wire updates via websocket payload merge.
