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

Copy `custom_components/lowi_spain` into your Home Assistant `config/custom_components/` directory and restart.

## Configuration

Configuration is done via the UI: **Settings → Devices & Services → Add Integration → Lowi**. You'll be asked for your **NIF/DNI** and password, then — if your account has more than one phone line — which number should receive the **SMS verification code**, then for that code. This mirrors the login lowi.es itself uses; accounts with a single line skip straight to the code step.

Each mobile phone line on your account becomes its own device, with sensors for:

- Remaining data
- Data used
- Total data allowance
- Data used (%)
- Tariff-included data
- Bonus/extra data
- Unlimited calls (on/off)

Plan name, price, roaming zone, and the extra-data breakdown (e.g. rollover from the previous cycle) are exposed as sensor attributes rather than separate entities.

A separate "Lowi Account" device covers figures that aren't tied to a single line:

- Cost this month
- Billing period end
- Last invoice amount, status, and date

Data is refreshed every 6 hours. This interval is intentionally conservative — see [CONTRIBUTING.md](CONTRIBUTING.md) for why.

## Disclaimer

This project is not affiliated with, endorsed by, or supported by Lowi or Vodafone Spain. Use at your own risk; it relies on an interface that can change or be blocked at any time.
