# Funkcje opcjonalne

Podstawowe uruchomienie opisuje [README](../README.md). Poniższe opcje nie są potrzebne do zwykłego działania parkingu.

## Przełączanie USB

W zakładce **Ustawienia kamer** zaznacz „Pracuj naprzemiennie”. Odznaczenie przywraca równoczesne pobieranie obrazów. Ustawienie zapisuje się w SQLite i obejmuje bezpośrednie USB oraz mostek Windows; IP i kamery testowe pracują stale. Czas każdej kamery jest zapisany w jej ustawieniach. Nieaktywna kamera pokazuje ostatnią klatkę; OCR jej nie przelicza. Przerwy mogą powodować pominięcie przejazdu.

`USB_ROTATION_SECONDS=5` lub `0` ustawia wyłącznie początkowy tryb, zanim administrator zapisze wybór w panelu. Zapisany checkbox ma pierwszeństwo.

## Nagrania demonstracyjne

Najprościej użyj **Dodaj kamerę → Kamera testowa**. Dwa filmy Full HD / 60 FPS są już dołączone do projektu; nie wymagają dodatkowego profilu ani pobierania. [Źródło, autorzy i licencja](../app/demo/ATTRIBUTION.md).

Starsza próba podmiany istniejących USB pozostaje opcjonalna i wymaga jawnego pliku Compose. Linux, Python 3 i FFmpeg:

```bash
python3 scripts/prepare_test_videos.py
python3 scripts/set_test_videos.py
./docker.sh -f compose.demo.yaml up -d --force-recreate --wait
```

Narzędzie pobiera małe MP4 „Car Park” i „Parking Garage” z [UVG-VCM — Ultra Video Group / Tampere University](https://ultravideo.fi/UVG-VCM/index.html), a nie wielogigabajtowe YUV. Licencja CC BY 4.0. Cytowanie: T. Partanen et al., “UVG-VCM: Benchmarking dataset for machine-oriented visual data compression”, QoMEX 2026. Kopie mają 1080p/15 FPS; Car Park jest wydłużony do 40 sekund przy użyciu kolejnych oryginalnych klatek.

Próba zastępuje dwa skonfigurowane USB. Detektor 256×256 analizuje obszar drogi wyznaczony z granic adnotacji; teksty adnotacji nie trafiają do OCR ani do głosowania. Potwierdzenia zapisują się w `data/test-parking.sqlite3`. Przy wszystkich kamerach testowych panel pokazuje bazę testową i oznaczenie TEST. Integracja zawsze czyta właściwą bazę.

Na Windowsie, po przygotowaniu nagrań i pliku podmiany, profil można włączyć przez `docker.ps1 -Demo`. Zwykłe uruchomienie bez `compose.demo.yaml` / `-Demo` wraca do fizycznych kamer, nie zmieniając ich danych. Usunięcie starego pliku podmiany: `python3 scripts/set_test_videos.py --off`.

Wyniki wydajności na tych nagraniach dotyczą ustawionego obszaru drogi, a nie całego obrazu z każdej fizycznej kamery.

## Parametry kamer i diagnostyka

Zakładka **Ustawienia kamer**: rzeczywista rozdzielczość, format, FPS, czas analizy, wiek klatki, wejście detektora i obszar próby. Rozdzielczość/FPS bezpośredniego USB są wybierane spośród trybów V4L2. Dla mostka Windows ustaw je w `windows-usb.ps1`; dla IP — w kamerze lub serwerze RTSP.

Minimalna tura USB: 3 sekundy lub więcej zależnie od szybkości analizy; maksymalnie 120. To pomocnicze minimum, nie gwarancja odczytu. Stan serwera jest osobną rozwijaną pozycją na dole lewego menu.

Podgląd jest skalowany całkowitym współczynnikiem do szerokości maksymalnie 1280 pikseli (z 1080p powstaje 960×540). OCR nadal korzysta z pełnej klatki. Pętla rozpoznawania nie analizuje drugi raz tej samej przechwyconej klatki.

## Integracja drugiej maszyny

Zachowano read-only API: `GET /api/integration/events?after_id=0` z nagłówkiem `Authorization: Bearer KLUCZ`. W obu aplikacjach użyj tego samego prywatnego klucza, nie umieszczaj go w adresie ani repozytorium.

```bash
python3 scripts/pull_events.py --help
```

Odbiornik importuje zdarzenia do lokalnej SQLite i przechowuje kursor, więc ponowienia nie tworzą duplikatów. Konfigurację adresu i klucza przechowuj poza Git. `secret/integration.key` istniejącego wdrożenia nie jest regenerowany przy uruchamianiu.

## Linux bez Dockera

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
./run.sh
```

`HOST` i `PORT` określają nasłuch; domyślnie wybierany jest interfejs Tailscale albo localhost i port 10000. Nie uruchamiaj równolegle dwóch instancji korzystających z tego samego USB lub portu. Skrypty przygotowania Dockera obsługują opcjonalny certyfikat proxy `CODEX_PROXY_CERT`.
