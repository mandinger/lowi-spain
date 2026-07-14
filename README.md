# Lowi for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)

A custom [Home Assistant](https://www.home-assistant.io/) integration for [Lowi](https://www.lowi.es), the Spanish low-cost mobile carrier owned by Vodafone Spain. Exposes mobile-line data usage and current-month cost as sensors.

## Status

This integration is under active development. The API it talks to is an **unofficial, reverse-engineered** interface to the Lowi customer portal — there is no public API and no support from Lowi/Vodafone. See [CONTRIBUTING.md](CONTRIBUTING.md) for how the API was discovered and how to help if Lowi changes it.

## Installation

### HACS (recommended)

1. In HACS, add this repository as a custom repository (category: Integration).
2. Install "Lowi".
3. Restart Home Assistant.

### Manual

Copy `custom_components/lowi` into your Home Assistant `config/custom_components/` directory and restart.

## Configuration

Configuration is done via the UI: **Settings → Devices & Services → Add Integration → Lowi**. You'll be asked for your **NIF/DNI** and password, then for the **SMS verification code** Lowi sends to your phone — the same two-step login lowi.es itself uses.

Each mobile phone line on your account becomes its own device, with sensors for:

- Tariff-included data
- Bonus/extra data
- Remaining data *(not yet available — see [CONTRIBUTING.md](CONTRIBUTING.md))*
- Total data allowance *(not yet available)*
- Accumulated data from the previous cycle *(not yet available)*
- Shared data received *(not yet available)*
- Cost this month *(not yet available)*

Only the contracted-tariff figures are populated today; the live usage/cost sensors will read as unavailable until the consumption endpoint is identified (help wanted, see CONTRIBUTING.md).

Data is refreshed every 6 hours. This interval is intentionally conservative — see [CONTRIBUTING.md](CONTRIBUTING.md) for why.

## Disclaimer

This project is not affiliated with, endorsed by, or supported by Lowi or Vodafone Spain. Use at your own risk; it relies on an interface that can change or be blocked at any time.
