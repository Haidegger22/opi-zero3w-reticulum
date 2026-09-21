# Установка Reticulum на Orange Pi Zero 3W

Пошагово, копипастом. Все команды выполняются **на самой Zero** (под обычным пользователем,
`sudo` не нужен нигде, кроме пункта про apt — а он и не требуется).

Ориентировочное время: 10–15 минут, из них большая часть — установка Python-пакетов.

---

## 1. Что получится

```
[ телефон ]
   приложение Reticulum (MeshChat/Sideband/Reticulum Mobile)
   настроено: TCP-клиент на <IP Зеро>:4242
        │
        │  локальная сеть: домашний Wi-Fi либо раздача со смартфона
        ▼
[ Orange Pi Zero 3W ]
   rnsd            — стек Reticulum, слушает TCP 0.0.0.0:4242
        │
   hermes_bridge.py — читает входящие LXMF-сообщения
        │             и отправляет ответ обратно
        ▼
   локальный API Hermes (127.0.0.1:8642) → агент Hermes
```

Сообщение и ответ идут по локальной сети. Интернет нужен только агенту, чтобы получить ответ
у модели; этот запрос можно пустить напрямую, без прокси и VPN (пункт 10).

---

## 2. Требования

| Что | Как проверить |
|---|---|
| Python 3.11+ | `python3 -V` |
| Модуль `venv` | `python3 -m venv --help` (должен напечатать справку) |
| ~200 МБ на диске | `df -h /` |
| Агент Hermes с API на `127.0.0.1:8642` | `ss -ltn \| grep 8642` |
| Сеть между телефоном и Zero | оба в одной сети (домашний Wi-Fi или раздача с телефона) |

Внешние apt-пакеты не нужны: `venv` уже есть, а `pip` мы поставим **внутрь окружения** через
`get-pip.py` — система при этом не трогается.

---

## 3. Установка Reticulum и LXMF

```bash
# создаём отдельное окружение рядом с домашним каталогом
python3 -m venv --without-pip ~/reticulum/venv

cd ~/reticulum

# pip внутрь окружения (в системном Python его может не быть)
curl -sL -o get-pip.py https://bootstrap.pypa.io/get-pip.py
venv/bin/python get-pip.py --no-warn-script-location

# сам стек и слой сообщений
venv/bin/pip install --no-warn-script-location rns lxmf

# проверяем
venv/bin/python -c "import RNS, LXMF; print('RNS', RNS.__version__, '| LXMF', LXMF.__version__)"
```

Проверочные версии на момент написания: `RNS 1.5.4`, `LXMF 1.1.1`.

> Если у машины нет прямого интернета и есть локальный прокси, добавьте его только на время
> установки: `export HTTPS_PROXY=http://127.0.0.1:9697` (или свой адрес).

---

## 4. Создание конфигурации

Первый запуск создаёт `~/.reticulum/config` со значениями по умолчанию:

```bash
cd ~/reticulum
venv/bin/python -c "import RNS; RNS.Reticulum(); print('конфиг создан')"
ls -la ~/.reticulum/          # появятся config, interfaces/, storage/
```

---

## 5. Правка `~/.reticulum/config`

Содержимое файла целиком (можно скопировать как есть):

```ini
# Конфигурация Reticulum на Orange Pi Zero 3W (для связи со смартфоном через RNS)
# Подробный пример всех опций: rnsd --exampleconfig
# Документация: https://reticulum.network/manual/

[reticulum]

  # Zero — всегда включена и стоит на месте, поэтому может быть транспортным узлом:
  # будет пересылать трафик и объявления для других участников сети.
  enable_transport = True

  # Общий экземпляр: первая программа поднимает стек, остальные (в том числе наш
  # мост к Hermes) общаются с ним через локальный сокет.
  share_instance = Yes

  instance_name = default


[logging]
  # 0 — только критичное, 4 — info (по умолчанию), 6 — отладка
  loglevel = 4


[interfaces]

  # 1. Обнаружение соседей по Wi-Fi/Ethernet без настройки адресов
  # (широковещательные UDP-пакеты по link-local IPv6).
  [[Default Interface]]
    type = AutoInterface
    enabled = Yes

  # 2. TCP-сервер для смартфона: приложение на телефоне подключается
  # как TCP-клиент на 192.168.1.50:4242. Нужен потому, что в домашних
  # Wi-Fi сетях широковещательные пакеты часто режутся между клиентами.
  [[Phone TCP]]
    type = TCPServerInterface
    enabled = Yes
    listen_ip = 0.0.0.0
    listen_port = 4242
```

