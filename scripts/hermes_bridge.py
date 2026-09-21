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

# Кто я (задаётся в юните службы, чтобы копия скрипта на другом узле не выдавала себя за этот)
SELF_DESCRIPTION = os.environ.get("LXMF_SELF", "Зеро — Hermes на Orange Pi Zero 3W")

# Кто пишет: подставляем имя вместо адреса, иначе агент путает себя с собеседником
SENDERS = {
    "b897f0cb8e4740ad4c4495b2cd83b975": "Артём (смартфон)",
    "c5a087b075a167a3185eaaeaeb1fe777": "Джарвис (Hermes на Raspberry Pi 5)",
    "08e7880033f5b0c18af98bbde8f789b6": "Зеро (Hermes на Orange Pi Zero 3W)",
    "f50f0c41f7b4508930c01a7ed0eb9559": "автотест проверки связи",
    "edfde41e35bb49c67ad8a5efbf1cd742": "автотест проверки связи",
}


def sender_name(hex_hash):
    return SENDERS.get(hex_hash, "неизвестный отправитель " + hex_hash[:8])

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
                "Ты " + SELF_DESCRIPTION + ". Отвечаешь на сообщения, пришедшие через Reticulum "
                "(LXMF-мессенджер). В начале сообщения указано, кто пишет. Ты — не отправитель: "
                "не путай себя с ним и не подписывайся его именем. ОТВЕЧАЙ ТОЛЬКО ПО-РУССКИ, "
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

        # Пути может не быть просто потому, что узел давно не слышал объявление
        # получателя (например телефон подключён к другому узлу сети). Просим сеть
        # дать маршрут и ждём его появления — тогда ответ уйдёт напрямую, а не в накопитель.
        if not has_path:
            try:
                RNS.Transport.request_path(source_hash)
                for _ in range(12):
                    time.sleep(1)
                    if RNS.Transport.has_path(source_hash):
                        has_path = True
                        break
            except Exception:
                has_path = False
            log("маршрут до получателя: %s" % ("найден" if has_path else "не найден"))

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
        who = sender_name(message.source_hash.hex())
        text = "[от %s] %s" % (who, text)
        log("отправитель определён как: " + who)
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
