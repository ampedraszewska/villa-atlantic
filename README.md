# Villa Atlantic — strona wynajmu

Strona statyczna (jeden plik `index.html`) dla willi Villa Atlantic w Puerto de Santiago na Teneryfie.

---

## Jak edytować kalendarz dostępności (instrukcja dla mamy)

Strona automatycznie pokazuje zajęte dni z dwóch Twoich kalendarzy Google:

- **Villa Atlantic — Cliffs** (góra)
- **Villa Atlantic — Gardens** (dół)

**Nic na stronie nie edytujesz.** Wszystko robisz w aplikacji Google Calendar na telefonie albo w przeglądarce (`calendar.google.com`).

### Jak dodać zajęty termin (rezerwację)

1. Otwórz Google Calendar na telefonie.
2. Upewnij się, że patrzysz na właściwy kalendarz — **Cliffs** dla góry albo **Gardens** dla dołu (w ustawieniach możesz wyłączyć widok innych kalendarzy).
3. Kliknij "+" w prawym dolnym rogu → **Wydarzenie**.
4. W tytule wpisz np. `REZERWACJA — 4 osoby` (treść nie ma znaczenia, liczy się tylko zakres dat).
5. Ustaw datę rozpoczęcia (check-in) i datę zakończenia (check-out). **Ważne**: data końcowa to dzień wymeldowania — jeśli gość wyjeżdża 15 maja, wpisz 15 maja jako koniec.
6. Włącz **"Cały dzień"**.
7. W "Kalendarz" wybierz **Villa Atlantic — Cliffs** lub **Villa Atlantic — Gardens** (zależnie, który apartament).
8. Zapisz.

Po 1–2 minutach zajęte dni pojawią się na stronie.

### Jak edytować / usunąć rezerwację

W Google Calendar kliknij na wydarzenie → **Edytuj** albo **Kosz**.

### Uwaga: ta sama data dla góry i dołu = cała willa zajęta

Na stronie w widoku "Cała willa":

- Jeśli **obie** (góra i dół) są zajęte tego samego dnia → dzień pokazuje się jako **zajęty**.
- Jeśli **tylko jedna** z nich jest zajęta → dzień pokazuje się jako **częściowo zajęty** (jeden apartament wciąż wolny).

### Jeśli ktoś rezerwuje całą willę

Dodaj wydarzenie w **obu** kalendarzach (Cliffs + Gardens) na te same daty.

---

## Jak pierwszy raz skonfigurować kalendarze (robi to Aleksandra raz)

1. **Utwórz 2 nowe kalendarze** w Google Calendar:
   - Ustawienia → "Dodaj kalendarz" → "Utwórz nowy kalendarz"
   - Nazwy: `Villa Atlantic — Cliffs` i `Villa Atlantic — Gardens`

2. **Nie udostępniaj kalendarzy publicznie**:
   - Otwórz ustawienia kalendarza (trzy kropki → Ustawienia)
   - "Uprawnienia dostępu" → **nie zaznaczaj** "Udostępnij publicznie"
   - Jeśli było już włączone, odznacz "Udostępnij publicznie" i zapisz. Publiczny link iCal z historii repo nie może działać.

3. **Pobierz prywatny link iCal** dla każdego kalendarza:
   - W ustawieniach kalendarza → sekcja "Zintegruj kalendarz"
   - Skopiuj **"Tajny adres w formacie iCal"** / **"Secret address in iCal format"**
   - Tego linku nie wklejaj do `index.html` ani do commita.

4. **Dodaj linki jako sekrety GitHub Actions**:
   - W repo GitHub: Settings → Secrets and variables → Actions → New repository secret
   - `CLIFFS_ICAL_URL` → prywatny link iCal dla Cliffs
   - `GARDENS_ICAL_URL` → prywatny link iCal dla Gardens
   - Workflow zapisuje bezpieczne pliki `ical/cliffs.ics` i `ical/gardens.ics`; strona czyta tylko je.

5. **Udostępnij kalendarze mamie**:
   - W każdym kalendarzu → Ustawienia → "Udostępnij konkretnym osobom"
   - Dodaj email mamy z uprawnieniami "Dokonywanie zmian w wydarzeniach"

---

## Jak edytować treść strony

Otwórz `index.html` w edytorze tekstu (VS Code, Notepad++, TextEdit). Strona ma trzy języki w jednym pliku, przełączane po stronie przeglądarki (`pl` / `en` / `es`):

- Polski tekst: szukaj `data-lang="pl"`
- Angielski: szukaj `data-lang="en"`
- Hiszpański: szukaj `data-lang="es"`