Что здесь важно:

- **`enable_transport = True`** — Zero работает круглосуточно и стоит на месте, поэтому может
  быть транспортным узлом: пересылать трафик и объявления соседей.
- **`share_instance = Yes`** — первая программа поднимает стек, остальные (мост) подключаются
  к нему через локальный сокет. Без этого мост и `rnsd` не увидят друг друга.
- **`[[Default Interface]]` (AutoInterface)** — поиск соседей по локальной сети автоматом.
- **`[[Phone TCP]]` (TCPServerInterface, порт 4242)** — то, к чему подключается телефон.
  Именно TCP, а не только автопоиск: в домашних Wi-Fi широковещательные пакеты между
  клиентами часто отключены, и тогда автопоиск не находит телефон.

Полный список опций интерфейсов — в официальном мануале:
<https://reticulum.network/manual/interfaces.html>

---

## 6. Первый запуск и проверка

Временно (до перезагрузки) можно поднять службу «на один раз»:

```bash
export XDG_RUNTIME_DIR=/run/user/$(id -u)
export DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$(id -u)/bus

systemd-run --user --collect --unit=rnsd \
  --description="Reticulum Network Stack" ~/reticulum/venv/bin/rnsd

sleep 8
~/reticulum/venv/bin/rnstatus          # покажет интерфейсы и их статус
ss -ltn | grep 4242                    # порт должен слушаться
```

Ожидаемый вывод `rnstatus` (сокращённо):

```
 AutoInterface[Default Interface]
    Status    : Up
 TCPServerInterface[Phone TCP/0.0.0.0:4242]
    Status    : Up
    Clients   : 0
 Transport Instance <...> running
```

---

## 7. Постоянные службы

Скопируйте юниты из репозитория в каталог пользовательских служб и включите их.

`~/.config/systemd/user/rnsd.service`:

```ini
[Unit]
Description=Reticulum Network Stack (rnsd)
Documentation=https://reticulum.network/manual/
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
# Пользовательский юнит: %h — домашний каталог пользователя
ExecStart=%h/reticulum/venv/bin/rnsd
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
```

`~/.config/systemd/user/hermes-lxmf-bridge.service`:

```ini
[Unit]
Description=Мост Reticulum (LXMF) → Hermes
After=network-online.target rnsd.service
Wants=network-online.target
Requires=rnsd.service

[Service]
Type=simple
ExecStart=%h/reticulum/venv/bin/python %h/reticulum/hermes_bridge.py
Restart=on-failure
RestartSec=10
# Без буферизации, чтобы лог моста был виден сразу
Environment=PYTHONUNBUFFERED=1
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
```

```bash
mkdir -p ~/.config/systemd/user
cp systemd/rnsd.service systemd/hermes-lxmf-bridge.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now rnsd hermes-lxmf-bridge

# проверка
systemctl --user status rnsd --no-pager | head -5
systemctl --user status hermes-lxmf-bridge --no-pager | head -5
journalctl --user -u rnsd -n 20 --no-pager
```

Чтобы службы поднимались и без входа в графическую сессию:

```bash
loginctl enable-linger $USER        # может потребовать прав sudo
```

---

## 8. Мост в Hermes

Скрипт кладём в `~/reticulum/hermes_bridge.py`.

