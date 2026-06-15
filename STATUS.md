# NeuroMouse — статус проекта и хэндофф

> Подробный обзор: что это за проект, что уже сделано, что осталось, к какому результату идём.
> Дата среза: **2026-06-16**. Текущий `main` = **`def6cda`**, зелёный на Linux CI и **задеплоен** (scope 🅰, мульти-юзер, LIVE).
> **Волна 9 (закалка + интеграция) выкачена в прод; kernel-песочница для чужого кода ДОКАЗАНА на Linux (CI) и подтверждена вживую на проде. Технических блокеров нет — остались два ручных человеко-шага (см. §5).**
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
  - `pytest` — **~200 passed** (postgres-тесты на CI через сервис `postgres:16`); **отдельный CI-джоб `kernel-sandbox-proof`**: `NEUROMOUSE_SANDBOX_KERNEL=required pytest packages/sandbox` = **47 passed / 0 skipped** под реальным Landlock (ABI 7) + seccomp
  - `node --test` — **46/46** (вкл. explain + smoke-тесты маршрутов) + js-юниты **7**; **playwright login-e2e гоняется в CI**
  - `sdk-ts` тесты — **22/22**; `mkdocs build --strict` — чисто
  - 2M-кейсовый deep-fuzz на CI зелёный
  - **`spike_detect` 57/57**; **`dsp.py` 1e-13 цел** на всём протяжении
- **Режим работы: hands-on** — ассистент делает build/git/test сам внутри Claude Code.
- **🚀 ЗАДЕПЛОЕНО на Railway — настоящая МУЛЬТИ-ЮЗЕР платформа (scope 🅰), LIVE:**
  - static **https://neuromouse.up.railway.app** — **маркетинговый лендинг на `/`** (мышь-маскот + чарты на реальных данных, из дизайн-хендоффа), **воркбенч за `/app`** (вход по «try the demo»; старый портрет-герой вырезан → сразу в инструменты), **докдока на `/docs/`** (mkdocs, брендовая тема). same-origin API-proxy → cookie логина first-party; favicon/OG/manifest, брендовый 404 (без SPA-fallback), статик-денилист (исходники/конфиги не отдаются), security-заголовки, корректные MIME. Файлы: `index.html`=лендинг, `app.html`=воркбенч, `landing/`=ассеты лендинга, `site/`=собранная докдока (закоммичена; `Dockerfile` копирует `app.html`+`landing/`+`site/`).
  - backend (FastAPI, per-user auth): **https://backend-production-c7a1.up.railway.app**
  - **Pentest-verified вживую:** `/sessions` без auth → 401; cross-user IDOR → 404 (изолировано, нет утечки в списке); невалидный токен → 401; `/demo/seed-mea` (public) → 201; `/auth/register` → 201.
  - **Login-flow проверен вживую через прод-домен:** register 201 → login 200 → cookie установлен first-party → `/sessions` с cookie 200, без cookie 401.
  - **прод на managed Postgres** (отдельный Railway PG-сервис, приватная сеть `postgres.railway.internal`, reference `DATABASE_URL` на backend); backend **сам применяет миграции при старте** (`schema_migrations` 001/002/003 — проверено вживую). SQLite остаётся dev-default/fallback; собирается из `Dockerfile.backend` через `RAILWAY_DOCKERFILE_PATH` (`environment edit --service-config` в non-TTY shell **не сохраняется** — env-переменная); uvicorn слушает `$PORT`; старый volume `/data` сохранён, но больше не используется.
  - **Что сделано к этому (Волны 6-8):** API auth + rate-limit + CORS, async-очередь джобов + live WS, **sandbox для чужого кода (P1-4) + kernel-слой Linux (seccomp+Landlock)**, Postgres-backend (sqlite default, **CI-проверен на pg**), **per-user auth + ownership** (register/login, `owner_id` на ресурсах, изоляция), **public demo lane** (демо без логина), login frontend, **same-origin proxy** (cross-domain cookie закрыт). pentest-High (публичные сессии) закрыт.
  - **`/api/explain` ВКЛЮЧЁН** — за логином (авторизация по auth-cookie через backend `/auth/me`; `x-explain-token` опционален для API-доступа). Проверено вживую: без cookie → 401, с cookie → 200 + объяснение. **Волна 9: код по умолчанию бьёт в официальный Anthropic (`x-api-key`/`anthropic-version`), kie.ai стал opt-in фоллбэком; прод-env пока оставлен на kie.ai до ручной замены ключа — explain работает как раньше.**

