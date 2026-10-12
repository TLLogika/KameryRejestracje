# KameryRejestracje

Panel w języku polskim do monitorowania kamer USB i IP oraz odczytu wielu tablic rejestracyjnych przez FastALPR.

## Uruchomienie w Dockerze (Linux)

Wymagane są Docker Engine, Docker Compose, Python 3 i polecenie `ip` na hoście. Python hosta przygotowuje tylko konfigurację; aplikacja i biblioteki OCR działają w kontenerze.

```bash
python3 scripts/configure_docker.py
./docker.sh up -d --build
./docker.sh ps
```

Konfigurator zapisuje adres nasłuchu, UID/GID i mapowania lokalnych urządzeń USB wyłącznie w ignorowanym `dsecret`. Domyślnie wybiera IPv4 interfejsu Tailscale (`tailscale0`); bez VPN wybiera localhost. Panel działa pod `http://ADRES_VPN_MASZYNY:10000`. Inny interfejs/port ustawia się przez zmienne `PANEL_BIND_IP` i `PANEL_PORT` podczas konfiguracji; rzeczywiste adresy pozostają prywatne.

Login `ADMIN`; hasło znajduje się w `dsecret/admin-password.txt`. Istniejące hasło, klucz i baza są używane także po przejściu z uruchomienia natywnego do Dockera. Hasło nie jest drukowane w logach.

Kontener działa jako użytkownik hosta, z dodatkową grupą urządzeń wideo, bez `privileged`, bez dodatkowych capabilities i z systemem plików obrazu tylko do odczytu. Docker udostępnia port wyłącznie na wskazanym adresie hosta. Wewnątrz kontenera aplikacja nasłuchuje na wszystkich jego interfejsach; nie rozszerza to publikacji portu na pozostałe interfejsy hosta.

Trwałe katalogi hosta:

- `data/`: SQLite i pobrane modele w `data/model-cache/`.
- `dsecret/`: hasło ADMIN, jego hash i prywatna konfiguracja wdrożenia.
- `logi/`: rotowane logi operacyjne.
- `secret/integration.key`: jeden plik montowany do kontenera tylko do odczytu. Klucze SSH GitHuba i pozostałe pliki `secret` nie są montowane.

`.dockerignore` dopuszcza do budowania tylko kod i zależności; hasła, adresy wdrożenia, baza, logi, Git i środowisko `.venv` nie trafiają do obrazu. Pierwszy start pobiera modele; następne używają trwałego cache. Jeśli środowisko wymaga certyfikatu proxy, konfigurator obsługuje `CODEX_PROXY_CERT` jako sekret BuildKit i montowanie certyfikatu tylko do odczytu przy uruchomieniu.

Po przepięciu lub dołączeniu kamery odśwież mapowania urządzeń:

```bash
python3 scripts/configure_docker.py
./docker.sh up -d --force-recreate
```

Adresy RTSP/HTTP kamer IP wpisuje się po zalogowaniu. Muszą być osiągalne z kontenera. Docker nie usuwa ograniczeń kontrolera USB; każda kamera musi mieć sprawny strumień na hoście. Przed uruchomieniem kontenera zatrzymaj natywną instancję panelu, aby nie zajmowała portu i kamer.

```bash
./docker.sh logs --tail 50 panel
./docker.sh restart panel
./docker.sh down
```

`down` usuwa kontener i jego sieć; dane w katalogach hosta pozostają. Restart kontenera unieważnia sesje — trzeba zalogować się ponownie. Konfiguracja ma automatyczny restart i healthcheck strony panelu; stan modeli OCR jest dodatkowo widoczny w panelu serwera. Dane CPU/RAM odnoszą się do wartości udostępnionych przez host kontenerowi, RAM procesu dotyczy procesu aplikacji w kontenerze.

## Próba przełączania USB co 5 sekund