```python
#!/usr/bin/env python3
"""Мост: сообщения из Reticulum (LXMF) → Hermes → ответ обратно в Reticulum.

Логика простая: приходит сообщение от телефона — текст уходит в локальный API
Hermes (127.0.0.1:8642), ответ возвращается отправителю как LXMF-сообщение.
Длинные ответы рубятся на части: в одиночном пакете LXMF умещается около 295 байт.
"""
import json
import os
import threading
import time
import traceback
import urllib.request

import LXMF
import RNS

HOME = os.path.expanduser("~")
RET = os.path.join(HOME, "reticulum")

# Всё настраивается через окружение, чтобы один и тот же скрипт работал и на другом узле
# (например на Джарвисе): имена файлов и имя узла задаются в юните службы.
DISPLAY_NAME = os.environ.get("LXMF_BOT_NAME", "Зеро (Hermes)")
IDENTITY_FILE = os.environ.get("LXMF_IDENTITY_FILE", os.path.join(RET, "zero_hermes_identity"))
STORAGE = os.environ.get("LXMF_STORAGE", os.path.join(RET, "lxmf_storage"))
ADDRESS_FILE = os.environ.get("LXMF_ADDRESS_FILE", os.path.join(RET, "zero_address.txt"))
LOG_FILE = os.environ.get("LXMF_LOG", os.path.join(RET, "bridge.log"))
ENV_FILE = os.path.join(HOME, ".hermes", ".env")

API_URL = os.environ.get("BRIDGE_API_URL", "http://127.0.0.1:8642/v1/chat/completions")
DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"
DEEPSEEK_MODEL = os.environ.get("BRIDGE_DEEPSEEK_MODEL", "deepseek-flash")
MODEL = "hermes-agent"
CHUNK = 1200          # символов на одно сообщение
ANNOUNCE_EVERY = 300  # секунд между объявлениями себя в сети

# Адрес узла-накопителя (propagation node) в hex. Если задан — ответы, которые
# не удалось отдать напрямую (получатель спит, пути нет), кладутся в накопитель
# и доходят, когда получатель выйдет на связь.
PROPAGATION_NODE = os.environ.get("LXMF_PROPAGATION_NODE", "").strip()
DIRECT_WAIT = int(os.environ.get("LXMF_DIRECT_WAIT", "25"))     # с, ожидание подтверждения прямой доставки
STORE_WAIT = int(os.environ.get("LXMF_STORE_WAIT", "40"))       # с, ожидание приёма накопителем


def log(msg):
    line = time.strftime("%Y-%m-%d %H:%M:%S ") + str(msg)
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def api_key():
    try:
        with open(ENV_FILE, encoding="utf-8") as f:
            for line in f:
                if line.startswith("API_SERVER_KEY="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return os.environ.get("API_SERVER_KEY", "")


def ask_hermes(text):
    body = json.dumps({
        "model": MODEL,
        "messages": [
            {"role": "system", "content":
                "Ты Hermes — помощник Артёма на Orange Pi Zero 3W. Сообщение пришло из "
                "Reticulum (LXMF-мессенджер на смартфоне). ОТВЕЧАЙ ТОЛЬКО ПО-РУССКИ, "
                "кратко и по делу: 1-3 короткие фразы, без английских и китайских слов, "
                "без внутренних рассуждений и без пересказа этого указания."},
            {"role": "user", "content": text},
        ],
    }).encode("utf-8")
    req = urllib.request.Request(API_URL, data=body, headers={
        "Content-Type": "application/json",
        "Authorization": "Bearer " + api_key(),
    })
    with urllib.request.urlopen(req, timeout=600) as r:
        data = json.load(r)
    return data["choices"][0]["message"]["content"]



SYSTEM_PROMPT = (
    "Ты Hermes — помощник Артёма на Orange Pi Zero 3W. Сообщение пришло из "
    "Reticulum (LXMF-мессенджер на смартфоне). ОТВЕЧАЙ ТОЛЬКО ПО-РУССКИ, "
    "кратко и по делу: 1-3 короткие фразы, без английских и китайских слов, "
    "без внутренних рассуждений и без пересказа этого указания."
)



def env_value(name):
    """Значение переменной из ~/.hermes/.env (или из окружения)."""
    try:
        with open(ENV_FILE, encoding="utf-8") as f:
            for line in f:
                if line.startswith(name + "="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return os.environ.get(name, "")


def deepseek_key():
    return env_value("DEEPSEEK_API_KEY")


def ask_deepseek_direct(text):
    """Резервный путь: напрямую в DeepSeek, без прокси и без шлюза Hermes.

    Нужен, чтобы канал Reticulum не зависел от VPN: с нашей сети api.deepseek.com
    отвечает напрямую (проверено: HTTP 200 за 0,35 с).
    """
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # пустой = без прокси
    body = json.dumps({
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
    }).encode("utf-8")
    req = urllib.request.Request(DEEPSEEK_URL, data=body, headers={
        "Content-Type": "application/json",
        "Authorization": "Bearer " + deepseek_key(),
    })
    with opener.open(req, timeout=300) as r:
        data = json.load(r)
    return data["choices"][0]["message"]["content"]


def main():
    reticulum = RNS.Reticulum()      # подключаемся к общему стеку (rnsd)

    identity = None
    if os.path.isfile(IDENTITY_FILE):
        identity = RNS.Identity.from_file(IDENTITY_FILE)
    if identity is None:
        identity = RNS.Identity()
        identity.to_file(IDENTITY_FILE)
        log("создан новый ключ узла")

    router = LXMF.LXMRouter(identity=identity, storagepath=STORAGE)
    local_dest = router.register_delivery_identity(identity, display_name=DISPLAY_NAME)
    if PROPAGATION_NODE:
        try:
            router.set_active_propagation_node(bytes.fromhex(PROPAGATION_NODE))
            log("узел-накопитель для ответов: " + PROPAGATION_NODE)
        except Exception:
            log("не удалось указать узел-накопитель: " + traceback.format_exc())
    address = local_dest.hash.hex()
    log("адрес LXMF: " + address)
    try:
        with open(ADDRESS_FILE, "w", encoding="utf-8") as f:
            f.write(address + "\n")
    except OSError:
        pass

    def recall_identity(source_hash, wait_seconds=60):
        """Ключ адресата узнаём из его объявления в сети. Если ключа нет —
        просим сеть прислать объявление и ждём: без ключа ответ отправить нельзя.
        Так мост отвечает и тому, кто написал впервые (например с телефона,
        подключённого к другому узлу сети)."""
        ident = RNS.Identity.recall(source_hash)
        if ident is not None:
            return ident
        log("ключ адресата неизвестен, запрашиваю объявление у сети: " + source_hash.hex())
        try:
            RNS.Transport.request_path(source_hash)
        except Exception:
            log("не удалось запросить путь: " + traceback.format_exc())
        deadline = time.time() + wait_seconds
        while time.time() < deadline:
            time.sleep(2)
            ident = RNS.Identity.recall(source_hash)
            if ident is not None:
                log("ключ адресата получен, отвечаю")
                return ident
        log("объявление не пришло за %d с — ответ отправить не могу" % wait_seconds)
        return None

    def send_parts(remote, text, method, wait_seconds):
        """Отправляет ответ (при необходимости частями) и ждёт подтверждения.

        Прямая доставка подтверждается состоянием DELIVERED, через накопитель —
        состоянием SENT (накопитель принял сообщение к себе на хранение)."""
        chunks = [text[i:i + CHUNK] for i in range(0, len(text), CHUNK)] or [""]
        confirmed = []
        for i, part in enumerate(chunks):
            prefix = "" if len(chunks) == 1 else "(%d/%d) " % (i + 1, len(chunks))
            msg = LXMF.LXMessage(remote, local_dest, prefix + part,
                                 title="Hermes",
                                 desired_method=method)
            msg.register_delivery_callback(
                lambda m: confirmed.append(getattr(m, "state", "?")))
            router.handle_outbound(msg)
            time.sleep(0.4)
        deadline = time.time() + wait_seconds
        while time.time() < deadline and not confirmed:
            time.sleep(1)
        return (True, confirmed[0]) if confirmed else (False, None)

    def send_reply(source_hash, text):
        dest_identity = recall_identity(source_hash)
        if dest_identity is None:
            return
        remote = RNS.Destination(dest_identity, RNS.Destination.OUT,
                                 RNS.Destination.SINGLE, "lxmf", "delivery")
        try:
            has_path = RNS.Transport.has_path(source_hash)
        except Exception:
            has_path = False

        # Путь есть — отдаём напрямую (быстро). Пути нет — сразу в накопитель,
        # чтобы ответ не потерялся, пока получатель спит.
        if has_path:
            ok, state = send_parts(remote, text, LXMF.LXMessage.DIRECT, DIRECT_WAIT)
            if ok:
                log("ответ доставлен напрямую (состояние %s)" % state)
                return
            log("прямая доставка не подтвердилась за %d с" % DIRECT_WAIT)

        if PROPAGATION_NODE:
            ok, state = send_parts(remote, text, LXMF.LXMessage.PROPAGATED, STORE_WAIT)
            if ok:
                log("ответ отдан в накопитель (состояние %s) — дойдёт, когда получатель выйдет на связь" % state)
                return
            log("накопитель не принял сообщение за %d с" % STORE_WAIT)
        else:
            log("пути к получателю нет, а накопитель не настроен — ответ не отправлен")

    def work(message, text):
        try:
            answer = ask_hermes(text)
            log("ответ Hermes: %d символов" % len(answer or ""))
        except Exception as e:
            log("шлюз Hermes недоступен (%s) — отвечаю напрямую через DeepSeek" % e)
            try:
                answer = ask_deepseek_direct(text)
                log("прямой ответ DeepSeek: %d символов" % len(answer or ""))
            except Exception as e2:
                answer = "Нет связи ни с Hermes, ни с моделью: %s" % e2
                log("прямой путь тоже не сработал: " + traceback.format_exc())
        send_reply(message.source_hash, answer or "(пустой ответ)")

    def on_message(message, propagation=None):
        try:
            text = (message.content or b"").decode("utf-8", "replace").strip()
            src = message.source_hash.hex()
            if not text:
                log("пустое сообщение от " + src)
                return
            log("входящее от %s: %s" % (src, text[:200].replace("\n", " ")))
            threading.Thread(target=work, args=(message, text), daemon=True).start()
        except Exception:
            log("сбой при обработке: " + traceback.format_exc())

    router.register_delivery_callback(on_message)
    log("мост запущен, объявляюсь в сети")

    while True:
        try:
            router.announce(local_dest.hash)
        except Exception:
            log("не смог объявиться: " + traceback.format_exc())
        time.sleep(ANNOUNCE_EVERY)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception:
        log("фатальная ошибка: " + traceback.format_exc())
        raise
```