- **🆕 Волна 9 (закалка + интеграция) — ВЫКАЧЕНА в прод** (деплои `abb843ba` backend / `4a3d9be1` static, из `def6cda`):
  - **kernel-песочница ДОКАЗАНА на Linux** — отдельный CI-джоб `kernel-sandbox-proof` (ubuntu-latest): preflight проверяет реальный Landlock (`ABI=7`) + seccomp, затем `NEUROMOUSE_SANDBOX_KERNEL=required pytest packages/sandbox` = **47 passed, 0 skipped**; враждебные пробы (сеть / ФС read-write / subprocess+shell / fork-bomb / symlink+path-traversal escape / OOM / secret-harvest) сдержаны под живой изоляцией; тесты усилены так, что fail-closed **больше не засчитывается за успех**. **Это закрывает гейт безопасности перед открытием загрузки чужого кода.**
  - **подтверждено вживую на проде** — демо-джоб `spike_detect` исполнился на Railway под `required`-режимом с реальным результатом (1024 электрода). Встроенные и пользовательские методы идут через один и тот же `run_in_sandbox`, поэтому успешный прогон = ядро реально держит изоляцию (иначе был бы fail-closed).
  - **PG connection pool** (`psycopg_pool`, миграции один раз на старте — вместо нового соединения на каждый запрос); **observability** (структурные JSON-логи + захват 5xx + лимит тела `NEUROMOUSE_MAX_BODY_BYTES` → 413); **CI: smoke-тесты маршрутов + playwright login-e2e**; **Private Method Lab открыт залогиненным юзерам прямо в `/app`** (анонимная демо-дорожка не тронута).

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
| **9 — Hardening + интеграция (этот чат), DEPLOYED** | 6 веток слиты в `main` и **выкачены в прод**: **kernel-песочница ДОКАЗАНА на Linux** (CI-джоб, Landlock ABI 7, 47 passed, враждебные пробы сдержаны) + **подтверждена вживую на проде** (демо-джоб под `required`); **PG connection pool**; **observability + лимит тела (413)**; **explain → официальный Anthropic по умолчанию** (kie.ai opt-in); **route-smoke + playwright e2e в CI**; **Private Method Lab открыт в `/app`** за логином |

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

### Наружу — блокирующего нет. Остались только **ручные человеко-шаги** (ключи/настройки, ассистент их не делает):
- 🔑 **Ротировать kie.ai-ключ**, засветившийся в чате — гигиена, не функциональность.
- 💾 **Включить daily-бэкапы Postgres** в дашборде Railway.
- *(опционально)* **Дотянуть `/api/explain` до официального Anthropic** — код уже умеет; осталось поставить настоящий `sk-ant-` ключ в `ANTHROPIC_API_KEY` и удалить `EXPLAIN_API_URL` / `EXPLAIN_ALLOW_THIRD_PARTY_API` на static-сервисе, затем редеплой. До этого explain работает через kie.ai.

### Опциональное развитие:
- **OAuth-идентичность** (GitHub/Google) как альтернатива email+password — auth-core спроектирован под подключение.
- Реальные пользователи (друзья-учёные), их методы/сортеры; развитие wetware-трека.

### Закрытые watch-items:
- ✅ **kernel-песочница ДОКАЗАНА на Linux + подтверждена вживую на проде** (Волна 9) — гейт безопасности перед открытием чужого кода закрыт; загрузка методов открыта залогиненным юзерам.
- ✅ **PG connection pooling** (`psycopg_pool`) + **observability** (JSON-логи + 5xx + лимит тела 413) — сделано в Волне 9.
- ✅ **`/api/explain`** — за логином; код переведён на официальный Anthropic по умолчанию (kie.ai opt-in). Проверено вживую.
- ✅ **Managed Postgres в проде** — Railway PG-сервис, backend на нём, миграции применяются автоматически; проверено вживую.
- ✅ **Node 20 → 24** (CI-экшены опт-ин) + **Docker build верифицирован** в проде.
- ✅ **sandbox (P1-4) + kernel-слой / persistence (P1-2) / async (P1-1) / auth + CORS + rate-limit** — Волны 6-8.
- ✅ **cross-domain cookie** — закрыт same-origin proxy (Волна 8).

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

Платформа в проде, зелёная, **Волна 9 выкачена, песочница доказана**. Возможные следующие шаги:
1. Открыть свежий Claude Code в этой папке (`/Users/axel/Documents/SpeedMouse`). Память и `COORDINATOR.md` подтянутся.
2. **Блокеров нет.** Остались два ручных человеко-шага: ротация kie.ai-ключа + daily-бэкапы Postgres (см. §5). После этого — обоснованная **пауза на реальных пилотов**.
3. **Развитие:** официальный Anthropic для explain, OAuth-логин, observability-метрики, wetware-трек — см. §5.
4. Любой код-чейндж: hands-on (build/git/test сам), **push только на зелёном CI**, **деплой наружу — только с явного «го»**.

---

*Этот файл — человеко-читаемый статус. Операционные детали харнесса (роли, шаблоны задач, тиры моделей, конвенции) — в [`COORDINATOR.md`](COORDINATOR.md).*
