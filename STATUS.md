# NeuroMouse — статус проекта и хэндофф

> Подробный обзор: что это за проект, что уже сделано, что осталось, к какому результату идём.
> Дата среза: **2026-06-13**. Текущий `main` = **`82f5ecc`**, зелёный на Linux CI и **задеплоен** (scope 🅰, мульти-юзер, LIVE).
> Связанные документы: операционный мануал — [`COORDINATOR.md`](COORDINATOR.md); архитектурная критика — [`docs/ARCH-REVIEW.md`](docs/ARCH-REVIEW.md); аудиты — [`audit/`](audit/); позиционирование — [`docs/POSITIONING.md`](docs/POSITIONING.md).

---

## 1. Что это за проект (в одном абзаце)

**NeuroMouse** — это **«слой Hugging Face / Stripe для нейроданных»**: montage-agnostic, plugin-first платформа + SDK, которая стоит **поверх** библиотек анализа (MNE / SpikeInterface = «PyTorch для нейронауки») и слоя сбора сигнала (LSL / BrainFlow = «USB-C для электродов»). Идея — сделать так, чтобы подключить **метод анализа или спайк-сортер было тривиально** (~50 строк кода → живая панель в UI). Прицельная ниша — **wetware / MEA** (живые нейроны на мультиэлектродных матрицах: FinalSpark, Cortical Labs; HD-MEA на 1024+ каналов).

**Зачем именно так:** науку приносят друзья-учёные/инженеры пользователя; платформа снимает с них всю инженерию (контракт данных, воспроизводимость, рендеринг, API), чтобы они «вставляли» свой метод и сразу видели результат. Это и есть **recruiting wedge** — приманка для привлечения людей.

**Аналогии для питча:**
| Слой | Аналог в ML | Что это здесь |
|---|---|---|
| Анализ | PyTorch | MNE / SpikeInterface |
| Железо/сбор | USB-C | LSL / BrainFlow |
| **Платформа поверх** | **Hugging Face / Stripe** | **NeuroMouse** |

---

## 2. Текущее состояние (что есть прямо сейчас)

- **`main` на GitHub** (`github.com/UlaYuga/NeuroMouse`), **полностью зелёный** — локально и на **Linux CI** (Python 3.11/3.12, Node 22; экшены опт-ин на Node 24).
- Метрики зелёного гейта:
  - `pytest` — **188 собрано** (postgres-тесты skip на маке без DSN; на CI их прогоняет сервис `postgres:16` — Волна 8)
  - `node --test` — **39/39** + js-auth **7 pass / 1 skip**; sandbox — **46**
  - `sdk-ts` тесты — **22/22**; `mkdocs build --strict` — чисто
  - 2M-кейсовый deep-fuzz на CI зелёный
  - **`spike_detect` 57/57**; **`dsp.py` 1e-13 цел** на всём протяжении
- **Режим работы: hands-on** — ассистент делает build/git/test сам внутри Claude Code.
- **🚀 ЗАДЕПЛОЕНО на Railway — настоящая МУЛЬТИ-ЮЗЕР платформа (scope 🅰), LIVE:**
  - static (login UI + демо + viewer, **same-origin API-proxy → cookie логина first-party**): **https://neuromouse.up.railway.app**
  - backend (FastAPI, per-user auth): **https://backend-production-c7a1.up.railway.app**
  - **Pentest-verified вживую:** `/sessions` без auth → 401; cross-user IDOR → 404 (изолировано, нет утечки в списке); невалидный токен → 401; `/demo/seed-mea` (public) → 201; `/auth/register` → 201.
  - **Login-flow проверен вживую через прод-домен:** register 201 → login 200 → cookie установлен first-party → `/sessions` с cookie 200, без cookie 401.
  - **прод на managed Postgres** (отдельный Railway PG-сервис, приватная сеть `postgres.railway.internal`, reference `DATABASE_URL` на backend); backend **сам применяет миграции при старте** (`schema_migrations` 001/002/003 — проверено вживую). SQLite остаётся dev-default/fallback; собирается из `Dockerfile.backend` через `RAILWAY_DOCKERFILE_PATH` (`environment edit --service-config` в non-TTY shell **не сохраняется** — env-переменная); uvicorn слушает `$PORT`; старый volume `/data` сохранён, но больше не используется.
  - **Что сделано к этому (Волны 6-8):** API auth + rate-limit + CORS, async-очередь джобов + live WS, **sandbox для чужого кода (P1-4) + kernel-слой Linux (seccomp+Landlock)**, Postgres-backend (sqlite default, **CI-проверен на pg**), **per-user auth + ownership** (register/login, `owner_id` на ресурсах, изоляция), **public demo lane** (демо без логина), login frontend, **same-origin proxy** (cross-domain cookie закрыт). pentest-High (публичные сессии) закрыт.
  - `/api/explain` на static — пока safe 503; enabled-path покрыт тестами (Волна 8), включить: `EXPLAIN_TOKEN` + `ANTHROPIC_API_KEY` на `speedmouse`.