Compose domyślnie włącza próbne `USB_ROTATION_SECONDS=5`. Kamery USB pracują kolejno: jedna zbiera obraz przez ustawiony czas (domyślnie 5 sekund) od pierwszej poprawnej klatki, zwalnia strumień, następnie uruchamia się kolejna. Czas otwierania urządzenia wydłuża pełny cykl. Kamery IP nadal pracują równocześnie.

Nieaktywna kamera pokazuje ostatnią klatkę z oznaczeniem „Wstrzymana”. OCR nie analizuje ponownie zatrzymanego obrazu; przy każdej turze zbiera nowe potwierdzenia. Tryb ma przerwy w obserwacji i może przegapić szybki przejazd.

Powrót do równoczesnego przechwytywania bez zmiany bazy i stref:

```bash
USB_ROTATION_SECONDS=0 ./docker.sh up -d --force-recreate
```

Ponowne włączenie próby:

```bash
USB_ROTATION_SECONDS=5 ./docker.sh up -d --force-recreate
```

## Czas i parametry każdej kamery

Po „Powiększ / obszary” zobaczysz rzeczywistą rozdzielczość klatki, FPS zgłoszony przez sterownik, zmierzony FPS przechwytywania, liczbę analiz OCR na sekundę, średni czas analizy, format obrazu, wiek ostatniej klatki i pozostały czas tury. Podczas pauzy bieżące FPS wynoszą zero; pokazane są też ostatnie pomiary aktywnej kamery. Podgląd MJPEG w przeglądarce nadal ma limit około 10 FPS.

Rozwiń „Ustawienia kamery i czas aktywności”. Dla USB możesz zmienić indywidualny czas tury, rozdzielczość, format MJPEG/YUYV oraz FPS. Listy zawierają kombinacje zgłaszane przez urządzenie przez V4L2; nieobsługiwane wartości odrzuca API. Zapis stosuje parametry przy kolejnym otwarciu strumienia i nie wymaga restartu kontenera. Po zmianie rozdzielczości sprawdź obszary detekcji, ponieważ kamera może zmienić pole widzenia.

Minimalny czas to 3 sekundy, zwiększany na podstawie 95. percentyla zmierzonego czasu/częstotliwości analizy: cztery cykle analizy plus 0,5 s zapasu. Domyślnie zalecane jest przynajmniej 5 s. To minimum techniczne, nie gwarancja odczytu — wpływają na niego także oświetlenie, wielkość tablicy i czas obecności pojazdu. Maksymalna tura to 120 s; dłuższa tura wydłuża przerwę pozostałych kamer. Przy wyłączonym przełączaniu (`USB_ROTATION_SECONDS=0`) czas tury nie jest używany.

Parametry kamer IP są odczytywane z otrzymanego obrazu. Rozdzielczość i FPS strumienia IP ustawia się w samej kamerze lub serwerze RTSP; panel nie udaje zdalnej zmiany kodera. Ustawienia USB są przechowywane w SQLite, a istniejąca baza jest migrowana automatycznie bez usuwania kamer ani stref.

Chronione API: `GET /api/cameras/{id}/capabilities` i `PUT /api/cameras/{id}/settings`. Pola ustawień: `rotation_seconds`, `width`, `height`, `fps`, `format`. API listy kamer zawiera `settings` i `metrics`; źródła z danymi logowania nie są w nim ujawniane.

## Uruchomienie bez kontenera (pomocnicze)

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
./run.sh
```

`HOST` i `PORT` wybierają interfejs i port. Domyślnie używany jest IPv4 VPN lub localhost i port 10000. Logowanie używa scrypt; sesje wygasają po 8 godzinach i po restarcie. Zapisy wymagają CSRF. Osiem nieudanych prób logowania blokuje kolejne na 5 minut dla danego adresu.

## Obsługa

1. Zaloguj się i wybierz „Dodaj kamerę”. Lista USB zawiera urządzenia maszyny z możliwością przechwytywania wideo, a nie urządzenia komputera przeglądarki. Urządzenia zajęte przez inny proces mogą być na liście, ale nie udostępniać obrazu.
2. Po lewej wybierz „Kamery” lub „Baza danych”. Zakładka bazy pokazuje przyjazdy, aktualny parking i odjazdy bez podglądów; można wyszukać numer lub fragment rejestracji. Wpisy zawierają czas, kamerę i pewność odczytu, jeśli jest dostępna. Historia pokazuje ostatnie 100 wjazdów i 100 wyjazdów. Przełączenie do bazy zamyka strumienie wideo w przeglądarce; OCR działa dalej na serwerze. Widok jest zapamiętany w adresie (`#database`), więc odświeżenie lub zakładka przeglądarki nie otwierają kamer.

   Kamery są wyświetlane po cztery, w układzie 2×2. Strzałki przełączają kolejne strony.
