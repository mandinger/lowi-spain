# Lowi para Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)

**🇪🇸 Español** | [🇬🇧 English](README.en.md)

Integración personalizada de [Home Assistant](https://www.home-assistant.io/) para [Lowi](https://www.lowi.es), el operador móvil low-cost español propiedad de Vodafone España. Expone el consumo de datos de tus líneas móviles y el coste del mes actual como sensores.

## Estado

Esta integración está en desarrollo activo. La API con la que habla es una interfaz **no oficial, obtenida por ingeniería inversa** del área de cliente de Lowi — no existe una API pública ni soporte por parte de Lowi/Vodafone. Consulta [CONTRIBUTING.md](CONTRIBUTING.md) para saber cómo se descubrió la API y cómo ayudar si Lowi la cambia.

## Instalación

### HACS (recomendado)

1. En HACS, añade este repositorio como repositorio personalizado (categoría: Integración).
2. Instala "Lowi".
3. Reinicia Home Assistant.

### Directa usando _My Home Assistant_
[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=mandinger&repository=lowi-spain&category=integration)


### Manual

Copia `custom_components/lowi_spain` en el directorio `config/custom_components/` de tu Home Assistant y reinicia.

## Configuración

La configuración se hace desde la interfaz: **Ajustes → Dispositivos y servicios → Añadir integración → Lowi**. Se te pedirá tu **NIF/DNI** y contraseña, y después — si tu cuenta tiene más de una línea móvil — a qué número debe enviarse el **código de verificación por SMS**, y por último ese código. Esto reproduce el mismo inicio de sesión que usa lowi.es; las cuentas con una sola línea pasan directamente al paso del código.

Cada línea móvil de tu cuenta se convierte en su propio dispositivo, con sensores para:

- Datos restantes
- Datos consumidos
- Total de datos del bono
- Datos consumidos (%)
- Datos incluidos en la tarifa
- Datos de bonus/extra
- Llamadas ilimitadas (activadas/desactivadas)

El nombre del plan, el precio, la zona de roaming y el desglose de datos extra (p. ej. el remanente del ciclo anterior) se exponen como atributos del sensor en lugar de como entidades independientes.

Un dispositivo separado, "Lowi Account", cubre las cifras que no están ligadas a una línea concreta:

- Coste de este mes
- Fin del periodo de facturación
- Importe, estado y fecha de la última factura

Los datos se actualizan cada 6 horas. Este intervalo es intencionadamente conservador — consulta [CONTRIBUTING.md](CONTRIBUTING.md) para saber por qué.

## Aviso legal

Este proyecto no está afiliado, respaldado ni soportado por Lowi ni por Vodafone España. Úsalo bajo tu propia responsabilidad; depende de una interfaz que puede cambiar o bloquearse en cualquier momento.
