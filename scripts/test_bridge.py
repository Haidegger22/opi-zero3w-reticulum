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
ADDRESS_FILE = os.path.join(HOME, "reticulum", "zero_address.txt")
TEST_IDENTITY = os.path.join(HOME, "reticulum", "test_identity")
STORAGE = os.path.join(HOME, "reticulum", "lxmf_storage_test")
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