3. „Powiększ / obszary” otwiera duży podgląd. Wybierz kolor wjazdu/parkingu albo wyjazdu. Każde zaznaczenie w trybie „Nowy obszar” dodaje kolejny prostokąt. Możesz zapisać do 32 zielonych i 32 czerwonych obszarów na kamerę. Wybierz numer, aby przerysować lub usunąć pojedynczy obszar; „Dodaj obszar” wraca do dodawania. Zapisz wszystkie zmiany przyciskiem „Zapisz obszary”. Zielone i czerwone obszary nie mogą się nakładać; obszary tego samego koloru mogą nachodzić na siebie. Dotychczasowe pojedyncze zaznaczenia pozostają obsługiwane. Bez zaznaczonych stref tablice są rozpoznawane, ale nie zmieniają stanu parkingu.
4. Środek wykrytej tablicy określa strefę. Odczyt musi wygrać co najmniej trzy głosy z ostatnich 10 klatek w oknie 12 sekund, mieć co najmniej 60% głosów i pewność OCR co najmniej 80%. Głosowanie odbywa się osobno dla przestrzennych śladów tablic i dla każdej kamery. To próg techniczny, nie gwarancja bezbłędnego OCR — jakość należy sprawdzić na rzeczywistych tablicach i oświetleniu parkingu.
5. Zielona strefa dodaje pojazd do parkingu; czerwona usuwa już obecny pojazd. Powtórzone wjazdy i wyjazdy nie duplikują wpisów. Brak wykrycia nie oznacza automatycznie wyjazdu. Zielona i czerwona strefa muszą odpowiadać rzeczywistemu ruchowi. Kilka kamer obserwujących jednocześnie ten sam pojazd w sprzecznych strefach wymaga poprawienia konfiguracji.
6. Panel serwera rozwija się po lewej: procesor, RAM, temperatura CPU (jeśli czujnik dostępny), load average 1/5/15 minut, RAM całego procesu kamer/panelu i liczba logicznych wątków CPU.

Przechwytywanie działa w osobnym wątku dla każdej kamery. Jeden wspólny proces rozpoznawania analizuje najnowszą klatkę każdej kamery kolejno, bez kolejki zaległych obrazów; modele CPU mają ograniczenie do dwóch wątków i wyłączone aktywne oczekiwanie między analizami. Pętla nie dodaje stałej przerwy 250 ms. Podgląd JPEG ma maksymalnie 1280 pikseli szerokości i skaluje się całkowitym współczynnikiem (dla 1080p: 960 × 540), a OCR korzysta z pełnej klatki; panel pokazuje osobno obie rozdzielczości. Strumień podglądu pozwala wysyłać do 40 klatek/s, ale rzeczywista szybkość zależy od źródła i obciążenia CPU. Wszystkie tablice wykryte na danej klatce są przetwarzane. Przy zwiększaniu liczby kamer spada częstotliwość odczytów na kamerę — należy dobrać liczbę kamer i prędkość przejazdu do wydajności maszyny.

## Dane i integracja

`data/parking.sqlite3`: tabele `cameras`, `events`, `parking`, dziennik WAL. Historia pozostaje po restarcie. Baza, hasła i adresy kamer (mogą zawierać dane logowania) nie trafiają do repozytorium.

