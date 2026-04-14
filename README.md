# Nubly – Home Assistant Integration

Custom Home Assistant integration for Nubly devices.

## Overview

This repo contains **only** the Home Assistant custom integration.
The device firmware lives in a separate repository.

## Status

**Scaffold + config flow only** — the integration can be loaded by Home Assistant and
configured via the UI, but does not yet communicate with devices.

## Installation (HACS)

1. Open HACS in your Home Assistant instance.
2. Go to **Integrations** → three-dot menu (top right) → **Custom repositories**.
3. Add this repository URL and select **Integration** as the category.
4. Find **Nubly** in the HACS integration list and click **Install**.
5. Restart Home Assistant.
6. Go to **Settings → Devices & Services → Add Integration** and search for **Nubly**.

### Manual installation

Copy the `custom_components/nubly` folder into your Home Assistant
`config/custom_components/` directory and restart Home Assistant.