Każdy widoczny tekst ma trzy wersje rodzeństwa (`en` → `pl` → `es`) w tym samym rodzicu. Edytując treść, zmień wszystkie trzy. Test `tests/test_html_integrity.py` pilnuje, żeby liczba `en`/`pl`/`es` była równa pod każdym rodzicem.

Teksty, których nie da się zrobić rodzeństwem `data-lang` (tytuł strony, meta/OG, temat e-maila formularza, etykiety lightboxa, słowo „Booked" w kalendarzu) siedzą w słowniku `I18N_META` w `<script>` — tam też trzy języki.

Zmień tekst, zapisz, wgraj zmiany na serwer (patrz: deploy).

> **Uwaga (kalendarz, lokalizacja miesięcy):** nazwy miesięcy/dni i przyciski FullCalendar biorą się z paczek lokalizacji ładowanych osobno. **Muszą** pochodzić z `@fullcalendar/core@6.1.15/locales/<lang>.global.min.js` — ścieżka `fullcalendar@6.1.15/locales/*` (bez `@fullcalendar/core`) zwraca **404** i kalendarz zostaje po angielsku.

### Co do uzupełnienia przed publikacją

- Sekrety `CLIFFS_ICAL_URL` i `GARDENS_ICAL_URL` w GitHub Actions → prywatne linki iCal (patrz wyżej)

---

## Deploy na GitHub Pages

Repo: `freezer3/villa-atlantic`. Domena: **`atlanticvilla.net`** (taka jest kolejność słów — nie `villaatlantic.net`).

Każda aktualizacja = commit + push do `main`. Strona odświeża się automatycznie w ~1 minutę. Nie ma kroku budowania.

Konfiguracja, gdyby trzeba było ją kiedyś odtworzyć:

- Settings → Pages → Source: "Deploy from a branch" → Branch: `main` / `/ (root)` → Save
- Plik `CNAME` w repo zawiera `atlanticvilla.net` — **nie usuwaj go**. To jedyne źródło prawdy o domenie: czyta go i GitHub Pages, i canary (niżej)
- Settings → Pages → Custom domain: `atlanticvilla.net` → Save → zaznacz "Enforce HTTPS"
- DNS (Cloudflare):
  - `A` → `185.199.108.153`, `185.199.109.153`, `185.199.110.153`, `185.199.111.153` (IP GitHub Pages)
  - `CNAME` `www` → `freezer3.github.io` (musi wskazywać na **obecnego** właściciela repo — po przeniesieniu repo między kontami trzeba go zaktualizować, inaczej `www` zwraca 404)
- Propagacja DNS trwa 10–60 minut

### Monitoring: canary (`.github/workflows/uptime.yml`)

Co 15 minut pobiera **żywą** stronę i sprawdza, że naprawdę serwuje willę: HTTP 200 + treść naszej strony (nie parkingu domeny ani 404 GitHuba), oba kanały `ical/*.ics` jako prawidłowy `BEGIN:VCALENDAR`, oraz certyfikat TLS ważny jeszcze ponad 14 dni.

Jeśli przyczyną jest konfiguracja Pages w repo (wyłączone Pages, skasowana domena, zmieniona gałąź) — canary **sam ją przywraca** i strona wraca bez udziału człowieka. Run i tak kończy się na czerwono, żeby awaria została w historii Actions.

**Alert = issue na GitHubie** z etykietą `uptime` (powiadomienie mailowe przychodzi normalnym kanałem GitHuba). Świadomie nie SMTP: nie wymaga żadnych sekretów ani hasła aplikacji Gmail. Jedno otwarte issue na całą awarię — kolejne przebiegi nie duplikują alertu — a gdy canary zobaczy zdrową stronę, sam dopisuje komentarz i zamyka issue.

Powód: 2026-08-02 ktoś wyłączył Pages w ustawieniach repo. DNS, TLS, sanitizer i godzinna synchronizacja kalendarzy działały dalej na zielono, a strona przez ten czas zwracała 404 GitHuba — bo nic nigdy nie pobierało żywej strony.

---

## Struktura plików

```
villa-atlantic/
├── index.html              ← jedyny plik strony (HTML + CSS + JS w jednym)
├── README.md               ← ten plik
├── images/
│   ├── hero-poster.jpg     ← obraz wyświetlany zanim załaduje się wideo
│   ├── house/
│   │   ├── outside/        ← basen, klify (Pool1-4, Cliffs, Cliffs2)
│   │   ├── upstairs/       ← zdjęcia Cliffs: Bedroom1-3, Kitchen, Living, Taras1-7, etc.
│   │   └── downstairs/     ← zdjęcia Gardens
│   ├── location/           ← mapa lokalizacji
│   └── surroundings/       ← plaża, miasto, góry, korty tenisowe
└── videos/
    └── hero.mp4            ← wideo hero (15s, 1.7 MB)
```
