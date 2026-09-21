# Reticulum на Orange Pi Zero 3W → связь со смартфоном

Поднимает на Orange Pi Zero 3W стек **Reticulum** (`rns` + `lxmf`) и мост, через который
сообщения из мессенджера Reticulum на смартфоне доходят до агента **Hermes** — и ответы
возвращаются тем же путём.

Доставка сообщений идёт **по локальной сети напрямую** (домашний Wi-Fi или раздача с
телефона): без интернета, без проброса портов, без VPN. Интернет нужен только чтобы модель
сформулировала ответ — и этот запрос тоже можно пустить напрямую, без прокси.

```
телефон (Reticulum Mobile / Sideband / columba)
  └── Wi-Fi или раздача с телефона
        └── Orange Pi Zero 3W: rnsd (порт 4242)
              └── мост hermes_bridge.py
                    └── локальный API Hermes (127.0.0.1:8642) → Hermes → ответ обратно
```

## Что в репозитории

| Файл | Что это |
|---|---|
| `INSTALL.md` | Пошаговая установка: копипаст-команды и полный код всех файлов |
| `scripts/hermes_bridge.py` | Мост: входящее LXMF-сообщение → Hermes → ответ отправителю |
| `scripts/test_bridge.py` | Самопроверка без телефона: свой узел пишет мосту и ждёт ответ |
| `systemd/rnsd.service` | Постоянная служба Reticulum (юнит пользователя) |
| `systemd/hermes-lxmf-bridge.service` | Постоянная служба моста |
| `systemd/reticulum-config.example` | Пример `~/.reticulum/config` |
| `systemd/hermes-gateway-noproxy-deepseek.conf` | Drop-in: модель мимо прокси (канал не зависит от VPN) |

## Требования

- Zero 3W (или любая ARM/Linux-машина) с Debian 12/13 или Ubuntu;
- Python 3.11+ (на Zero 3W — 3.13);
- ~200 МБ на диске;
- агент Hermes с поднятым локальным API (по умолчанию `127.0.0.1:8642`).

Внешних пакетов из apt не требуется: `venv` создаётся штатным Python, `pip` ставится внутрь
окружения через `get-pip.py`.

## Быстрый старт

Всё по шагам — в [INSTALL.md](INSTALL.md). Кратко:

```bash
python3 -m venv --without-pip ~/reticulum/venv
cd ~/reticulum && curl -sL -o get-pip.py https://bootstrap.pypa.io/get-pip.py
venv/bin/python get-pip.py --no-warn-script-location
venv/bin/pip install rns lxmf
venv/bin/python -c "import RNS; RNS.Reticulum()"   # создаст ~/.reticulum/config
```

Дальше — правка `~/.reticulum/config`, два юнита из `systemd/` и настройка приложения на
телефоне (`Settings → TCP transport node → Host: <IP Зеро>, Port: 4242 → Connect TCP`).

## Проверено на

Orange Pi Zero 3W, Debian 13, Python 3.13.5, `rns` 1.5.4, `lxmf` 1.1.1 — сентябрь 2026.
Живой прогон полного пути: телефон → Reticulum → мост → Hermes → ответ («Связь есть. 2+2 = 4. 🤓»).

## Про секреты

В репозитории **нет** ключей и токенов (адреса в примерах — вымышленные): ключ узла Reticulum генерируется на самой
машине при первом запуске, ключи сторонних сервисов мост читает из `~/.hermes/.env` и никуда
не пишет. Перед публикацией репозиторий проверялся на утечки.

## Смежное

- **Reticulum по радио (LoRa)** требует своего приёмопередатчика (RNode). В Москве и области
  LoRa-покрытие Reticulum практически отсутствует, зато хорошо работает **MeshCore** — под
  него нужна отдельная сборка (USB-радио в режиме companion + свой мост), это отдельная
  история.
- **Доступ снаружи дома** (телефон в сотовой сети, сервер дома за NAT) требует либо проброса
  порта, либо туннеля (Tailscale/WireGuard), либо релея — это свойство сетей, а не софта.