API wymaga zalogowania do panelu: `POST /api/login` z JSON `{"username":"ADMIN","password":"…"}` zwraca `csrf` i ustawia ciasteczko sesji. Kolejne żądania używają tego ciasteczka; operacje zapisu także nagłówka `X-CSRF-Token`.

- `GET /api/devices`: lokalne urządzenia USB.
- `GET/POST /api/cameras`: lista/dodawanie kamer.
- `PUT /api/cameras/{id}/zones`: listy prostokątów `arrival`, `departure` ze współrzędnymi `x,y,w,h` w zakresie 0–1; starszy format pojedynczego prostokąta także jest obsługiwany.
- `DELETE /api/cameras/{id}`: usunięcie konfiguracji i zatrzymanie przechwytywania.
- `GET /api/cameras/{id}/stream`: podgląd MJPEG, wymaga sesji.
- `GET /api/parking`: trzy listy; historia w interfejsie to ostatnie 100 wpisów każdej kategorii.
- `GET /api/events?after_id=123`: do 1000 zdarzeń rosnąco po ID. Druga maszyna powinna zapamiętać ostatnie odebrane ID i odpytywać dalej. Dostęp dla drugiej maszyny przez wspólny klucz opisano poniżej.
- `GET /api/server`: rzeczywiste pomiary maszyny i stan modeli OCR.

Log operacyjny: `logi/server.log` z rotacją. Dokumentacja założeń, zmian i technologii: `logi/projekt.md`. `secret/` (klucze SSH) i `dsecret/` (hasła, konfiguracja prywatna) są ignorowane przez Git.

## Testy

```bash
.venv/bin/pip install pytest httpx
.venv/bin/python -m pytest -q
```

Testy obejmują wiele tablic, izolację głosów kamer, wygasanie głosów, deduplikację zdarzeń i eksport, trwałość konfiguracji, logowanie, CSRF, walidację USB/IP i zakaz nakładania stref.

## Połączenie dwóch maszyn: IP i wspólny klucz

Klucz integracji jest generowany przy pierwszym starcie w `secret/integration.key` (uprawnienia 600). To osobny klucz od SSH GitHuba. Skopiuj **ten sam plik** bezpiecznie na drugą maszynę do `secret/integration.key`; nie dodawaj go do GitHuba. API maszynowe jest tylko do odczytu danych parkingu i nie daje dostępu do kamer ani ich konfiguracji.

- `GET /api/integration/events?after_id=0`: zdarzenia, do 1000 na żądanie.
- `GET /api/integration/parking`: aktualny parking i ostatnia historia.
- Uwierzytelnianie: nagłówek `Authorization: Bearer <zawartość pliku integration.key>`.

Odbiornik na drugiej maszynie nie wymaga dodatkowych bibliotek:

```bash
python3 scripts/pull_events.py --url https://ADRES_MASZYNY_KAMER --key-file secret/integration.key --db data/cameras.sqlite3 --interval 2
```

Baza odbiorcy zawiera `camera_events`, `camera_parking`, `sync_cursors`. Pierwsze uruchomienie odtwarza parking z historii, następne pobierają nowe zdarzenia od zapisanego ID. Zapis zdarzeń i kursora jest atomowy; ponowne pobranie nie duplikuje rekordów. `--interval 0` wykonuje jeden odczyt maksymalnie 1000 zdarzeń. Długotrwałe odpytywanie dogania większą historię kolejnymi partiami. Zmiana adresu źródła tworzy osobny strumień w bazie odbiorcy. Zmiana klucza wymaga podmiany pliku na obu maszynach i restartu panelu.

Adres maszyny docelowej nie został jeszcze podany. Aktualny panel nasłuchuje na adresie VPN na porcie 10000. Odbiornik konfiguruje się przez `--url http://ADRES_VPN_MASZYNY:10000`. Dostęp z drugiej maszyny wymaga osiągalności adresu VPN i zezwolenia na TCP/10000; do przesyłania klucza przez sieć użyj HTTPS albo zabezpieczonego tunelu.

