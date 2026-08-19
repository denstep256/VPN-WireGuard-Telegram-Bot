# Telegram-бот для WireGuard VPN

Бот управляет платными и пробными VPN-подписками, выдаёт конфигурации через WireGuard Easy, принимает платежи Telegram/YooKassa, поддерживает промокоды, рефералов, уведомления и административные операции.

## Возможности

- покупка и календарное продление подписок на 1, 6 и 12 месяцев;
- одноразовый пробный период на 3 дня;
- проверка вместимости сервера перед оплатой;
- идемпотентная обработка платежей и восстановление незавершённой выдачи;
- промокоды, бонусный баланс и реферальные начисления;
- плановые уведомления и очистка истёкших WireGuard-клиентов;
- рассылки, Excel-отчёты, пинг серверов и ручное управление подписками.

## Требования

- Python 3.10+ (проект проверяется на Python 3.12);
- Linux с установленным `iputils-ping` для проверки серверов из админки;
- WireGuard Easy с v14-совместимым API (`/api/session`, `/api/wireguard/client`);
- Telegram Bot Token и provider token YooKassa;
- SQLite по умолчанию.

## Установка

```bash
sudo apt-get update
sudo apt-get install -y python3 python3-venv iputils-ping ca-certificates

python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp config.example.py config.py
```

Заполните `config.py`. Проверка TLS-сертификата WireGuard Easy отключена в коде, поскольку целевой сервер использует self-signed сертификат. Не публикуйте административный API WireGuard Easy в открытый интернет: ограничьте доступ firewall/VPN или доверенной внутренней сетью.

Запуск:

```bash
.venv/bin/python main.py
```

При старте приложение проверяет обязательную конфигурацию, создаёт каталог для конфигов и применяет совместимые SQLite-миграции. Секреты и сгенерированные `*.conf` не должны попадать в Git.

## Проверки перед деплоем

```bash
.venv/bin/python -m compileall -q main.py app tests
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m pip check
```

После автоматических тестов выполните интеграционные сценарии из [TEST_METHODOLOGY_RU.md](TEST_METHODOLOGY_RU.md) на тестовых Telegram/YooKassa и WireGuard Easy. Локальные тесты намеренно не проводят реальные платежи и не создают клиентов на боевом сервере.

Если WireGuard Easy обновляется до v15 или новее, сначала проверьте контракт API в тестовом окружении: в новых основных версиях схема аутентификации и маршруты могут отличаться от v14-совместимого API этого проекта.

Перед обновлением продакшена сделайте резервную копию SQLite и каталога `app/auth`. Не запускайте одновременно две копии polling-бота с одной БД.

## Запуск через systemd

Шаблон находится в `deploy/vpn-bot.service.example`. Перед установкой замените в нём пользователя и путь `/opt/vpn-wireguard-bot` на фактические значения, затем выполните:

```bash
sudo cp deploy/vpn-bot.service.example /etc/systemd/system/vpn-bot.service
sudo systemctl daemon-reload
sudo systemctl enable --now vpn-bot.service
sudo systemctl status vpn-bot.service
```

Логи процесса доступны через `journalctl -u vpn-bot.service`; прикладные журналы также записываются в каталог `logs`. Пользователь systemd должен иметь права на запись в рабочий каталог, SQLite-файл, `logs` и каталог из `DIR_CONF`.

## Структура

- `app/users` — пользовательские сценарии;
- `app/payments` — цены, платежи, продления и рефералы;
- `app/admin` — административные сценарии;
- `app/planners` — фоновые задания;
- `app/database` — модели и миграции;
- `app/wg_api` — интеграция с WireGuard Easy.

Схема исходной архитектуры: [app/Pictures/drawio.jpg](app/Pictures/drawio.jpg).