Как он работает:

1. Поднимает стек (`RNS.Reticulum()`) и **подключается** к уже работающему `rnsd` — поэтому
   важен `share_instance = Yes` в конфиге.
2. Регистрирует собственный LXMF-адрес и объявляет его в сети (раз в 5 минут), чтобы телефон
   видел узел.
3. На каждое входящее сообщение запускает отдельный поток: текст уходит в локальный API Hermes
   (`POST http://127.0.0.1:8642/v1/chat/completions`, модель `hermes-agent`), ответ режется на
   части по 1200 символов и отправляется отправителю.
4. Ключ локального API читается из `~/.hermes/.env` (переменная `API_SERVER_KEY`). Если API
   недоступен — включается **резервный прямой путь** к модели (см. пункт 10), чтобы канал
   Reticulum не зависел от VPN.
5. Свой LXMF-адрес пишет в `~/reticulum/zero_address.txt`, лог — `~/reticulum/bridge.log`.

Проверка лога после старта:

```bash
tail -5 ~/reticulum/bridge.log
cat ~/reticulum/zero_address.txt      # адрес, который надо вписать в телефон
```

---

## 9. Самопроверка без телефона

Скрипт поднимает на той же машине второй LXMF-узел, пишет мосту и ждёт ответ.

```python
#!/usr/bin/env python3
"""Самопроверка моста: свой узел отправляет сообщение мосту и ждёт ответ.

Запускается на самой Зеро — второй экземпляр LXMF через тот же общий стек.
"""
import os
import sys
import time

import LXMF
import RNS

HOME = os.path.expanduser("~")
ADDRESS_FILE = os.environ.get("LXMF_ADDRESS_FILE",
                              os.path.join(HOME, "reticulum", "zero_address.txt"))
TEST_IDENTITY = os.environ.get("LXMF_TEST_IDENTITY",
                              os.path.join(HOME, "reticulum", "test_identity"))
STORAGE = os.environ.get("LXMF_TEST_STORAGE",
                        os.path.join(HOME, "reticulum", "lxmf_storage_test"))
TIMEOUT = 120

reply_text = []


def main():
    reticulum = RNS.Reticulum()
    if os.path.isfile(TEST_IDENTITY):
        identity = RNS.Identity.from_file(TEST_IDENTITY)
    else:
        identity = RNS.Identity()
        identity.to_file(TEST_IDENTITY)

    router = LXMF.LXMRouter(identity=identity, storagepath=STORAGE)
    me = router.register_delivery_identity(identity, display_name="Тестовый клиент")
    print("мой тестовый адрес:", me.hash.hex())

    target_hex = open(ADDRESS_FILE).read().strip()
    target = bytes.fromhex(target_hex)
    print("шлю в мост:", target_hex)

    def on_message(message, propagation=None):
        text = (message.content or b"").decode("utf-8", "replace")
        print("ОТВЕТ ПОЛУЧЕН:", text[:300])
        reply_text.append(text)

    def on_delivery(message, state=None):
        print("статус доставки моего сообщения:", state)

    router.register_delivery_callback(on_message)
    router.announce(me.hash)

    # ждём, пока узел моста станет известен (объявление)
    for _ in range(60):
        if RNS.Identity.recall(target) is not None:
            break
        if _ % 10 == 0:
            RNS.Transport.request_path(target)
        time.sleep(1)
    if RNS.Identity.recall(target) is None:
        print("узел моста пока не виден — попробую всё равно")
        # запросим путь
        RNS.Transport.request_path(target)
        time.sleep(5)

    dest_identity = RNS.Identity.recall(target)
    if dest_identity is None:
        print("НЕ УДАЛОСЬ: ключ моста неизвестен (мост не объявился?)")
        return 1
    dest = RNS.Destination(dest_identity, RNS.Destination.OUT,
                           RNS.Destination.SINGLE, "lxmf", "delivery")

    question = "Проверка связи через Reticulum. Ответь коротко: сколько будет 2+2?"
    msg = LXMF.LXMessage(dest, me, question, title="Проверка",
                         desired_method=LXMF.LXMessage.DIRECT)
    msg.register_delivery_callback(on_delivery)
    router.handle_outbound(msg)
    print("сообщение отправлено, жду ответ до %d с" % TIMEOUT)

    t0 = time.time()
    while time.time() - t0 < TIMEOUT and not reply_text:
        time.sleep(1)

    if reply_text:
        print("ИТОГ: связь через Reticulum работает")
        return 0
    print("ИТОГ: ответ не пришёл за %d с" % TIMEOUT)
    return 1


if __name__ == "__main__":
    sys.exit(main())
```

