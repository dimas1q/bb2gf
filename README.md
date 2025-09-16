# Bitbucket Server/DC → GitFlic Migrator

Утилита переносит **все репозитории** из проектов Bitbucket Server/DC (v8.x) в компанию/команду GitFlic с таким же алиасом.

Поддерживается миграция из **нескольких** проектов за один запуск.

---

## Требования

- Python 3.10+
- Установленные `git` и `git-lfs`
- Доступ к Bitbucket Server/DC (HTTPS/SSH)
- API-токен GitFlic
- Учетные данные Git для GitFlic

---

## Установка

1. Создайте окружение и активируйте его:

  ```bash
  python -m venv .venv
  source .venv/bin/activate  # Windows: .venv\Scripts\activate
  ```

2. Установите зависимости и утилиту:

  ```bash
  python -m pip install --upgrade pip setuptools wheel
  pip install .
  ```

Чтобы удалить утилиту, используйте следующие команды:

```bash
pip uninstall bb2gf
deactivate
```

---

## Конфигурация

Создайте и заполните файл `.env` на основе `.env.example`

Перед запуском миграции убедитесь, что в GitFlic предварительно созданы компании/команды с таким же алиасом, как и у проектов BitBucket, из которых планируется миграция.

---

## Использование

### Запуск миграций без дополнительных опций (используются проекты, указанные в `.env`)

```bash
bb2gf migrate 
```

### Запуск миграций с указанием одного проекта (через URL)

```bash
bb2gf migrate -u https://bitbucket/projects/PROJECT1
```

### Запуск миграций с указанием нескольких проектов (через URL)

```bash
bb2gf migrate \
  -u https://bitbucket/projects/PROJECT1 \
  -u https://bitbucket/projects/PROJECT2
```

### Запуск миграций по ключам (нужен BITBUCKET\_BASE\_URL в `.env`)

```bash
bb2gf migrate -k PROJECT1 -k PROJECT2
```

### Сухой прогон (создание/пуш не выполняются, только логика)

```bash
bb2gf migrate -u https://bitbucket/projects/PROJECT1 --dry-run
```

---

## Вывод и отчёты

Во время миграции по каждому репозиторию выводятся логи и итоговая строка.

В результате выполнения выводятся:

- таблица по проектам (всего/создано/LFS/пропущено/ошибок);
- суммарная панель;
- файлы `report_<project>.json` и `report_all.json` с деталями.&#x20;

---

## Частые проблемы

- **GitFlic 404 Language Not Found**

  - В параметре `LANGUAGE_DEFAULT=` указан несуществующий в GitFlic язык программирования. Исправьте его или оставьте поле пустым.

- **Самоподписанный сертификат Bitbucket**

  - Укажите `BITBUCKET_VERIFY_TLS=false` или путь к `BITBUCKET_CA_CERT`.

---