---

## 3. Что уже сделано (по волнам)

Проект строился «волнами» (wave) — пачками параллельных задач, каждая в своём git-worktree, с само-проверяющим зелёным гейтом, затем батч-мерж в `main`.

| Волна | Что сделано |
|---|---|
| **0 — Фундамент** | Исполняемый контракт данных + **DSP bit-exact парность** (1e-13) |
| **1 — Закалка** | Убраны 3 класса багов, найденных фаззером; скелет **FastAPI-бэкенда**; **method-SDK/реестр**; адаптеры + conformance; TS-контракт; фикс окружения |
| **2 + 2.5 — Вертикальный срез** | Детерминированный **run-engine**; реальные бэкенд-джобы + SQLite + WebSocket; либрализация фронтенда; **живой срез: метод → панель** (демо) |
| **3 — Wetware / MEA** | **HD-MEA адаптер**; шаблоны MEA-методов (`spike_detect`, `network_burst`, `electrode_connectivity`); шов **«принеси свой спайк-сортер»** (`packages/sorting`); манифест воспроизводимости; MEA-доки; контракт сырых MEA-трейсов |
| **4 — Глубокая (этот чат)** | MEA-демо бэкенд (`POST /demo/seed-mea` + 3 метода) + фронтенд (seed→spike_detect→панель + **скриншот wetware**); **adversarial security audit v2**; **perf**: `electrode_connectivity` ускорен **~70×** (13.9с → 0.2с) при сохранении ground-truth; fuzz-until-dry (8 новых таргетов); архитектурная критика |
| **5 — Ship (этот чат)** | **docs-site** (mkdocs-material); **example-скрипт** `examples/quickstart_mea.py`; **docker-compose** (статик + FastAPI-бэкенд, профили под оба сценария) |
| **6 — Production hardening** | API auth-token + rate-limit + CORS + health; **async-очередь джобов + live WS** вне event-loop (P1-1); **Postgres-backend** + миграции (sqlite по умолчанию, P1-2); **sandbox для чужого кода методов/сортеров (P1-4)**; фронт→prod-backend; arch P1-3 (`mea.n_samples`); CloseEvent node22 CI-фикс |
| **7 — Per-user auth** (rebuilt hands-on) | auth-core (register/login/logout/me, pbkdf2, storage-backed session-токены, httpOnly-cookie); `owner_id` на каждой сессии/датасете/джобе (миграция 003, owner-scoped запросы); per-user authz middleware; **public anonymous demo lane**; login frontend. pentest-High (анонимные сессии) закрыт |
| **8 — Polish (этот чат)** | postgres-suite **runtime-проверена на CI** (`postgres:16` + `DATABASE_URL`); browser-verified login e2e + UI-фиксы/скриншоты; **kernel-sandbox Linux** (seccomp-bpf + Landlock + `no_new_privs`); `/api/explain` enabled-path тесты + infra-доки; **cross-domain cookie закрыт** (same-origin proxy → cookie first-party) |

**Дополнительно в этом чате (важное):**
- 🔴 **Закрыта живая дыра безопасности V2-01** (`/api/explain`): была открытая неаутентифицированная LLM-ручка, утекавшая API-ключ на сторонний хост. Добавлены auth-токен, rate-limit, официальный хост по умолчанию, CORS-allowlist.
- 🔧 **Вскрыт и закрыт скрытый долг: CI был красным с 11 июня** (а локально выглядел зелёным). Две причины:
  1. `CloseEvent` — не глобал на Linux node22 (на маке есть) → падал тест-мок. Добавлен фоллбэк.
  2. **arch P1-3**: длина MEA-трейсов не была закреплена в контракте (проверялась «сама на себя»). Добавлено поле **`mea.n_samples`** синхронно во **всех 4 точках контракта** + golden/fixtures.