```bash
cd ~/reticulum && venv/bin/python test_bridge.py
```

Ожидаемый результат:

```
мой тестовый адрес: <32 hex>
шлю в мост: <адрес из zero_address.txt>
сообщение отправлено, жду ответ до 120 с
ОТВЕТ ПОЛУЧЕН: <ответ агента>
ИТОГ: связь через Reticulum работает
```

---

## 10. Настройка телефона

### Приложение

| Клиент | Размер | Установка | Язык интерфейса |
|---|---|---|---|
| **Reticulum Mobile** (thatSFguy, Kotlin, без сервисов Google) | ~13 МБ | APK из GitHub Releases | английский |
| **Sideband** (эталонный LXMF-клиент) | ~115 МБ | APK из GitHub Releases | английский |
| **columba** (нативный Kotlin) | 58 МБ | APK из GitHub Releases | английский |
| MeshChat | — | только рабочий стол | английский |

Русской локализации нет ни у одного клиента Reticulum — это проверено по их исходникам.
Варианты: пользоваться как есть (переписка при этом идёт по-русски), переводить строки в
columba и собирать APK самому, или сделать свой веб-интерфейс.

Раздать APK телефону проще всего со самой Zero:

```bash
mkdir -p ~/reticulum/apk && cd ~/reticulum/apk   # сюда положить .apk
python3 -m http.server 8099 --bind 0.0.0.0
# на телефоне открыть http://<IP Зеро>:8099/имя-файла.apk
```