## Wyniki sprawdzenia na obecnej maszynie

Testy automatyczne przechodzą. Test przeglądarkowy potwierdził logowanie, dodawanie USB, dostępny obraz, rysowanie i zapis stref, panel serwera i układ mobilny. Rozpoznawanie przetestowano na obrazie referencyjnym FastALPR oraz na dwóch jednoczesnych lokalnych strumieniach MJPEG: potwierdzony wjazd, deduplikacja i wyjazd. Lokalny odbiornik połączył się z API przez klucz.

**Obecne dwie kamery USB nie dostarczają obrazu równocześnie na wspólnym kontrolerze.** Sterownik zgłasza `VIDIOC_STREAMON: No space left on device` także przy 320×240/5 FPS i 640×480/5 FPS. To brak zasobów kontrolera USB, nie brak miejsca na dysku. Każda kamera osobno dostarcza obraz. Należy rozdzielić kamery między kontrolery USB albo poprawić konfigurację przekazywania USB do maszyny wirtualnej. Nie zmieniano modułów jądra ani konfiguracji wirtualizatora.

### Próba z dwoma nagraniami zamiast USB

Panel może tymczasowo zastąpić dwie skonfigurowane kamery USB lokalnymi nagraniami „Car Park” i „Parking Garage” z [UVG-VCM, Ultra Video Group / Tampere University](https://ultravideo.fi/UVG-VCM/index.html). Zbiór jest udostępniany na licencji CC BY 4.0; autorzy proszą o cytowanie: T. Partanen et al., “UVG-VCM: Benchmarking dataset for machine-oriented visual data compression”, QoMEX 2026. Kopie robocze przekonwertowano z podglądów MP4 4K/60 FPS do 1080p/15 FPS. Car Park wydłużono czterokrotnie z 10 do około 40 sekund, wykorzystując kolejne oryginalne klatki 60 FPS, zamiast dodawać powtórzenia do głosowania OCR. Pliki pozostają w ignorowanym katalogu `data/test-videos/` i nie są wysyłane do GitHub.

Przygotowanie pobiera tylko dwie małe wersje MP4 (łącznie około 195 MB), bez surowych plików YUV. Wymaga `ffmpeg` na maszynie. Następnie włącz podmianę:

```bash
python3 scripts/prepare_test_videos.py
python3 scripts/set_test_videos.py
./docker.sh up -d --force-recreate --wait
```

Oba nagrania działają równocześnie w pętli; podczas testu detektor 256 × 256 analizuje skalibrowany obszar drogi obejmujący wszystkie tablice oznaczone przez autorów nagrań (granice wyznaczane z adnotacji z marginesem). OCR odczytuje rzeczywiste wycinki tablic z pełnej klatki; teksty z adnotacji nie są podawane do głosowania. Dla fizycznych kamer pozostaje detektor 384 × 384 i analiza całego obrazu. Obszar oraz rozmiar wejścia detektora są widoczne w powiększonym podglądzie. tytuły podglądów zawierają „TEST” i nazwę filmu. OCR i obszary działają; potwierdzenia z co najmniej trzech różnych przechwyconych klatek zapisują zdarzenia w osobnej bazie `data/test-parking.sqlite3`. Jeśli wszystkie kamery są testowe, panel pokazuje parking i zdarzenia z tej bazy, z oznaczeniem TEST. API zdarzeń i integracja nadal korzystają z właściwej bazy parkingu. Liczba potwierdzeń i ostatnia tablica są widoczne w powiększonym podglądzie. Konfiguracja źródeł USB, ich ustawienia i zaznaczenia pozostają zachowane. Wyłączenie próby:

```bash
python3 scripts/set_test_videos.py --off
./docker.sh up -d --force-recreate --wait
```

Przywraca to fizyczne kamery USB. Plik podmiany `dsecret/test-cameras.json` jest prywatny i nie trafia do obrazu Docker ani repozytorium.