---

## 4. Архитектура (ключевые узлы)

```
┌─ contracts/         pydantic-контракт + JSON Schema (источник истины данных)
├─ packages/
│   ├─ core/          ★ dsp.py — СВЯЩЕННЫЙ (bit-exact 1e-13, НИКОГДА не править)
│   │                 run-engine: детерминизм, canonical JSON, SHA-256 манифест
│   ├─ backend/       FastAPI: сессии, джобы, SQLite-хранилище, WebSocket
│   ├─ web/ + js/     фронтенд: viewer, panels/method-panel.js, sources/, workbench
│   ├─ sdk/           Python-SDK для авторов методов (+ examples)
│   ├─ sdk-ts/        TS-типы + схема + валидатор контракта
│   ├─ adapters/      HD-MEA (mea.py), file_replay, brainflow, DANDI-ingest
│   └─ sorting/       шов «принеси свой сортер» (Kilosort/SpikeInterface)
├─ methods/           MEA-методы: spike_detect, network_burst, electrode_connectivity
├─ bench/             perf_harness.py — бенчмарки на 1024-ch
├─ tests/             pytest + node --test + property/ + fuzz/
├─ datasets/golden/   mea_synthetic.json — эталон 1024 канала × 64 сэмпла, 57 спайков
├─ docs/              ARCHITECTURE, POSITIONING, ARCH-REVIEW, MEA_QUICKSTART, adr/
├─ audit/             security-аудиты v1 (agent-1..8) + v2 (REPORT-v2)
├─ infra/ + Dockerfile + docker-compose.yml   деплой
└─ .github/workflows/ci.yml   Linux-гейт (py3.11/3.12, node22)
```

**Контракт данных enforced в 4 местах одновременно** (правило: держать синхронными):
1. pydantic — `contracts/src/neuromouse_contract/dataset.py`
2. JSON Schema — `contracts/schema/dataset.schema.json`
3. TS-валидатор — `packages/sdk-ts/`
4. JS-валидатор — `js/sources/static-source.js`

---

## 5. Что осталось сделать (план)

Платформа **развёрнута (scope 🅰)**, зелёная на CI и проверена вживую — **блокирующего ничего нет**. Остаётся опциональное и **наружу (нужно явное «го»)**.

### Наружу (требует явного разрешения):
- **Включить `/api/explain`** — сейчас safe 503; задать `EXPLAIN_TOKEN` + `ANTHROPIC_API_KEY` на сервисе `speedmouse`. Enabled-path уже покрыт тестами (Волна 8) — не хватает только живых секретов.

### Опциональное развитие:
- **OAuth-идентичность** (GitHub/Google) как альтернатива email+password — auth-core спроектирован под подключение.
- **Observability** на backend (структурные логи, трейсинг, метрики) — для реальной мульти-юзер нагрузки.
- **Connection pooling для PG** — сейчас `PostgreSQLBackendStore._connect()` открывает новое соединение на каждый запрос и проверяет миграции; при росте нагрузки добавить пул (psycopg_pool).
- **Лимит памяти / размерности** на тело запроса (memory-DoS) — последняя часть P1-3.

### Закрытые watch-items:
- ✅ **Managed Postgres в проде** — Railway PG-сервис поднят, backend на нём (приватная сеть, reference `DATABASE_URL`), миграции применены автоматически; проверено вживую (свежий юзер + сессия легли в PG).
- ✅ **Node 20 → 24:** CI-экшены опт-ин через `FORCE_JAVASCRIPT_ACTIONS_TO_NODE24` (дедлайн ~16 июня пройден заранее).
- ✅ **Docker build верифицирован** — backend и static реально собираются и стартуют в проде.
- ✅ **sandbox (P1-4) + kernel-слой / persistence (P1-2) / async (P1-1) / auth + CORS + rate-limit** — сделано в Волнах 6-8.
- ✅ **cross-domain cookie** — закрыт same-origin proxy (Волна 8 / этот чат).