### Настройка связи

1. Установить APK (разрешить установку из неизвестных источников).
2. Открыть приложение и дать ему создать идентичность (генерируется на телефоне).
3. Добавить связь: **Settings → TCP transport node** (в некоторых клиентах — `Add node` →
   `TCP`):
   - **Host**: `<IP Зеро>` (например `192.168.1.50`)
   - **Port**: `4242`
   - нажать **Connect TCP** (не `Pick another` — та кнопка уводит на публичные узлы).
4. Добавить адресата: **Nodes → Add by hash** → адрес узла из `~/reticulum/zero_address.txt`.
5. Написать сообщение. Ответ придёт тем же путём.

---

## 11. Сценарии сети

| Где телефон | Где Zero | Работает? | Что нужно |
|---|---|---|---|
| Домашний Wi-Fi | тот же Wi-Fi | ✅ | вписать `<IP Зеро>` (например `192.168.1.50`) |
| Раздача со смартфона | клиент раздачи | ✅ | узнать адрес Зеро в этой сети и вписать его (диапазон обычно `192.168.43.x`) |
| Сотовая сеть | дома за NAT | ❌ | проброс порта на роутере, либо туннель (Tailscale/WireGuard), либо публичный релей |
| LoRa-радио | — | ⚠️ | нужен RNode; в Москве LoRa-покрытие Reticulum почти отсутствует (там хорошо работает MeshCore) |

Как узнать адрес Зеро в текущей сети:

- дома — в веб-интерфейсе роутера (список клиентов DHCP), искать по имени хоста;
- в раздаче с телефона — Настройки → Точка доступа → Подключённые устройства;
- либо просто спросить у агента: `hostname -I` / `ip -brief addr show wlan0`.

---

## 12. Второй узел в той же сети (необязательно)

Тот же мост можно поднять на второй машине в той же локальной сети — тогда у каждой будет
свой LXMF-адрес, и телефон сможет писать обеим. Узлы находят друг друга сами по AutoInterface.

Отличия от установки на Zero 3W:

1. Пакеты можно поставить в пользовательский каталог вместо отдельного окружения:
   ```bash
   python3 -m pip install --user --break-system-packages -U rns lxmf
   ```
   тогда бинарники окажутся в `~/.local/bin` (в `PATH` они могут не попасть — в юните
   указывайте полный путь `%h/.local/bin/rnsd`).
2. Юнит `rnsd` берётся из `systemd/rnsd.service`, но `ExecStart` меняется на `%h/.local/bin/rnsd`.
3. В юните моста задаются СВОИ имена файлов и имя узла через окружение (скрипт читает их
   из переменных и по умолчанию рассчитан на Zero):

   ```
   Environment=LXMF_BOT_NAME=Джарвис (Hermes)
   Environment=LXMF_IDENTITY_FILE=/home/<user>/reticulum/jarvis_hermes_identity
   Environment=LXMF_STORAGE=/home/<user>/reticulum/lxmf_storage
   Environment=LXMF_ADDRESS_FILE=/home/<user>/reticulum/jarvis_address.txt
   Environment=LXMF_LOG=/home/<user>/reticulum/bridge.log
   ```
4. Проверка, что узлы видят друг друга (на любой из машин):
   ```bash
   rnpath <адрес узла с другой машины>
   # Path found, destination <...> is 1 hop away via <...> on AutoInterfacePeer[wlan0/...]
   ```

## 13. Независимость канала от VPN

По умолчанию через прокси (если он настроен у агента) идут **только запросы к модели**.
Ни `rnsd`, ни мост прокси не используют: сообщение идёт по локальной сети, и канал работает
даже при выключенном VPN. Чтобы и ответы не зависели от прокси, есть два механизма:

1. **Резервный прямой путь в мосте** — если локальный API не ответил, мост сам идёт к модели
   напрямую, с пустым обработчиком прокси (`ProxyHandler({})`), беря ключ `DEEPSEEK_API_KEY`
   из `~/.hermes/.env`. Работает автоматически, ничего настраивать не нужно.
2. **Drop-in для службы агента** — добавьте домен модели в `NO_PROXY`, чтобы и основной путь
   шёл напрямую. Файл кладётся в
   `~/.config/systemd/user/hermes-gateway.service.d/zz-model-direct.conf`:

```ini
# Drop-in для пользовательской службы Hermes Gateway.
# Кладётся в: ~/.config/systemd/user/hermes-gateway.service.d/zz-model-direct.conf
#
# Зачем: если у шлюза Hermes прописан прокси (HTTP_PROXY/HTTPS_PROXY), то запросы к
# модели тоже идут через него. Тогда канал Reticulum оказывается зависим от VPN.
# Здесь мы добавляем домен модели в NO_PROXY — запрос к модели идёт напрямую.
#
# Имя файла обязательно начинается на zz-, иначе он прочитается РАНЬШЕ основного
# proxy.conf и его значение будет перекрыто.
#
# ВАЖНО: подставьте свои локальные адреса. Telegram при этом продолжает ходить
# через прокси — у него отдельная переменная TELEGRAM_PROXY, её мы не трогаем.
[Service]
Environment=NO_PROXY="127.0.0.1,localhost,.local,192.168.1.0/24,.lan,api.deepseek.com,.deepseek.com"
Environment=no_proxy="127.0.0.1,localhost,.local,192.168.1.0/24,.lan,api.deepseek.com,.deepseek.com"
```

```bash
systemctl --user daemon-reload
systemctl --user show hermes-gateway -p Environment | tr ' ' '\n' | grep -i no_proxy
```

> Имя файла обязательно начинается на `zz-`: drop-in'ы читаются по алфавиту, и он должен
> примениться **после** основного `proxy.conf`. Изменение вступает в силу после перезапуска
> службы (перезапуск из-под самой же сессии агента прервал бы текущий ответ — делайте это
> отдельной командой в терминале или при следующей перезагрузке).

---

## 14. Если что-то не работает