---

## 6. Главная развилка: scope деплоя 🅰 vs 🅱 — ✅ РЕШЕНО (выбран 🅰, развёрнут)

Это **решает, что вообще деплоить** и сколько ещё работы. Архитектурная критика (`docs/ARCH-REVIEW.md`) называет это ключевым вопросом.

| | 🅰 Хостед-платформа | 🅱 Workbench + публичное демо |
|---|---|---|
| Что это | Мульти-юзер сервис, чужой код на общем хосте («слой Hugging Face» по-настоящему) | Single-user dev-инструмент + статичная демо-страница + pip-устанавливаемый SDK |
| Что деплоим | Статик **+ FastAPI-бэкенд** | Статик-демо (wetware-скриншот **уже есть**) + docs-site + SDK |
| Что ещё нужно | sandbox, persistent storage, auth, async, лимиты (см. §5) | почти ничего — оно готово |
| Срок | Большой трек | Быстрый «demo-able handoff» |

**Решение (принято и выполнено):** выбран путь **🅰 — хостед мульти-юзер платформа**, и она **развёрнута на Railway** (см. §2). Изначально ассистент рекомендовал начать с 🅱 ради скорости демо, но пользователь повёл сразу в 🅰: sandbox (+ kernel-слой), persistence, async, auth и per-user ownership реализованы (Волны 6-8) и работают в проде. Развилка закрыта.

---

## 7. К какому результату идём

- **Ближняя цель (≈5 волн):** серьёзный, **демонстрируемый хэндофф** — «вставь свой метод/сортер → получи живую панель». ✅ **Достигнута и перевыполнена.**
- **Средняя цель:** развернуть **🅰 хостед-платформу** (с песочницей и persistence) — обещание позиционирования. ✅ **Сделано:** мульти-юзер, per-user ownership, sandbox (+ kernel-слой), persistence, async, auth — LIVE на Railway (Волны 6-8).
- **Дальняя цель (остаётся):** стать дефолтным «слоем поверх» для wetware/MEA-сообщества — местом, куда плагином приносят метод/сортер, как модель на Hugging Face. Дальше — реальные пользователи (друзья-учёные), их методы/сортеры, и развитие из §5.

---

## 8. Важные правила и подводные камни (не нарушать)

- ★ **НИКОГДА не трогать `packages/core/src/neuromouse_core/dsp.py`** — bit-exact парность 1e-13, проверяется в каждом гейте.
- **Контракт данных правится сразу в 4 местах** (pydantic / JSON Schema / sdk-ts / js) — иначе рассинхрон.
- **Не ослаблять тесты/фаззеры** ради зелёного — чинить код.
- **Push только на зелёном**, fast-forward, без force. **Деплой наружу — только с явного «го».**
- **Окружение mac vs Linux:** локально `node --test` может быть зелёным, а Linux CI — нет (разные глобалы, напр. был `CloseEvent`). **Доверять Linux CI**, не только маку. Тяжёлые гейты (2M-fuzz) гонять на CI, а не греть мак.
- **macOS native-stall:** при зависании native-расширения — `NEUROMOUSE_NATIVE_PREWARM=0` или `uv sync --link-mode=copy`.

---

## 9. Как продолжить, когда вернёшься

Платформа уже в проде и зелёная. Возможные следующие шаги:
1. Открыть свежий Claude Code в этой папке (`/Users/axel/Documents/SpeedMouse`). Память и `COORDINATOR.md` подтянутся.
2. **Наружу (с явного «го»):** включить `/api/explain` (секреты `EXPLAIN_TOKEN` + `ANTHROPIC_API_KEY` на `speedmouse`) — см. §5. Managed Postgres уже подключён.
3. **Развитие:** OAuth-логин, observability, лимит памяти на тело запроса — см. §5.
4. Любой код-чейндж: hands-on (build/git/test сам), **push только на зелёном CI**, **деплой наружу — только с явного «го»**.

---

*Этот файл — человеко-читаемый статус. Операционные детали харнесса (роли, шаблоны задач, тиры моделей, конвенции) — в [`COORDINATOR.md`](COORDINATOR.md).*