| Симптом | Что проверить |
|---|---|
| Телефон не подключается | `ss -ltn \| grep 4242` — порт слушается? Оба в одной сети? Адрес в приложении совпадает с текущим IP Зеро? |
| Подключился, но сообщения не доходят | `tail ~/reticulum/bridge.log` — есть ли «входящее от …». `rnstatus` — интерфейс Up? |
| Мост не отвечает | `journalctl --user -u hermes-lxmf-bridge -n 30 --no-pager`; проверить локальный API: `curl -s http://127.0.0.1:8642/v1/models -H "Authorization: Bearer $API_SERVER_KEY"` |
| Ответ на другом языке | в мосте есть системная инструкция отвечать по-русски; если модель всё равно уходит в другой язык — усилить формулировку или добавить проверку кириллицы в ответе |
| `AttributeError: type object 'Transport' has no attribute 'owner'` | не вызван `RNS.Reticulum()` до создания `LXMRouter` |
| `LXMessage initialised with invalid source` | в `LXMessage` и получатель, и отправитель должны быть `RNS.Destination`, а не `Identity` |
| Службы пропали после перезагрузки | включить `loginctl enable-linger $USER` и `systemctl --user enable rnsd hermes-lxmf-bridge` |

Полезные команды:

```bash
~/reticulum/venv/bin/rnstatus              # состояние интерфейсов
~/reticulum/venv/bin/rnpath table          # таблица маршрутов Reticulum
journalctl --user -u rnsd -f               # журнал стека
tail -f ~/reticulum/bridge.log             # журнал моста
```

> **Осторожно с шаблонами процессов.** Команды вида
> `pkill -f "<строка, которая есть в вашей же команде>"` убивают собственную оболочку
> (процесс завершается по SIGTERM). Для остановки по имени используйте точное имя
> (`pgrep -x rnsd`) или скрипт-файл.

---

## 15. Удаление

```bash
systemctl --user disable --now hermes-lxmf-bridge rnsd
rm -f ~/.config/systemd/user/{rnsd,hermes-lxmf-bridge}.service
systemctl --user daemon-reload

rm -rf ~/reticulum          # окружение, скрипты, логи
rm -rf ~/.reticulum         # конфиг, ключ узла, хранилище сообщений
```

Ключ узла лежит в `~/reticulum/zero_hermes_identity` (или там, куда его положит скрипт) —
**не публикуйте его**: с ним можно отправлять сообщения от имени узла. Потеря ключа означает
новый адрес узла.

---

## Узел-накопитель: чтобы ответы не терялись

Reticulum доставляет сообщения «здесь и сейчас»: если клиент (телефон) спит и не держит
соединение, доставить некуда — ответ пропадает. Узел-накопитель (LXMF propagation node)
принимает сообщения и хранит их, пока получатель не выйдет на связь.

1. Конфиг `~/.lxmd/config` — пример лежит в `systemd/lxmd-config.example`; главное:
   ```
   [propagation]
     enable_node = Yes
   ```
2. Служба накопителя: юнит `systemd/lxmd.service` скопировать в `~/.config/systemd/user/`,
   затем `systemctl --user enable --now lxmd` (накопитель создаст `~/.lxmd/identity` и `storage/`).
3. Узнать адрес накопителя:
   ```bash
   python3 -c "import RNS; print(RNS.Destination.hash(RNS.Identity.from_file('$HOME/.lxmd/identity'), 'lxmf', 'propagation').hex())"
   ```
4. В юните моста прописать этот адрес: `Environment=LXMF_PROPAGATION_NODE=<адрес>`,
   перезапустить мост. Мост сначала пытается отдать ответ напрямую, а если подтверждения нет —
   кладёт его в накопитель.
5. В приложении на телефоне: **Настройки → Connection → раздел Propagation → Propagation node**.
   Достаточно выбрать **Automatic** — клиент сам выберет ближайший узел по числу переходов;
   конкретный накопитель выбирается в том же списке (виден по имени из `node_name`).
   Кнопка **Sync now** забирает накопленные сообщения вручную.

Как понять, что работает: состояние сообщения `DELIVERED` (8) — отдано напрямую;
`SENT` (4) — принято накопителем, придёт при выходе получателя на связь.
Без накопителя сообщение в такой ситуации не доставляется вообще.

## Приложение: что где слушается

| Порт | Кто | Назначение |
|---|---|---|
| 4242/tcp | `rnsd` | TCP-интерфейс Reticulum для телефона |
| 8642/tcp | агент Hermes | локальный OpenAI-совместимый API |
| 8099/tcp | `python3 -m http.server` (по желанию) | раздача APK телефону |
